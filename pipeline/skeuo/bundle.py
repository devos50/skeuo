"""
A device bundle is one virtual device: a directory with its storage and a description.

  <bundle>/device.json   what the device is, its identity and which firmware it was restored with, its name and
                         settings
  <bundle>/disk.img      the disk that the NAND holds, as a sparse raw disk image (see nand.py)
  <bundle>/overlay/      the NAND pages iOS wrote since the last cold boot, folded into disk.img when it powers off
  <bundle>/nor.bin       the NOR flash
  <bundle>/suspended.state   the saved machine of a suspended device (QEMU migration stream)
  <bundle>/thumbnail.png the gallery picture of the device: the last lit screen the app showed
  <bundle>/logs/         serial and QEMU logs of the last run
  <bundle>/.lock         locked while a run uses the bundle

The disk and NOR are the device's persistent storage: everything iOS writes ends up there.

Suspending saves the machine (RAM, CPU, every device and the NOR, but not the NAND) to suspended.state. The guest's
FTL keeps the physical layout of the NAND in RAM, so the state is only valid with disk.img and the overlay exactly
as they were when it was saved: the overlay is not folded while a saved state exists. device.json's "suspended"
records it ("saved", the emulator "fingerprint" it belongs to, and the device's "clock" at that moment), and only a
state recorded there counts; a state file without it is left over from a suspend that did not finish. Resuming
consumes the state: once it is loaded, the record and the file are removed, so a run that ends without suspending
leaves an overlay that is folded at the next start, as after a cold boot. Discarding the state (powering off)
makes folding safe again.

device.json's "name" is what the app shows (the directory name stays as it was created), and "settings" holds the
options picked at creation (see SETTINGS); bundles from before these existed get defaults when they are read.

Format 1 bundles stored the NAND itself, one file per written page in <bundle>/nand/; open() converts them.
"""
import datetime
import json
import os
import shutil

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

from . import activation, devices, nand

FORMAT_VERSION = 2

# Device settings and their defaults. "wifi" and "audio" change the emulator's command line, so a suspended device's
# state no longer loads after changing them; "usbmuxd" only decides whether a run serves the device to libimobiledevice.
SETTINGS = {
    "wifi": True,
    "audio": True,
    "usbmuxd": True,
}
MACHINE_SETTINGS = ("wifi", "audio")
# The capability of the device profile that each setting needs; a device without it has the setting off.
SETTING_CAPABILITIES = {"wifi": "wifi", "audio": "audio", "usbmuxd": "usbmux"}


def check_settings(profile, changes):
    """Refuses settings that don't exist, or that turn on something the device can't do."""
    unknown = set(changes) - set(SETTINGS)
    if unknown:
        raise BundleError("unknown settings: %s" % ", ".join(sorted(unknown)))
    missing = [key for key, value in changes.items()
               if value and SETTING_CAPABILITIES[key] not in profile.capabilities]
    if missing:
        raise BundleError("the %s has no %s" % (profile.name, ", ".join(sorted(missing))))


def default_settings(profile):
    return {key: value and SETTING_CAPABILITIES[key] in profile.capabilities for key, value in SETTINGS.items()}


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
        self.state = os.path.join(path, "suspended.state")
        self.thumbnail = os.path.join(path, "thumbnail.png")
        self.lock_file = None

    @property
    def ready(self):
        return self.info.get("state") == "ready"

    @property
    def name(self):
        return self.info.get("name") or default_name(self.info["firmware"]["version"])

    @property
    def profile(self):
        """The device's profile (devices/), by its product."""
        try:
            return devices.get(self.info.get("product"))
        except devices.DeviceError as e:
            raise BundleError("%s: %s" % (self.path, e))

    @property
    def settings(self):
        settings = dict(SETTINGS, **self.info.get("settings", {}))
        capabilities = self.profile.capabilities
        return {key: value and SETTING_CAPABILITIES[key] in capabilities for key, value in settings.items()}

    def rename(self, name):
        name = name.strip()
        if not name:
            raise BundleError("a device needs a name")
        self.info["name"] = name
        self.save()

    def update_settings(self, changes):
        """Changes settings; returns whether one of them changes the emulator's command line."""
        check_settings(self.profile, changes)
        settings = self.settings
        machine = any(settings[key] != bool(value) for key, value in changes.items() if key in MACHINE_SETTINGS)
        settings.update({key: bool(value) for key, value in changes.items()})
        self.info["settings"] = settings
        self.save()
        return machine

    def set_thumbnail(self, png):
        """Replaces the thumbnail; None removes it, so that the app draws its own."""
        if png is None:
            if os.path.exists(self.thumbnail):
                os.remove(self.thumbnail)
            return
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise BundleError("a thumbnail must be a PNG image")
        with open(self.thumbnail + ".part", "wb") as f:
            f.write(png)
        os.replace(self.thumbnail + ".part", self.thumbnail)

    def in_use(self):
        """Whether a process (this one included) holds the bundle's lock."""
        if self.lock_file is not None:
            return True
        if fcntl is None or not os.path.exists(os.path.join(self.path, ".lock")):
            return False
        with open(os.path.join(self.path, ".lock"), "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
        return False

    @property
    def nand_epoch(self):
        """The NAND driver epoch of the bundle's firmware, which the emulator formats the NAND for."""
        return self.firmware["nand_epoch"]

    @property
    def firmware(self):
        """The profile's entry for the bundle's firmware."""
        build = self.info["firmware"]["build"]
        found = self.profile.firmware_by_build(build)
        if not found:
            raise BundleError("%s has firmware %s, which Skeuo doesn't support" % (self.path, build))
        return found[1]

    @property
    def boot_args(self):
        """The kernel arguments to boot with: code signing enforcement off (see activation.py), except on firmware
        where the emulator's default arguments already allow any signature."""
        if self.firmware.get("default_boot_args"):
            return None
        return activation.BOOT_ARGS

    @property
    def clock_date(self):
        """The date to start the device's clock at (YYYY-MM-DD), or None for the host's date. A device activated with
        a device certificate from Apple needs a date in its validity period."""
        validity = self.info.get("device_certificate")
        if not validity:
            return None
        return activation.clock_date((validity["not_before"], validity["not_after"]))

    def resume_clock(self):
        """The date to resume a suspended device's clock at: where it was when it was saved, so that the clock and
        the guest's calendar agree, as long as that is still within the device certificate's validity."""
        clock = self.suspended and self.suspended.get("clock")
        validity = self.info.get("device_certificate")
        if not clock or not validity:
            return self.clock_date
        saved = datetime.datetime.fromisoformat(clock).replace(tzinfo=datetime.timezone.utc)
        not_after = datetime.datetime.fromisoformat(validity["not_after"])
        if saved > not_after - datetime.timedelta(days=1):
            return self.clock_date
        return clock

    def __str__(self):
        fw = self.info["firmware"]
        return "%s: %s %s (%s)" % (self.path, self.info["product"], fw["version"], fw["build"])

    def save(self):
        with open(os.path.join(self.path, "device.json.part"), "w") as f:
            json.dump(self.info, f, indent=2)
            f.write("\n")
        os.replace(os.path.join(self.path, "device.json.part"), os.path.join(self.path, "device.json"))

    def lock(self):
        """Takes the bundle for this process; two emulators on one bundle would corrupt it."""
        if fcntl is None:
            return
        f = open(os.path.join(self.path, ".lock"), "a")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            f.close()
            raise BundleError("%s is in use by another Skeuo process" % self.path)
        self.lock_file = f

    def unlock(self):
        if self.lock_file is not None:
            self.lock_file.close()
            self.lock_file = None

    @property
    def suspended(self):
        """The record of the saved state, or None."""
        return self.info.get("suspended")

    def fold(self, log=print):
        """Folds an overlay that a run left behind into the disk, unless a saved state needs it as it is."""
        if self.suspended:
            raise BundleError("%s is suspended; its overlay belongs to the saved state" % self.path)
        if os.path.exists(self.state):
            os.remove(self.state)  # left over from a suspend that did not finish
        if os.path.exists(self.overlay):
            log("writing the changed pages into the disk")
            nand.fold(self.profile.nand, self.overlay, self.disk)

    def record_suspended(self, fingerprint, clock):
        """Records the state that was just saved to self.state, together with the emulator it belongs to."""
        self.info["suspended"] = {
            "saved": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "clock": clock,
            "fingerprint": fingerprint,
        }
        self.save()

    def consume_suspended(self):
        """Forgets the saved state once the emulator has loaded it."""
        self.info.pop("suspended", None)
        self.save()
        if os.path.exists(self.state):
            os.remove(self.state)

    def discard_suspended(self, log=print):
        """Powers a suspended device off: drops its saved state and folds the overlay."""
        if self.suspended:
            log("discarding the state saved at %s" % self.suspended["saved"])
            self.consume_suspended()
        self.fold(log=log)

    def mark_ready(self):
        self.info["state"] = "ready"
        self.save()

    @classmethod
    def create(cls, path, ipsw, identity, name=None, settings=None):
        if os.path.exists(path) and os.listdir(path):
            raise BundleError("%s exists and is not empty" % path)
        check_settings(ipsw.profile, settings or {})
        os.makedirs(os.path.join(path, "logs"), exist_ok=True)
        bundle = cls(path, {
            "format": FORMAT_VERSION,
            "product": ipsw.product,
            "board": ipsw.board,
            "firmware": {"version": ipsw.version, "build": ipsw.build},
            "name": name or default_name(ipsw.version),
            "settings": dict(default_settings(ipsw.profile), **(settings or {})),
            "identity": identity,
            "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "state": "restoring",
        })
        bundle.save()
        return bundle

    @classmethod
    def open(cls, path):
        bundle = cls.read(path)
        if not bundle.ready:
            raise BundleError("%s was not restored completely; restore it again" % path)
        if bundle.info["format"] == 1:
            bundle.convert_from_pages()
        return bundle

    @classmethod
    def read(cls, path):
        """The bundle as it is, also when it wasn't restored completely; for listing."""
        try:
            with open(os.path.join(path, "device.json")) as f:
                info = json.load(f)
        except FileNotFoundError:
            raise BundleError("%s is not a device bundle (no device.json)" % path)
        except ValueError as e:
            raise BundleError("%s has a damaged device.json (%s)" % (path, e))
        if info.get("format") not in (1, FORMAT_VERSION):
            raise BundleError("%s has bundle format %s, this version reads %d"
                              % (path, info.get("format"), FORMAT_VERSION))
        return cls(path, info)

    def convert_from_pages(self, log=print):
        """Format 1 -> 2: replaces the one-file-per-page NAND by the disk it holds."""
        pages = os.path.join(self.path, "nand")
        if os.path.isdir(pages):
            log("converting %s to a disk image" % pages)
            nand.extract(self.profile.nand, pages, self.disk + ".part")
            os.replace(self.disk + ".part", self.disk)
            shutil.rmtree(pages)
        self.info["format"] = FORMAT_VERSION
        self.save()


def default_name(version):
    return "iPod touch (%s %s)" % ("iOS" if int(version.split(".")[0]) >= 4 else "iPhone OS", version)
