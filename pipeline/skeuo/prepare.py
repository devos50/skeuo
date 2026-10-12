"""
Makes a freshly restored device boot to SpringBoard in the emulator, by changing the filesystems on its NAND:

- SpringBoard's launch daemon gets LK_ENABLE_MBX2D=0, so LayerKit draws in software.
- The device is activated by Skeuo's own activation authority (see activation.py): its certificates replace Apple's
  and the device gets an activation record for its UDID.
- With a Lockdown source instead, the Lockdown directory of a device that Apple activated (activation record, data
  ark, device keys, pair records) goes to /private/var/root/Library/Lockdown. That only works for the identity of
  that device.

The restored image can't be changed before the restore instead: asr on the restore ramdisk checks Apple's signature
of the root filesystem image. So this takes the disk out of the NAND, changes its partitions and writes a new NAND.
"""
import os
import plistlib
import shutil

from . import activation, hfs, nand

SPRINGBOARD_PLIST = "/System/Library/LaunchDaemons/com.apple.SpringBoard.plist"
LOCKDOWN_IN_ROOTFS = "/private/var/root/Library/Lockdown"
LOCKDOWN_IN_DATA = "/root/Library/Lockdown"  # the data partition is mounted at /private/var
SYSTEM_PARTITION = 1
DATA_PARTITION = 2
COPY_CHUNK = 1 << 22


def copy_regions(src, dst, src_offset, dst_offset, length):
    """Copies the data regions of src[src_offset:src_offset + length] to dst at dst_offset, keeping holes."""
    with open(src, "rb") as fs, open(dst, "r+b") as fd:
        end = min(os.fstat(fs.fileno()).st_size, src_offset + length)
        for start, count in nand.data_regions(fs, end):
            start, stop = max(start, src_offset), min(start + count, end)
            while start < stop:
                chunk = min(stop - start, COPY_CHUNK)
                fs.seek(start)
                data = fs.read(chunk)
                fd.seek(dst_offset + start - src_offset)
                fd.write(data)
                start += chunk


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


def prepare(nand_dir, workdir, device, product_type, lockdown=None, log=print):
    """device: the bundle's identity, with the UDID the restore reported."""
    """Rewrites the NAND at nand_dir with the changed filesystems."""
    hfs.check_supported()
    disk = os.path.join(workdir, "disk.img")
    log("reading the disk from the NAND")
    nand.extract(nand_dir, disk)
    partitions = {number: (start, size) for number, start, size in nand.mbr_partitions(disk)}
    images = {}
    for number in (SYSTEM_PARTITION, DATA_PARTITION):
        start, size = partitions[number]
        images[number] = os.path.join(workdir, "partition%d.img" % number)
        with open(images[number], "wb") as f:
            f.truncate(size * nand.BYTES_PER_PAGE)
        copy_regions(disk, images[number], start * nand.BYTES_PER_PAGE, 0, size * nand.BYTES_PER_PAGE)

    log("letting SpringBoard draw in software")
    plist = plistlib.loads(hfs.read_file(images[SYSTEM_PARTITION], SPRINGBOARD_PLIST))
    plist.setdefault("EnvironmentVariables", {})["LK_ENABLE_MBX2D"] = "0"
    system_files = {SPRINGBOARD_PLIST: plistlib.dumps(plist)}
    if not lockdown:
        system_files.update(activation.system_files())
    hfs.add_files(images[SYSTEM_PARTITION], system_files)

    if not lockdown:
        log("activating %s" % device["udid"])
        hfs.add_files(images[DATA_PARTITION],
                      activation.data_files(device["udid"], device["serial_number"], product_type))
    else:
        files = lockdown_files(lockdown)
        if not files:
            raise hfs.HFSError("no Lockdown files in %s" % lockdown)
        log("installing the Lockdown directory (%d files)" % len(files))
        hfs.add_files(images[DATA_PARTITION],
                      {os.path.join(LOCKDOWN_IN_DATA, rel): data for rel, data in files.items()})

    for number, image in images.items():
        start, size = partitions[number]
        copy_regions(image, disk, 0, start * nand.BYTES_PER_PAGE, size * nand.BYTES_PER_PAGE)
    log("writing the new NAND")
    new_nand = os.path.join(workdir, "nand")
    nand.build(disk, new_nand)
    os.rename(nand_dir, nand_dir + ".restored")
    os.rename(new_nand, nand_dir)
    shutil.rmtree(nand_dir + ".restored")
