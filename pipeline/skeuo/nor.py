"""
The NOR flash of a new device before its first restore: the factory data (syscfg: model, region, serial number) and
an NVRAM with the default environment. The restore flashes the boot images (LLB, iBoot, device tree, logos) itself.
"""
import struct
import zlib

NOR_SIZE = 1024 * 1024
SYSCFG_OFFSET = 0x4000
NVRAM_OFFSET = 0xFC000
NVRAM_SIZE = 0x2000

DEFAULT_SYSCFG = {
    "Mod#": "MA623",
    "Regn": "B/LL",
    "SrNm": "1A8478BH203",
    "Batt": "690476146348",
}

DEFAULT_ENV = {
    "debug-uarts": "1",
    "btaddr": "00:23:32:6B:38:E2",
    "wifiaddr": "00:23:32:6E:AA:10",
}


def fourcc(tag):
    # a C multi-character constant like 'SCfg', stored as a little endian word
    return struct.pack("<I", int.from_bytes(tag.encode(), "big"))


def syscfg(entries):
    data = struct.pack("<4sIIIII", fourcc("SCfg"), 200, 0x2000, 0x00010001, 0, len(entries))
    for tag, value in entries.items():
        data += fourcc(tag) + value.encode().ljust(16, b"\0")
    return data


def chrp_header(sig, length, name):
    """A CHRP NVRAM partition header: signature, checksum, length in 16-byte units, name."""
    header = bytearray(struct.pack("<BBH12s", sig, 0, length, name.encode()))
    c = sig
    for b in header[2:16]:
        c = (c + b) & 0xffff
    while c > 0xff:
        c = (c >> 8) + (c & 0xff)
    header[1] = c
    return header


def nvram(env):
    data = bytearray(NVRAM_SIZE)
    data[0x20:0x30] = chrp_header(0x70, 0x80, "common")
    variables = b"".join(b"%s=%s\0" % (k.encode(), v.encode()) for k, v in env.items())
    data[0x30:0x30 + len(variables)] = variables
    data[0x820:0x830] = chrp_header(0xA1, 0x81, "APL,OSXPanic")
    data[0x1030:0x1040] = chrp_header(0x7F, 0xFD, "wwwwwwwwwwww")

    # the Apple header: a CHRP header for the whole NVRAM, an adler32 of everything after it, and a generation
    struct.pack_into("<II", data, 0x10, 0, 0x10)
    adler = zlib.adler32(bytes(data[0x14:]))
    struct.pack_into("<I", data, 0x10, adler)
    header = bytearray(struct.pack("<BBH12s", 0x5A, 0, 0x2, b"nvram"))
    data[0:0x10] = header
    data[1] = chrp_header(0x5A, 0x2, "nvram")[1]
    return bytes(data)


def factory_nor(syscfg_entries=None, env=None):
    nor = bytearray(NOR_SIZE)
    cfg = syscfg(syscfg_entries or DEFAULT_SYSCFG)
    nor[SYSCFG_OFFSET:SYSCFG_OFFSET + len(cfg)] = cfg
    nor[NVRAM_OFFSET:NVRAM_OFFSET + NVRAM_SIZE] = nvram(env or DEFAULT_ENV)
    return bytes(nor)
