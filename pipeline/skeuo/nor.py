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


def factory_nor(syscfg_entries, env):
    """syscfg_entries and env come from identity.py."""
    nor = bytearray(NOR_SIZE)
    cfg = syscfg(syscfg_entries)
    nor[SYSCFG_OFFSET:SYSCFG_OFFSET + len(cfg)] = cfg
    nor[NVRAM_OFFSET:NVRAM_OFFSET + NVRAM_SIZE] = nvram(env)
    return bytes(nor)


def set_nvram_variables(path, changes):
    """Update the newest valid bank, preserving its other variables/partitions.

    Write the other bank with a newer generation, as the guest does. In 1.x,
    restored clears boot-args; preparation reinstates the tested normal args.
    """
    with open(path, "r+b") as stream:
        banks = []
        for offset in (NVRAM_OFFSET, NVRAM_OFFSET + NVRAM_SIZE):
            stream.seek(offset)
            bank = bytearray(stream.read(NVRAM_SIZE))
            if (len(bank) == NVRAM_SIZE and bank[0] == 0x5a and bank[4:9] == b"nvram"
                    and struct.unpack_from("<I", bank, 0x10)[0] == zlib.adler32(bank[0x14:])):
                banks.append((struct.unpack_from("<I", bank, 0x14)[0], offset, bank))
        if not banks:
            raise ValueError("NOR has no valid NVRAM bank")
        generation, active, bank = max(banks, key=lambda item: item[0])
        offset = 0x20
        while offset + 16 <= len(bank):
            length = struct.unpack_from("<H", bank, offset + 2)[0] * 16
            if length < 16 or offset + length > len(bank):
                break
            if bank[offset + 4:offset + 16].split(b"\0")[0] == b"common":
                env = dict(item.split(b"=", 1) for item in bytes(bank[offset + 16:offset + length]).split(b"\0")
                           if b"=" in item)
                env.update({key.encode(): value.encode() for key, value in changes.items()})
                data = b"".join(key + b"=" + value + b"\0" for key, value in env.items())
                if len(data) > length - 16:
                    raise ValueError("NVRAM common variables do not fit")
                bank[offset + 16:offset + length] = data.ljust(length - 16, b"\0")
                struct.pack_into("<I", bank, 0x14, (generation + 1) & 0xffffffff)
                struct.pack_into("<I", bank, 0x10, zlib.adler32(bank[0x14:]))
                target = NVRAM_OFFSET + NVRAM_SIZE if active == NVRAM_OFFSET else NVRAM_OFFSET
                stream.seek(target)
                stream.write(bank)
                return
            offset += length
        raise ValueError("NVRAM has no valid common partition")
