"""
Makes a freshly restored device boot to SpringBoard in the emulator, by changing the filesystems on its disk:

- SpringBoard's launch daemon gets LK_ENABLE_MBX2D=0, so LayerKit draws in software.
- The device is activated by Skeuo's own activation authority (see activation.py): its certificates replace Apple's
  and the device gets an activation record for its UDID. From 3.0 on, lockdownd is patched to accept Skeuo's device
  certificate, unless a device certificate from Apple is given.
- With a Lockdown source instead, the Lockdown directory of a device that Apple activated (activation record, data
  ark, device keys, pair records) goes to /private/var/root/Library/Lockdown. That only works for the identity of
  that device.

The restored image can't be changed before the restore instead: asr on the restore ramdisk checks Apple's signature
of the root filesystem image. So this changes the partitions of the restored disk image in place.
"""
import os
import plistlib

from . import activation, hfs, nand

SPRINGBOARD_PLIST = "/System/Library/LaunchDaemons/com.apple.SpringBoard.plist"
LOCKDOWN_IN_ROOTFS = "/private/var/root/Library/Lockdown"
LOCKDOWN_IN_DATA = "/root/Library/Lockdown"  # the data partition is mounted at /private/var
SYSTEM_PARTITION = 1
DATA_PARTITION = 2
def lockdown_files(source):
    """The files of a Lockdown directory, from the directory itself or from a filesystem image that has it."""
    if os.path.isdir(source):
        files = {}
        for dirpath, dirnames, filenames in os.walk(source):
            for name in filenames:
                if name != ".DS_Store":
                    with open(os.path.join(dirpath, name), "rb") as f:
                        files[os.path.relpath(os.path.join(dirpath, name), source)] = f.read()
        return files
    return hfs.read_tree(source, LOCKDOWN_IN_ROOTFS)


LOCKDOWND_MODE = 0o755


def prepare(disk, workdir, device, product_type, build, lockdown=None, device_certificate=None, log=print):
    """Changes the filesystems on the disk image of a restored device that never booted. device: the bundle's
    identity, with the UDID the restore reported. build: the firmware build. device_certificate: a PEM device certificate from Apple for the
    activation record (see activation.py)."""
    hfs.check_supported()
    partitions = {number: (start, size) for number, start, size in nand.partitions(disk)}
    images = {}
    for number in (SYSTEM_PARTITION, DATA_PARTITION):
        start, size = partitions[number]
        images[number] = os.path.join(workdir, "partition%d.img" % number)
        with open(images[number], "wb") as f:
            f.truncate(size * nand.BYTES_PER_PAGE)
        nand.copy_regions(disk, images[number], start * nand.BYTES_PER_PAGE, 0, size * nand.BYTES_PER_PAGE)

    log("letting SpringBoard draw in software")
    plist = plistlib.loads(hfs.read_file(images[SYSTEM_PARTITION], SPRINGBOARD_PLIST))
    plist.setdefault("EnvironmentVariables", {})["LK_ENABLE_MBX2D"] = "0"
    system_files = {SPRINGBOARD_PLIST: plistlib.dumps(plist)}
    modes = {}
    if not lockdown:
        system_files.update(activation.system_files(apple_device_certificate=device_certificate is not None))
        if not device_certificate:
            lockdownd = activation.patch_lockdownd(
                build, hfs.read_file(images[SYSTEM_PARTITION], activation.LOCKDOWND))
            if lockdownd:
                log("letting lockdownd accept Skeuo's device certificate")
                system_files[activation.LOCKDOWND] = lockdownd
                modes[activation.LOCKDOWND] = LOCKDOWND_MODE
    hfs.add_files(images[SYSTEM_PARTITION], system_files, modes)

    if not lockdown:
        log("activating %s" % device["udid"])
        hfs.add_files(images[DATA_PARTITION],
                      activation.data_files(device["udid"], device["serial_number"], product_type,
                                            device_certificate))
    else:
        files = lockdown_files(lockdown)
        if not files:
            raise hfs.HFSError("no Lockdown files in %s" % lockdown)
        log("installing the Lockdown directory (%d files)" % len(files))
        hfs.add_files(images[DATA_PARTITION],
                      {os.path.join(LOCKDOWN_IN_DATA, rel): data for rel, data in files.items()})

    log("writing the changed partitions into the disk")
    for number, image in images.items():
        start, size = partitions[number]
        nand.copy_regions(image, disk, 0, start * nand.BYTES_PER_PAGE, size * nand.BYTES_PER_PAGE)
