"""
The devices Skeuo emulates, one profile per product (see profile.py). Everything that differs between devices is in
their profiles; the rest of the pipeline looks a device up here, by the product of its IPSW or its bundle.
"""
from . import ipod2_1
from .profile import CAPABILITIES, BootromSpec, NandLayout, Profile

PROFILES = {profile.product: profile for profile in (ipod2_1.PROFILE,)}


class DeviceError(Exception):
    pass


def get(product):
    if product not in PROFILES:
        raise DeviceError("Skeuo can't emulate %s; it emulates %s" % (product, ", ".join(sorted(PROFILES))))
    return PROFILES[product]


def profiles():
    return list(PROFILES.values())


def for_version(version, product=None):
    """The profile of product, or, without one, the only device that has firmware version in its catalog."""
    if product:
        return get(product)
    matches = [profile for profile in PROFILES.values() if version in profile.firmwares]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise DeviceError("no device Skeuo emulates has firmware %s; supported: %s" % (version, ", ".join(
            "%s %s" % (p.product, ", ".join(p.firmwares)) for p in PROFILES.values())))
    raise DeviceError("several devices have firmware %s; name the product (%s)"
                      % (version, ", ".join(p.product for p in matches)))
