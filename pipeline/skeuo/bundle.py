"""
A device bundle is one virtual device: a directory with its storage and a description.

  <bundle>/device.json   what the device is, its identity and which firmware it was restored with
  <bundle>/disk.img      the disk that the NAND holds, as a sparse raw disk image (see nand.py)
  <bundle>/overlay/      while the emulator runs: the NAND pages iOS wrote, folded into disk.img afterwards
  <bundle>/nor.bin       the NOR flash
  <bundle>/logs/         serial and QEMU logs of the last run

The disk and NOR are the device's persistent storage: everything iOS writes ends up there.

Format 1 bundles stored the NAND itself, one file per written page in <bundle>/nand/; open() converts them.
"""
import datetime
import json
import os
import shutil

from . import nand

FORMAT_VERSION = 2


class BundleError(Exception):
    pass


class Bundle:
    def __init__(self, path, info):
        self.path = path
        self.info = info
        self.disk = os.path.join(path, "disk.img")
        self.overlay = os.path.join(path, "overlay")
        self.nor = os.path.join(path, "nor.bin")
        self.logs = os.path.join(path, "logs")

    @property
    def ready(self):
        return self.info.get("state") == "ready"

    def __str__(self):
        fw = self.info["firmware"]
        return "%s: %s %s (%s)" % (self.path, self.info["product"], fw["version"], fw["build"])

    def save(self):
        with open(os.path.join(self.path, "device.json.part"), "w") as f:
            json.dump(self.info, f, indent=2)
            f.write("\n")
        os.replace(os.path.join(self.path, "device.json.part"), os.path.join(self.path, "device.json"))

    def fold(self, log=print):
        """Folds an overlay that a run left behind into the disk."""
        if os.path.exists(self.overlay):
            log("writing the changed pages into the disk")
            nand.fold(self.overlay, self.disk)

    def mark_ready(self):
        self.info["state"] = "ready"
        self.save()

    @classmethod
    def create(cls, path, ipsw, identity):
        if os.path.exists(path) and os.listdir(path):
            raise BundleError("%s exists and is not empty" % path)
        os.makedirs(os.path.join(path, "logs"), exist_ok=True)
        bundle = cls(path, {
            "format": FORMAT_VERSION,
            "product": ipsw.product,
            "board": ipsw.board,
            "firmware": {"version": ipsw.version, "build": ipsw.build},
            "identity": identity,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "state": "restoring",
        })
        bundle.save()
        return bundle

    @classmethod
    def open(cls, path):
        try:
            with open(os.path.join(path, "device.json")) as f:
                info = json.load(f)
        except FileNotFoundError:
            raise BundleError("%s is not a device bundle (no device.json)" % path)
        if info.get("format") not in (1, FORMAT_VERSION):
            raise BundleError("%s has bundle format %s, this version reads %d"
                              % (path, info.get("format"), FORMAT_VERSION))
        bundle = cls(path, info)
        if not bundle.ready:
            raise BundleError("%s was not restored completely; restore it again" % path)
        if info["format"] == 1:
            bundle.convert_from_pages()
        return bundle

    def convert_from_pages(self, log=print):
        """Format 1 -> 2: replaces the one-file-per-page NAND by the disk it holds."""
        pages = os.path.join(self.path, "nand")
        if os.path.isdir(pages):
            log("converting %s to a disk image" % pages)
            nand.extract(pages, self.disk + ".part")
            os.replace(self.disk + ".part", self.disk)
            shutil.rmtree(pages)
        self.info["format"] = FORMAT_VERSION
        self.save()
