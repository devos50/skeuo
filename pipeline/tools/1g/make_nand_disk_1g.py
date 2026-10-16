#!/usr/bin/env python3 -I
"""make_nand_disk_1g.py <extracted ipsw> <out disk image> [data MB]: builds a test NAND disk image for the 1G
(nand-disk=) from a 1.1.x IPSW, as iBoot 1.1.5 reads it: an MBR in the first logical page whose LBAs count 2048-byte
pages (iBoot takes the block device's block size, the FTL's page), partition 1 the system volume (disk0s1, mounted at
/) and partition 2 a journaled HFS+ data volume (disk0s2, /private/var) holding the system volume's /private/var, as
a restore leaves it (the copy is owned by the user running this, uid 501 on a Mac, which is also mobile's).

The system volume comes from the root filesystem DMG, decrypted with the build's VFDecrypt key (vfdecrypt and dmg2img
from Homebrew). Keys are per build; only 1.1.5 (4B1) is known here. The disk image is sparse, so the NAND model
presents the space between and after the partitions as erased.

The device comes up activated: 1.1.x has no code signing, so lockdownd is patched (LOCKDOWND_PATCHES) to settle on
Activated whatever activation record it finds. A record of its own won't do: lockdownd's UDID is the SHA-1 of the
serial number and the Wi-Fi and Bluetooth addresses, and the record would also have to be signed by a key that
lockdownd trusts. The data volume also gets the data ark iTunes leaves behind (as the 2G's in skeuo/activation.py):
without a brick state in it lockdownd turns the brick state on at start, and for an iPod it never turns it off
again, so SpringBoard would stay on "Connect to iTunes".

The 4B1 kernelcache also gets the checked notifier null guard in skeuo/firmware1g.py, so USB can run with the
original device tree. The rebuilt kernel uses literal LZSS (larger but dependency-free) and an unsigned plaintext
8900 container, accepted by the emulator's bootrom stand-in.
"""
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from skeuo import activation, hfs  # noqa: E402
from skeuo.firmware1g import KERNEL_PATH, LOCKDOWND, LOCKDOWND_PATCHES, ROOTFS_KEYS as KEYS, patch_lockdownd, patch_usb_kernel  # noqa: E402

BLOCK = 2048
SYSTEM_LBA = 1

def apm_hfs_partition(img):
    """(offset, length) of the Apple_HFS(X) partition of an Apple Partition Map disk image."""
    with open(img, "rb") as f:
        for i in range(1, 64):
            f.seek(512 * i)
            e = f.read(512)
            if e[:2] != b"PM":
                break
            start, count = struct.unpack(">II", e[8:16])
            if e[48:80].split(b"\0")[0] in (b"Apple_HFS", b"Apple_HFSX"):
                return start * 512, count * 512
    raise SystemExit(f"{img}: no HFS partition")


def main():
    ipsw, out = sys.argv[1], sys.argv[2]
    data_mb = int(sys.argv[3]) if len(sys.argv) > 3 else 512
    restore = plistlib.load(open(os.path.join(ipsw, "Restore.plist"), "rb"))
    build = restore["ProductBuildVersion"]
    if build not in KEYS or build not in LOCKDOWND_PATCHES:
        raise SystemExit(f"no root filesystem key or lockdownd patch for {build}")
    rootfs = os.path.join(ipsw, restore["SystemRestoreImages"]["User"])

    with tempfile.TemporaryDirectory() as tmp:
        dec = os.path.join(tmp, "rootfs.dmg")
        raw = os.path.join(tmp, "rootfs.img")
        subprocess.run(["vfdecrypt", "-i", rootfs, "-k", KEYS[build], "-o", dec], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["dmg2img", dec, raw], check=True, stdout=subprocess.DEVNULL)
        sys_off, sys_len = apm_hfs_partition(raw)
        system = os.path.join(tmp, "system.hfs")
        with open(raw, "rb") as f, open(system, "wb") as o:
            f.seek(sys_off)
            left = sys_len
            while left:
                chunk = f.read(min(left, 1 << 20))
                o.write(chunk)
                left -= len(chunk)
        os.remove(raw)
        lockdownd = patch_lockdownd(build, hfs.read_file(system, LOCKDOWND))
        kernel = patch_usb_kernel(build, hfs.read_file(system, KERNEL_PATH))
        hfs.add_files(system, {LOCKDOWND: lockdownd, KERNEL_PATH: kernel}, {LOCKDOWND: 0o755})

        mnt = os.path.join(tmp, "system")
        subprocess.run(["hdiutil", "attach", "-quiet", "-readonly", "-nobrowse", "-mountpoint", mnt, dec], check=True)
        var = os.path.join(tmp, "var")
        try:
            shutil.copytree(os.path.join(mnt, "private/var"), var, symlinks=True)
        finally:
            subprocess.run(["hdiutil", "detach", "-quiet", mnt], check=True)
        ark = os.path.join(var, activation.DATA_ARK.lstrip("/"))
        os.makedirs(os.path.dirname(ark), exist_ok=True)
        with open(ark, "wb") as f:
            plistlib.dump(activation.INITIAL_DATA_ARK, f)
        data_dmg = os.path.join(tmp, "data.dmg")
        subprocess.run(["hdiutil", "create", "-quiet", "-size", f"{data_mb}m", "-fs", "Journaled HFS+",
                        "-volname", "Data", "-layout", "NONE", "-format", "UDRW", "-srcfolder", var, data_dmg],
                       check=True)
        subprocess.run(["hdiutil", "convert", "-quiet", data_dmg, "-format", "UDTO", "-o",
                        os.path.join(tmp, "data")], check=True)
        data_img = os.path.join(tmp, "data.cdr")
        data_len = os.path.getsize(data_img)

        sys_blocks = -(-sys_len // BLOCK)
        data_lba = SYSTEM_LBA + sys_blocks
        data_blocks = data_len // BLOCK

        mbr = bytearray(BLOCK)
        for i, (lba, n) in enumerate([(SYSTEM_LBA, sys_blocks), (data_lba, data_blocks)]):
            # boot flag, CHS (unused), type 0xaf (HFS+), CHS, first LBA, number of LBAs
            mbr[0x1be + i * 16:0x1be + (i + 1) * 16] = struct.pack("<B3sB3sII", 0, b"\xff" * 3, 0xaf,
                                                                    b"\xff" * 3, lba, n)
        mbr[510:512] = b"\x55\xaa"

        with open(out, "wb") as o:
            o.write(mbr)
            for src, off, length, lba in [(system, 0, sys_len, SYSTEM_LBA), (data_img, 0, data_len, data_lba)]:
                o.seek(lba * BLOCK)
                with open(src, "rb") as f:
                    f.seek(off)
                    left = length
                    while left:
                        chunk = f.read(min(left, 1 << 20))
                        # keep runs of zeros as holes
                        if chunk.count(0) == len(chunk):
                            o.seek(len(chunk), 1)
                        else:
                            o.write(chunk)
                        left -= len(chunk)
            o.truncate()
    print(f"system: LBA {SYSTEM_LBA}, {sys_blocks} blocks; data: LBA {data_lba}, {data_blocks} blocks")


if __name__ == "__main__":
    main()
