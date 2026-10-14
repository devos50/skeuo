"""
Moves a directory to the user's trash, so that removing a device can be undone.
"""
import ctypes
import datetime
import os
import sys
import urllib.parse


class TrashError(Exception):
    pass


def _unique(directory, name):
    candidate, n = name, 2
    while os.path.lexists(os.path.join(directory, candidate)):
        candidate = "%s %d" % (name, n)
        n += 1
    return os.path.join(directory, candidate)


def _same_device(a, b):
    return os.stat(a).st_dev == os.stat(b).st_dev


def _macos(path):
    # the home volume's trash, or the trash of the volume the bundle is on
    trash = os.path.expanduser("~/.Trash")
    if not (os.path.isdir(trash) and _same_device(trash, path)):
        mount = path
        while not os.path.ismount(mount):
            mount = os.path.dirname(mount)
        trash = os.path.join(mount, ".Trashes", str(os.getuid()))
        if not os.path.isdir(trash):
            raise TrashError("there is no trash on the volume of %s" % path)
    os.rename(path, _unique(trash, os.path.basename(path)))


def _freedesktop(path):
    base = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Trash")
    files, info = os.path.join(base, "files"), os.path.join(base, "info")
    os.makedirs(files, exist_ok=True)
    os.makedirs(info, exist_ok=True)
    if not _same_device(files, path):
        raise TrashError("%s is not on the home volume, which has the trash" % path)
    dest = _unique(files, os.path.basename(path))
    with open(os.path.join(info, os.path.basename(dest) + ".trashinfo"), "w") as f:
        f.write("[Trash Info]\nPath=%s\nDeletionDate=%s\n" % (
            urllib.parse.quote(os.path.abspath(path)), datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")))
    os.rename(path, dest)


def _windows(path):
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=os.path.abspath(path) + "\0",
                         fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) or op.fAnyOperationsAborted:
        raise TrashError("could not move %s to the Recycle Bin" % path)


def trash(path):
    try:
        if sys.platform == "darwin":
            _macos(path)
        elif sys.platform == "win32":
            _windows(path)
        else:
            _freedesktop(path)
    except OSError as e:
        raise TrashError("could not move %s to the trash: %s" % (path, e))
