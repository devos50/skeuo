"""
Changes files on the HFS+ partitions of a restored device, through macOS's own HFS+ driver (hdiutil).

macOS mounts the images with ownership ignored, so copied files end up owned by the current user, and launchd skips
daemons that are not owned by root. After unmounting, add_files() sets the owner and group in each file's HFS+ catalog
record to 0, without needing sudo. It only touches records whose parent is the destination directory, which it
identifies by its catalog node ID (the inode number).

Ported from add_files.py of generate_nand_it2g.
"""
import contextlib
import mmap
import os
import struct
import subprocess
import sys
import tempfile
import time

# HFSPlusCatalogFile: recordType, flags, reserved, fileID, 5 dates, then HFSPlusBSDInfo with ownerID and groupID.
# HFSPlusCatalogFolder has the same layout up to the BSD info.
FOLDER_RECORD = 1
FILE_RECORD = 2
OWNER_OFFSET = 0x20


class HFSError(Exception):
    pass


def check_supported():
    if sys.platform != "darwin":
        raise HFSError("changing the restored filesystems needs macOS (hdiutil) for now")


def attach(image, mountpoint, readonly=False):
    args = ["hdiutil", "attach", "-nobrowse", "-owners", "off", "-mountpoint", mountpoint]
    if readonly:
        args.append("-readonly")
    if not image.endswith(".dmg"):
        args += ["-imagekey", "diskimage-class=CRawDiskImage"]
    subprocess.run(args + [image], check=True, stdout=subprocess.DEVNULL)


def detach(mountpoint):
    # Spotlight or fseventsd can briefly keep a fresh mount busy.
    for _ in range(5):
        if subprocess.run(["hdiutil", "detach", mountpoint], stdout=subprocess.DEVNULL).returncode == 0:
            return
        time.sleep(1)
    subprocess.run(["hdiutil", "detach", mountpoint], check=True, stdout=subprocess.DEVNULL)


@contextlib.contextmanager
def mounted(image, readonly=False):
    mountpoint = tempfile.mkdtemp(prefix="skeuo-mount.")
    attach(image, mountpoint, readonly)
    try:
        yield mountpoint
    finally:
        detach(mountpoint)
        os.rmdir(mountpoint)


def chown_root(image, entries):
    """entries: list of (name, parent directory node ID, record type)."""
    with open(image, "r+b") as f, mmap.mmap(f.fileno(), 0) as data:
        # Mapped rather than read, so that large (sparse) partition images do not have to fit in memory.
        for name, parent, record_type in entries:
            uname = name.encode("utf-16-be")
            key = struct.pack(">HIH", 6 + len(uname), parent, len(name)) + uname
            matches = []
            pos = data.find(key)
            while pos != -1:
                rec = pos + len(key)
                if struct.unpack_from(">H", data, rec)[0] == record_type:
                    matches.append(rec)
                pos = data.find(key, pos + 1)
            # Unused B-tree node space can hold stale copies of a record, so patch every copy rather than guess
            # which one is live.
            if not matches:
                raise HFSError("no catalog record for %s in directory %d" % (name, parent))
            for rec in matches:
                struct.pack_into(">II", data, rec + OWNER_OFFSET, 0, 0)
        data.flush()


def add_files(image, files, modes=None):
    """Writes files into an HFS+ image, owned by root:wheel. files: {absolute path in the filesystem: bytes}. modes:
    {path: permissions} for files that aren't 0644. Missing parent directories are created and made root-owned as
    well."""
    entries = []
    with mounted(image) as mountpoint:
        for path, content in files.items():
            dst = os.path.join(mountpoint, path.lstrip("/"))
            missing = []
            parent = os.path.dirname(dst)
            while not os.path.isdir(parent):
                missing.append(parent)
                parent = os.path.dirname(parent)
            for directory in reversed(missing):
                os.mkdir(directory, 0o755)
                entries.append((os.path.basename(directory), os.stat(os.path.dirname(directory)).st_ino,
                                FOLDER_RECORD))
            if os.path.lexists(dst):
                os.remove(dst)
            with open(dst, "wb") as f:
                f.write(content)
            os.chmod(dst, (modes or {}).get(path, 0o644))
            entries.append((os.path.basename(dst), os.stat(os.path.dirname(dst)).st_ino, FILE_RECORD))
    chown_root(image, entries)


def read_file(image, path):
    with mounted(image, readonly=True) as mountpoint:
        with open(os.path.join(mountpoint, path.lstrip("/")), "rb") as f:
            return f.read()


def read_tree(image, path):
    """Returns {path relative to `path`: bytes} for the regular files below a directory of an image."""
    files = {}
    with mounted(image, readonly=True) as mountpoint:
        root = os.path.join(mountpoint, path.lstrip("/"))
        if not os.path.isdir(root):
            raise HFSError("%s has no %s" % (image, path))
        for dirpath, dirnames, filenames in os.walk(root):
            for name in filenames:
                if name == ".DS_Store":
                    continue
                full = os.path.join(dirpath, name)
                with open(full, "rb") as f:
                    files[os.path.relpath(full, root)] = f.read()
    return files
