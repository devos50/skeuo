"""Build-specific repairs to firmware supplied by the user for the S5L8900.

Nothing here contains a firmware image. The 4B1 USB wrangler removes its PHY
publication notifier from a callback that can run before addNotification returns
and stores that notifier. Guard the removal when it is still null. This replaces
one diagnostic printf call to make room without moving code. In that case the
notifier remains registered for the lifetime of the wrangler.
"""
import struct
import subprocess
import zlib

KEY_837 = "188458A6D15034DFE386F23B61D43774"
KERNEL_PATH = "/System/Library/Caches/com.apple.kernelcaches/kernelcache.s5l8900xrb"
DEFAULT_BOOT_ARGS = "serial=1 debug=0x8 -v"
ROOTFS_KEYS = {
    "4B1": "c7973558e8f6af22e38d4573737d1533f1d5eec202bf86a32d941975d76f8906c7f0afe4",
}


def unpack_8900(image):
    if len(image) < 0x800 or image[:4] != b"8900":
        raise ValueError("not an 8900 container")
    size = struct.unpack_from("<I", image, 12)[0]
    payload = image[0x800:0x800 + size]
    if len(payload) != size:
        raise ValueError("truncated 8900 payload")
    if image[7] == 3:
        payload = subprocess.run(
            ["openssl", "enc", "-d", "-aes-128-cbc", "-K", KEY_837,
             "-iv", "0" * 32, "-nopad"], input=payload, capture_output=True, check=True).stdout
    elif image[7] != 4:
        raise ValueError("unsupported 8900 format %d" % image[7])
    return payload


def decompress_kernel(payload):
    if len(payload) < 0x180 or payload[:8] != b"complzss":
        raise ValueError("not a compressed kernel")
    checksum, size, count = struct.unpack_from(">III", payload, 8)
    if size > 32 << 20 or count > len(payload) - 0x180:
        raise ValueError("invalid compressed kernel size")
    src = payload[0x180:0x180 + count]
    ring = bytearray(b" " * 4096)
    write = 4096 - 18
    out = bytearray()
    i = 0
    while i < len(src) and len(out) < size:
        flags = src[i]
        i += 1
        for bit in range(8):
            if len(out) == size:
                break
            if i >= len(src):
                raise ValueError("truncated LZSS token")
            if flags & (1 << bit):
                values = [src[i]]
                i += 1
            else:
                if i + 2 > len(src):
                    raise ValueError("truncated LZSS match")
                a, b = src[i:i + 2]
                i += 2
                pos = a | ((b & 0xf0) << 4)
                # Copy through the ring: LZSS matches can overlap their output.
                values = None
            length = 1 if values is not None else (b & 15) + 3
            for k in range(length):
                value = values[0] if values is not None else ring[(pos + k) & 4095]
                out.append(value)
                ring[write] = value
                write = (write + 1) & 4095
    if len(out) != size or zlib.adler32(out) != checksum:
        raise ValueError("kernel size or Adler-32 mismatch")
    return bytes(out)


def literal_kernel(header, kernel):
    """Valid LZSS using literal groups; larger, but avoids a compressor dependency."""
    encoded = b"".join(b"\xff" + kernel[i:i + 8] for i in range(0, len(kernel), 8))
    header = bytearray(header[:0x180])
    struct.pack_into(">III", header, 8, zlib.adler32(kernel), len(kernel), len(encoded))
    return bytes(header) + encoded


def patch_usb_kernel(build, image):
    if build != "4B1":
        raise ValueError("no USB notifier repair for build %s" % build)
    payload = unpack_8900(image)
    kernel = bytearray(decompress_kernel(payload))
    # Mach-O file offset of VA c04c24d8 in kernelcache.release.s5l8900xrb, 4B1.
    offset = 0x41b4d8
    old = bytes.fromhex("33ff2fe16c0095e5003090e50fe0a0e154f093e5")
    # ldr r0,[r5,#0x6c]; cmp r0,#0; ldrne r3,[r0]; mov lr,pc; ldrne pc,[r3,#0x54]
    new = bytes.fromhex("6c0095e5000050e3003090150fe0a0e154f09315")
    if kernel[offset:offset + len(old)] != old:
        raise ValueError("4B1 kernel does not have the expected USB notifier code")
    kernel[offset:offset + len(old)] = new
    repaired = literal_kernel(payload, kernel)
    header = bytearray(image[:0x800])
    # The emulator's bootrom stand-in accepts unsigned plaintext (format 4).
    header[7] = 4
    struct.pack_into("<I", header, 12, len(repaired))
    return bytes(header) + repaired


LOCKDOWND = "/usr/libexec/lockdownd"
# (file offset, original bytes, patched bytes) per build. In determine_activation_state (0xdcb8 in 1.1.5's lockdownd,
# __TEXT at file offset 0 for 0x1000), where the checks of the record join (0xe248): the state becomes Activated
# (the CFString the record path loads from 0xe64c) and the brick flag in r4 false, then on to the brick state check
# (0xe278). The path without a record (0xddc8) goes there too instead of straight to 0xe278.
LOCKDOWND_PATCHES = {
    "4B1": [
        (0xd248, "04009de5e8139fe5354502eb000050e3",
                 "fc239fe5" "04208de5" "0040a0e3" "070000ea"),  # ldr r2, =Activated; str r2, [sp, #4]; mov r4, #0; b
        (0xcdc8, "2a0100ea", "1e0100ea"),                      # b 0xe248
    ],
}


def patch_lockdownd(build, lockdownd):
    if build not in LOCKDOWND_PATCHES:
        raise ValueError("no activation repair for build %s" % build)
    for offset, old, new in LOCKDOWND_PATCHES[build]:
        old, new = bytes.fromhex(old), bytes.fromhex(new)
        if lockdownd[offset:offset + len(old)] != old:
            raise ValueError(f"lockdownd of {build} doesn't have the expected code at 0x{offset:x}")
        lockdownd = lockdownd[:offset] + new + lockdownd[offset + len(new):]
    return lockdownd
