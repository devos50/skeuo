"""
Makes a freshly restored device boot to SpringBoard in the emulator, by changing the filesystems on its disk:

- SpringBoard's launch daemon gets LK_ENABLE_MBX2D=0, so LayerKit draws in software.
- The device is activated by Skeuo's own activation authority (see activation.py): its certificates replace Apple's
  and the device gets an activation record for its UDID. From 3.0 on, lockdownd is patched to accept Skeuo's device
  certificate, unless a device certificate from Apple is given.
- With a Lockdown source instead, the Lockdown directory of a device that Apple activated (activation record, data
  ark, device keys, pair records) goes to /private/var/root/Library/Lockdown. That only works for the identity of
  that device.
- On firmware ssh.py has tested, Dropbear, a POSIX shell and per-bundle keys are installed for SSH over USB.

The restored image can't be changed before the restore instead: asr on the restore ramdisk checks Apple's signature
of the root filesystem image. So this changes the partitions of the restored disk image in place.
"""
import os
import plistlib
import shutil
import subprocess
import tempfile

from . import activation, hfs, nand, ssh

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


def seed_legacy_data(source, data_image, build, workdir):
    """1.x removes /private/var from the system but doesn't seed its new data volume.

    Copy the original tree from the user's IPSW, retaining modes and symlinks,
    just as make_nand_disk_1g does for a hand-built image.
    """
    from .firmware1g import ROOTFS_KEYS
    if not source or not shutil.which("vfdecrypt"):
        raise hfs.HFSError("preparing 1.x needs its IPSW root image and vfdecrypt on PATH")
    with tempfile.TemporaryDirectory(prefix="initial-data.", dir=workdir) as work:
        decrypted = os.path.join(work, "rootfs.dmg")
        subprocess.run(["vfdecrypt", "-i", source, "-k", ROOTFS_KEYS[build], "-o", decrypted],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with hfs.mounted(decrypted, readonly=True) as system, hfs.mounted(data_image) as data:
            source_var = os.path.join(system, "private/var")
            # This is a never-booted data volume. Replace seed entries instead
            # of following existing symlinks or overwriting read-only files.
            for name in os.listdir(source_var):
                dest = os.path.join(data, name)
                if os.path.isdir(dest) and not os.path.islink(dest):
                    shutil.rmtree(dest)
                elif os.path.lexists(dest):
                    os.unlink(dest)
            shutil.copytree(source_var, data, symlinks=True, dirs_exist_ok=True)


def prepare(disk, workdir, device, profile, build, lockdown=None, device_certificate=None, log=print,
            initial_data=None, ssh_directory=None):
    """Changes the filesystems on the disk image of a restored device that never booted. device: the bundle's
    identity, with the UDID the restore reported. profile: the device's profile. build: the firmware build. device_certificate: a PEM device certificate from Apple for the
    activation record (see activation.py)."""
    hfs.check_supported()
    page = profile.nand.bytes_per_page
    partitions = {number: (start, size) for number, start, size in nand.partitions(profile.nand, disk)}
    images = {}
    for number in (SYSTEM_PARTITION, DATA_PARTITION):
        start, size = partitions[number]
        images[number] = os.path.join(workdir, "partition%d.img" % number)
        with open(images[number], "wb") as f:
            f.truncate(size * page)
        nand.copy_regions(disk, images[number], start * page, 0, size * page)

    if profile.image_format == "img2":
        log("seeding the 1.x data volume from the IPSW's /private/var")
        seed_legacy_data(initial_data, images[DATA_PARTITION], build, workdir)

    log("letting SpringBoard draw in software")
    plist = plistlib.loads(hfs.read_file(images[SYSTEM_PARTITION], SPRINGBOARD_PLIST))
    plist.setdefault("EnvironmentVariables", {})["LK_ENABLE_MBX2D"] = "0"
    system_files = {SPRINGBOARD_PLIST: plistlib.dumps(plist)}
    modes = {}
    legacy = profile.image_format == "img2"
    if legacy:
        from .firmware1g import KERNEL_PATH, patch_usb_kernel, patch_lockdownd
        log("repairing the 1.x USB notifier")
        system_files[KERNEL_PATH] = patch_usb_kernel(build, hfs.read_file(images[SYSTEM_PARTITION], KERNEL_PATH))
    if legacy and not lockdown:
        log("activating 1.x with its build-specific lockdownd repair")
        system_files[activation.LOCKDOWND] = patch_lockdownd(
            build, hfs.read_file(images[SYSTEM_PARTITION], activation.LOCKDOWND))
        modes[activation.LOCKDOWND] = LOCKDOWND_MODE
    elif not lockdown:
        system_files.update(activation.system_files(apple_device_certificate=device_certificate is not None))
        if not device_certificate:
            lockdownd = activation.patch_lockdownd(
                profile.firmware_by_build(build)[1], hfs.read_file(images[SYSTEM_PARTITION], activation.LOCKDOWND))
            if lockdownd:
                log("letting lockdownd accept Skeuo's device certificate")
                system_files[activation.LOCKDOWND] = lockdownd
                modes[activation.LOCKDOWND] = LOCKDOWND_MODE
    hfs.add_files(images[SYSTEM_PARTITION], system_files, modes)

    if legacy and not lockdown:
        hfs.add_files(images[DATA_PARTITION], {activation.DATA_ARK: plistlib.dumps(activation.INITIAL_DATA_ARK)})
    elif not lockdown:
        log("activating %s" % device["udid"])
        hfs.add_files(images[DATA_PARTITION],
                      activation.data_files(device["udid"], device["serial_number"], profile.product,
                                            device_certificate))
    else:
        files = lockdown_files(lockdown)
        if not files:
            raise hfs.HFSError("no Lockdown files in %s" % lockdown)
        log("installing the Lockdown directory (%d files)" % len(files))
        hfs.add_files(images[DATA_PARTITION],
                      {os.path.join(LOCKDOWN_IN_DATA, rel): data for rel, data in files.items()})

    if ssh_directory and ssh.supported(profile.product, build):
        log("installing Dropbear and a POSIX shell for USB SSH")
        ssh.install(profile.product, images[SYSTEM_PARTITION], images[DATA_PARTITION], ssh_directory)

    log("writing the changed partitions into the disk")
    for number, image in images.items():
        start, size = partitions[number]
        nand.copy_regions(image, disk, 0, start * page, size * page)
