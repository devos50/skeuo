"""
What Skeuo knows about one emulated device, so that the rest of the pipeline and the app can ask instead of assume.
"""
import hashlib
import os
from dataclasses import dataclass

# What a device can do. A device without one of these has no setting for it, and requests that need it are refused.
CAPABILITIES = ("wifi", "audio", "accelerometer", "suspend", "usbmux")
SUPPORT_LEVELS = ("supported", "experimental")


@dataclass(frozen=True)
class BootromSpec:
    """The chip's bootrom (SecureROM), which the emulator can boot through instead of starting the firmware itself.
    Apple's code, so never shipped: a user who has a dump can choose it."""
    version: str  # "iBoot-240.4"
    size: int
    sha256: str

    def matches(self, path):
        """Whether the file at path is this bootrom."""
        if not path or not os.path.isfile(path) or os.path.getsize(path) != self.size:
            return False
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == self.sha256


@dataclass(frozen=True)
class NandLayout:
    """The NAND's geometry and the FTL/VFL that lays it out (see nand.py)."""
    kind: str                # "vsvfl" or Whimory 2.1 "legacy"
    bytes_per_page: int
    bytes_per_spare: int
    meta_size: int           # the part of the spare area that the FTL/VFL sees
    pages_per_block: int
    num_ce: int
    blocks_per_ce: int
    planes_per_ce: int       # each plane of a CE is a bank of its own

    @property
    def pages_per_ce(self):
        return self.pages_per_block * self.blocks_per_ce

    @property
    def num_banks(self):
        return self.num_ce * self.planes_per_ce

    @property
    def blocks_per_bank(self):
        return self.blocks_per_ce // self.planes_per_ce

    @property
    def pages_per_sublock(self):
        return self.pages_per_block * self.num_banks


@dataclass(frozen=True)
class Profile:
    product: str             # "iPod2,1"
    name: str                # "iPod touch (2nd generation)"
    board: str               # "n72ap"
    soc: str                 # "S5L8720"
    machine: str             # the emulator's machine, for -M
    # version -> {"build", "url" (None: never on a public URL), "size", "sha1", "nand_epoch", "default_boot_args",
    # "lockdownd_certificate_check"}; see the profiles
    firmwares: dict
    bootrom: BootromSpec | None  # None when booting through a dump is not supported
    image_format: str        # "img3", or "img2" (8900 containers)
    nand: NandLayout
    restore: str             # how a bundle is restored: "restored" (the restore ramdisk in the emulator, over USB)
    capabilities: frozenset
    support: str             # "supported" or "experimental"
    wifi_nic: str = None     # the emulator's NIC model for the Wi-Fi chip, with the "wifi" capability

    def __post_init__(self):
        unknown = set(self.capabilities) - set(CAPABILITIES)
        if unknown:
            raise ValueError("%s: unknown capabilities %s" % (self.product, ", ".join(sorted(unknown))))
        if self.support not in SUPPORT_LEVELS:
            raise ValueError("%s: unknown support level %s" % (self.product, self.support))

    def firmware_by_build(self, build):
        """(version, firmware) of a build, or None."""
        for version, fw in self.firmwares.items():
            if fw["build"] == build:
                return version, fw
        return None

    def describe(self):
        """The profile as device_types sends it to the app."""
        return {
            "product": self.product,
            "name": self.name,
            "board": self.board,
            "soc": self.soc,
            "capabilities": sorted(self.capabilities),
            "support": self.support,
            "bootrom": {"soc": self.soc, "version": self.bootrom.version, "size": self.bootrom.size,
                        "sha256": self.bootrom.sha256} if self.bootrom else None,
        }
