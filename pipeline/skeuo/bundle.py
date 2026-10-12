"""
A device bundle is one virtual device: a directory with its NAND, its NOR and a description.

  <bundle>/device.json   what the device is and which firmware it was restored with
  <bundle>/nand/         the NAND, one file per written page (see nand.py)
  <bundle>/nor.bin       the NOR flash
  <bundle>/logs/         serial and QEMU logs of the last run

The NAND and NOR are the device's persistent storage: everything iOS writes ends up there.
"""
import datetime
import json
import os

FORMAT_VERSION = 1


class BundleError(Exception):
    pass


class Bundle:
    def __init__(self, path, info):
        self.path = path
        self.info = info
        self.nand = os.path.join(path, "nand")
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

    def mark_ready(self):
        self.info["state"] = "ready"
        self.save()

    @classmethod
    def create(cls, path, ipsw):
        if os.path.exists(path) and os.listdir(path):
            raise BundleError("%s exists and is not empty" % path)
        os.makedirs(os.path.join(path, "logs"), exist_ok=True)
        bundle = cls(path, {
            "format": FORMAT_VERSION,
            "product": ipsw.product,
            "board": ipsw.board,
            "firmware": {"version": ipsw.version, "build": ipsw.build},
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
        if info.get("format") != FORMAT_VERSION:
            raise BundleError("%s has bundle format %s, this version reads %d"
                              % (path, info.get("format"), FORMAT_VERSION))
        bundle = cls(path, info)
        if not bundle.ready:
            raise BundleError("%s was not restored completely; restore it again" % path)
        return bundle
