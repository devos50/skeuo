"""
Activates a device without Apple's activation server.

lockdownd (iPhone OS 2.1.1) trusts an activation record when
- its DeviceCertificate chains to /System/Library/Lockdown/iPhoneDeviceCA.pem, and
- its AccountTokenSignature is the SHA-1 PKCS#1 v1.5 signature of its AccountToken by the key of
  /System/Library/Lockdown/iPhoneActivation.pem,
and an iPod is Activated when the account token's UniqueDeviceID is the device's own (determine_activation_state).
The device certificate check (SecTrustEvaluate with the device CA as anchor) only passes with the result
kSecTrustResultRecoverableTrustFailure, which Apple's certificates got and an expired certificate gets too, so Skeuo's
device certificate expired in 2008.
Both certificates are plain files on the root filesystem, so Skeuo puts its own activation authority in their place
(see tools/make_activation_ca.py) and writes a record it signed itself to
/var/root/Library/Lockdown/activation_records/pod_record.plist. lockdownd verifies that record at boot.

A fresh device also gets a data ark with the state that iTunes leaves behind. Without a cached activation state
lockdownd enables the "brick state" when it starts, and for an iPod it never disables it again, so SpringBoard would
keep showing "Connect to iTunes".
"""
import hashlib
import json
import os
import plistlib
import uuid

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "activation")
ACTIVATION_CERT = "/System/Library/Lockdown/iPhoneActivation.pem"
DEVICE_CA_CERT = "/System/Library/Lockdown/iPhoneDeviceCA.pem"
# lockdownd falls back to the factory certificates when the production ones fail; 2.2's Security doesn't accept the
# expired device certificate, but its lockdownd ignores the device certificate on that path ("For Timberline")
FACTORY_ACTIVATION_CERT = "/System/Library/Lockdown/FactoryActivation.pem"
RECORD = "/root/Library/Lockdown/activation_records/pod_record.plist"  # on the data partition (/private/var)
DATA_ARK = "/root/Library/Lockdown/data_ark.plist"
# data ark keys are "<domain>-<key>"; the global domain is empty
INITIAL_DATA_ARK = {
    "-BrickState": False,
    "-ActivationStateAcknowledged": True,
    "-iTunesHasConnected": True,
    "com.apple.mobile.lockdown_cache-ActivationState": "Activated",
}

# DER DigestInfo prefix of a SHA-1 hash, for PKCS#1 v1.5 signatures
SHA1_DIGEST_INFO = bytes.fromhex("3021300906052b0e03021a05000414")


def _read(name):
    with open(os.path.join(HERE, name), "rb") as f:
        return f.read()


def sign_sha1(data, key):
    """RSASSA-PKCS1-v1_5 with SHA-1. key: {"n", "e", "d"} as hex strings."""
    n, d = int(key["n"], 16), int(key["d"], 16)
    k = (n.bit_length() + 7) // 8
    t = SHA1_DIGEST_INFO + hashlib.sha1(data).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def verify_sha1(data, signature, key):
    n, e = int(key["n"], 16), int(key["e"], 16)
    k = (n.bit_length() + 7) // 8
    em = pow(int.from_bytes(signature, "big"), e, n).to_bytes(k, "big")
    return em.endswith(SHA1_DIGEST_INFO + hashlib.sha1(data).digest())


def quote(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def account_token(udid, serial_number, product_type):
    """The account token, an old-style (OpenStep) plist like the ones Apple's server issued."""
    fields = [
        ("SerialNumber", quote(serial_number)),
        ("ProductType", quote(product_type)),
        ("UniqueDeviceID", quote(udid)),
        ("PostponementInfo", "{}"),
        ("ActivationRandomness", quote(str(uuid.uuid4()).upper())),
    ]
    return ("{\n" + "".join("\t%s = %s;\n" % (quote(k), v) for k, v in fields) + "}").encode()


def activation_record(udid, serial_number, product_type):
    key = json.loads(_read("activation_key.json"))
    token = account_token(udid, serial_number, product_type)
    return plistlib.dumps({
        "AccountToken": token,
        "AccountTokenCertificate": _read("activation.pem"),
        "AccountTokenSignature": sign_sha1(token, key),
        "DeviceCertificate": _read("device.pem"),
        "LDActivationVersion": 2,
    })


def system_files():
    """The certificates that replace Apple's on the system partition."""
    return {ACTIVATION_CERT: _read("activation.pem"), DEVICE_CA_CERT: _read("device_ca.pem"),
            FACTORY_ACTIVATION_CERT: _read("activation.pem")}


def data_files(udid, serial_number, product_type):
    """The activation record and the initial data ark, for the data partition of a freshly restored device."""
    return {RECORD: activation_record(udid, serial_number, product_type),
            DATA_ARK: plistlib.dumps(INITIAL_DATA_ARK)}
