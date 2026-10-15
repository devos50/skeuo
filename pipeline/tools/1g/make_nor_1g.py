"""Builds a test NOR for the iPod touch 1G from an extracted 1.1.x IPSW:
python3 make_nor_1g.py <ipsw dir> <out> [boot-args]"""
import hashlib, os, struct, subprocess, sys, zlib

KEY = "188458A6D15034DFE386F23B61D43774"
# The emulator's UID key (key_uid in ipod_touch_aes.h). LLB checks an image header's signature at 0x3e0: the SHA-1 of
# the header before it plus 12 fixed bytes, AES-128-CBC encrypted with zero IV under a key that is itself
# HEADER_KEY_SEED encrypted with the UID key and HEADER_KEY_IV. A restore writes it; here it's done with openssl.
UID = "0123456789ABCDEF0123456789ABCDEF"
HEADER_KEY_SEED = "cdf345b312e748858bbe2147f0e58088"
HEADER_KEY_IV = "41705d116f984b829c6c99bba5f17869"
# The data is signed the same way, at 0x20: the SHA-1 of the (encrypted) data plus 44 fixed bytes, the first 12 of
# which are the header's. With flag bit 9 the data is also encrypted with that key, as a restore leaves it.
DATA_PAD = bytes.fromhex("ad2ee38d2d9be43599044433653df07498d8563b4ff96a5545ce82f29a5ac2bc47616d654f766572a6a09913")
HEADER_PAD = DATA_PAD[:12]
GRANULE = 0x40
IMAGES = [("LLB.n45ap.RELEASE", b"llbz"), ("iBoot.n45ap.RELEASE", b"ibot"), ("DeviceTree.n45ap", b"dtre"),
          ("applelogo", b"logo"), ("needservice", b"nsrv"), ("batterycharging", b"batC"),
          ("batterylow0", b"batl"), ("batterylow1", b"batL"), ("recoverymode", b"recm")]

def unwrap(path):
    d = open(path, "rb").read()
    assert d[:4] == b"8900", path
    size = struct.unpack("<I", d[0xc:0x10])[0]
    data = d[0x800:0x800 + size]
    if d[7] == 3:
        data = subprocess.run(["openssl", "enc", "-d", "-aes-128-cbc", "-K", KEY, "-iv", "0" * 32, "-nopad"],
                              input=data, capture_output=True, check=True).stdout
    return data

def aes_encrypt(key, iv, data):
    return subprocess.run(["openssl", "enc", "-e", "-aes-128-cbc", "-K", key, "-iv", iv, "-nopad"],
                          input=data, capture_output=True, check=True).stdout

def install(img):
    """Does to an image what a restore does before writing it to the NOR (see main)."""
    key = aes_encrypt(UID, HEADER_KEY_IV, bytes.fromhex(HEADER_KEY_SEED)).hex()
    data_len = struct.unpack_from("<I", img, 0x10)[0]
    whole = data_len & ~0xf  # the engine leaves a partial last block as it is
    img[0x400:0x400 + whole] = aes_encrypt(key, "0" * 32, bytes(img[0x400:0x400 + whole]))
    flags = struct.unpack_from("<I", img, 0x1c)[0] | 0x01000000 | 0x200 | 0x2
    struct.pack_into("<I", img, 0x1c, flags)
    img[0x20:0x60] = aes_encrypt(key, "0" * 32, hashlib.sha1(bytes(img[0x400:0x400 + data_len])).digest() + DATA_PAD)
    struct.pack_into("<I", img, 0x60, struct.unpack_from("<I", img, 0x60)[0] + 0xc)
    struct.pack_into("<I", img, 0x64, zlib.crc32(bytes(img[:0x64])))
    img[0x3e0:0x400] = aes_encrypt(key, "0" * 32, hashlib.sha1(bytes(img[:0x3e0])).digest() + HEADER_PAD)

# iBoot's NVRAM (FUN_18004b74, FUN_18008576 in iBoot 1.1.5): two banks of 0x2000 at the end of nor0, the one with
# the highest epoch wins. A bank is CHRP NVRAM: a 0x5a "nvram" header with an Adler-32 of 0x14 to the end at 0x10 and
# the epoch at 0x14, then partitions from 0x20 (signature, header checksum, length in 16 bytes, 12-byte name, data)
# up to a 0x7f free partition. Partition "common" (0x70) holds the variables, "name=value" strings ending in a zero.
NVRAM_BANK = 0x2000
DEFAULT_BOOT_ARGS = "serial=1 debug=0x8 -v"

def chrp(sig, name, data):
    h = bytearray(struct.pack("<BBH12s", sig, 0, (0x10 + len(data) + 0xf) // 0x10, name))
    c = h[0] + sum(h[2:0x10])
    while c > 0xff:
        c = (c >> 8) + (c & 0xff)
    h[1] = c
    return bytes(h) + data.ljust((len(data) + 0xf) & ~0xf, b"\0")

def nvram(variables, epoch):
    # debug-uarts is a mask of the UARTs iBoot writes its console to (bit 0, UART0); iBoot passes boot-args on.
    common = b"".join(b"%s=%s\0" % (k.encode(), v.encode()) for k, v in variables)
    parts = chrp(0x70, b"common", common.ljust(0x7f0, b"\0"))
    bank = bytearray(chrp(0x5a, b"nvram", struct.pack("<II", 0, epoch).ljust(0x10, b"\0")) + parts)
    bank += chrp(0x7f, b"w" * 12, b"\0" * (NVRAM_BANK - len(bank) - 0x10))
    struct.pack_into("<I", bank, 0x10, zlib.adler32(bytes(bank[0x14:])))
    return bytes(bank)

def main(ipsw, out, boot_args=DEFAULT_BOOT_ARGS):
    fw = os.path.join(ipsw, "Firmware/all_flash/all_flash.n45ap.production")
    nor = bytearray(0x100000)
    cfg = struct.pack("<4sIIIII", b"gfCS", 200, 0x2000, 0x00010001, 0, 0)
    nor[0x4000:0x4000 + len(cfg)] = cfg
    sb = bytearray(struct.pack("<4sIIII", b"2GMI", GRANULE, 0x410, 0, 0x80000 // GRANULE).ljust(0x30, b"\0"))
    nor[0x8400:0x8434] = sb + struct.pack("<I", zlib.crc32(bytes(sb)))
    off = 0x410 * GRANULE
    for name, tag in IMAGES:
        img = bytearray(unwrap(os.path.join(fw, name + ".img2")))
        assert img[:4] == b"2gmI" and img[4:8] == tag[::-1], (name, img[:8])
        data_len = struct.unpack("<I", img[0x10:0x14])[0]
        total = (0x400 + data_len + GRANULE - 1) // GRANULE * GRANULE
        # A restore records the length in granules, encrypts the data and signs it (flags 9 and 1), marks the image
        # as installed (flag 24), makes the size of the first extension (at 0x60, its data's length in the IPSW)
        # cover what the extension's CRC covers (0x6c to the end of the data), redoes the header's CRC and signs
        # the header.
        struct.pack_into("<I", img, 0x18, total // GRANULE)
        install(img)
        nor[off:off + total] = bytes(img[:total]).ljust(total, b"\0")
        print("%s at 0x%x, 0x%x bytes" % (tag.decode(), off, total))
        off += total
    assert off <= len(nor) - 2 * NVRAM_BANK
    nor[len(nor) - 2 * NVRAM_BANK:len(nor) - NVRAM_BANK] = nvram([("debug-uarts", "1"), ("boot-args", boot_args)], 1)
    nor[len(nor) - NVRAM_BANK:] = b"\xff" * NVRAM_BANK
    open(out, "wb").write(nor)

main(*sys.argv[1:])
