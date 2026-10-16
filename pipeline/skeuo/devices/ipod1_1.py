"""iPod touch 1G, n45ap. USB bring-up on user-supplied 1.1.5 firmware.

Restore support is deliberately unavailable until the 1.x restore path is proven.
The emulator currently boots through its bootrom stand-in only.
"""
from .profile import NandLayout, Profile

PROFILE = Profile(
    product="iPod1,1",
    name="iPod touch (1st generation)",
    board="n45ap",
    soc="S5L8900",
    machine="iPod-Touch-1G",
    firmwares={"1.1.5": {
        "build": "4B1",
        "url": "https://secure-appldnld.apple.com/iPod/SBML/osx/bundles/061-4841.20080714.bgy8O/"
               "iPod1,1_1.1.5_4B1_Restore.ipsw",
        "size": 173519637,
        "sha1": "1b818911316e4248ee01d3ec67f9d39afc3db240",
        "nand_epoch": None, "default_boot_args": True,
    }},
    bootrom=None,
    image_format="img2",
    nand=NandLayout(kind="legacy", bytes_per_page=2048, bytes_per_spare=64,
                    meta_size=12, pages_per_block=128, num_ce=8,
                    blocks_per_ce=4096, planes_per_ce=1),
    restore="unavailable",
    capabilities=frozenset({"audio", "accelerometer", "usbmux"}),
    support="experimental",
)
