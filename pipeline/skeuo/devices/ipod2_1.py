"""
The iPod touch 2G (iPod2,1, n72ap, S5L8720).

Firmware: Apple still serves the IPSWs of the firmware Skeuo supports, except iPhone OS 3.0: that was a paid upgrade
for the iPod touch, sold through the iTunes Store, and its IPSW was never on a public URL (Apple's catalog only names
a protected:// asset, and only for 3.1.3). A 3.0 device needs a local IPSW. Apple's version catalog only publishes a
FirmwareSHA1 for the firmware it currently offers (4.1 and 4.2.1); the SHA-1s below match the IPSWs as archived
elsewhere (ipsw.me) and a copy downloaded from Apple in 2008 (see download.py).

nand_epoch is the security epoch of the firmware's NAND driver. The NAND signature carries that epoch, and iBoot only
boots from a NAND formatted for its own epoch. default_boot_args: the emulator's default kernel arguments already
allow any code signature, so the device needs none of its own (see activation.py). lockdownd_certificate_check:
where the firmware's lockdownd checks the device certificate, which activation.py patches out (from 3.0 on).

NAND: 4 CEs of Samsung NAND, laid out by the VSVFL/FTL of the iPhone OS 2.x kernel.
"""
from .profile import BootromSpec, NandLayout, Profile

PROFILE = Profile(
    product="iPod2,1",
    name="iPod touch (2nd generation)",
    board="n72ap",
    soc="S5L8720",
    machine="iPod-Touch",
    firmwares={
        "2.1.1": {
            "build": "5F138",
            "url": "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-5494.20080909.8i9o0/"
                   "iPod2,1_2.1.1_5F138_Restore.ipsw",
            "size": 282083944,
            "sha1": "c3c700be49ad227d1152188e7c1e46b8958fd1e4",
            "nand_epoch": 1,
            "default_boot_args": True,
        },
        "2.2": {
            "build": "5G77a",
            "url": "https://secure-appldnld.apple.com/iPod/SBML/osx/061-5358.20081120.Gtghy/"
                   "iPod2,1_2.2_5G77a_Restore.ipsw",
            "size": 291123491,
            "sha1": "34a0a489605f34d6cc6c9954edcaaf9a050deedc",
            "nand_epoch": 2,
        },
        "3.0": {
            "build": "7A341",
            "url": None,  # never on a public URL, see above
            "nand_epoch": 3,
            # (file offset, the bl there): bl 0x88d0 at 0xdd8c
            "lockdownd_certificate_check": (0xcd8c, "cfeaffeb"),
        },
        "4.0": {
            "build": "8A293",
            "url": "https://secure-appldnld.apple.com/iPhone4/061-7435.20100621.tr49t/"
                   "iPod2,1_4.0_8A293_Restore.ipsw",
            "size": 330278777,
            "sha1": "c026c373bc535496a6f901de2ba37d4a487413bf",
            "nand_epoch": 4,
            "lockdownd_certificate_check": (0xe354, "c7eaffeb"),  # bl 0x9e78 at 0xf354
        },
    },
    bootrom=BootromSpec(
        version="iBoot-240.4",
        size=65536,
        sha256="55f4d8ea2791ba51dd89934168f38f0fb21ce8762ff614c1e742407c0d3ca054",
    ),
    image_format="img3",
    nand=NandLayout(
        kind="vsvfl",
        bytes_per_page=4096,
        bytes_per_spare=64,
        meta_size=12,
        pages_per_block=128,
        num_ce=4,
        blocks_per_ce=4096,
        planes_per_ce=2,
    ),
    restore="restored",
    capabilities=frozenset({"wifi", "audio", "accelerometer", "suspend", "usbmux"}),
    support="supported",
    wifi_nic="bcm4325",
)
