"""
The identity of a virtual device: its serial numbers and MAC addresses. Every bundle gets its own, generated at
restore time, so that no two devices (and no real device) share one. iOS derives the device's UDID from these
values.

The model number and region describe the kind of device, not the device itself, so they are fixed.
"""
import random
import string

MODEL_NUMBER = "MA623"
REGION = "B/LL"
SERIAL_MODEL_CODE = "203"  # the last three characters of the serial number identify the model
SERIAL_CHARS = string.digits + string.ascii_uppercase


def random_mac(rng):
    # a locally administered unicast address, so it can't belong to real hardware
    octets = [rng.randrange(256) for _ in range(6)]
    octets[0] = (octets[0] & 0xFC) | 0x02
    return ":".join("%02X" % o for o in octets)


def random_serial(rng):
    """An 11-character serial in the format of the time: factory, year, week, unique part, model code."""
    factory = "1A"
    year = rng.choice("89")
    week = "%02d" % rng.randrange(1, 53)
    unique = "".join(rng.choice(SERIAL_CHARS) for _ in range(3))
    return factory + year + week + unique + SERIAL_MODEL_CODE


def generate(rng=None):
    rng = rng or random.SystemRandom()
    return {
        "serial_number": random_serial(rng),
        "battery_serial": "".join(rng.choice(string.digits) for _ in range(12)),
        "wifi_mac": random_mac(rng),
        "bluetooth_mac": random_mac(rng),
    }


def syscfg(identity):
    return {
        "Mod#": MODEL_NUMBER,
        "Regn": REGION,
        "SrNm": identity["serial_number"],
        "Batt": identity["battery_serial"],
    }


def nvram_env(identity):
    return {
        "debug-uarts": "1",
        "btaddr": identity["bluetooth_mac"],
        "wifiaddr": identity["wifi_mac"],
    }
