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

From iPhone OS 3.0 on, Security pins the anchor of the device certificate (Apple's iPhone CA, or the factory CA), so
Skeuo's device CA doesn't pass anymore. lockdownd doesn't check that the device certificate belongs to the device,
though: a record with a device certificate that Apple issued to any device, and Apple's iPhoneDeviceCA.pem left in
place, verifies (load_device_certificate). It has to be in its validity period on the device's clock (see
clock_date), while the expired Apple intermediates are accepted. On 4.0 an iPod without a verified record is put in
the brick state.

Without such a certificate, Skeuo patches lockdownd instead (patch_lockdownd): verify_activation_record treats the
device certificate as verified, while the account token signature check stays. The patched lockdownd no longer matches
its code signature, so the device runs with AMFI's enforcement off (BOOT_ARGS; the kernel honours these arguments
because the emulated chip is a non-production one, for which iBoot sets debug-enabled). That also lets unsigned and
modified binaries run.

A fresh device also gets a data ark with the state that iTunes leaves behind. Without a cached activation state
lockdownd enables the "brick state" when it starts, and for an iPod it never disables it again, so SpringBoard would
keep showing "Connect to iTunes".
"""
import base64
import datetime
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
LOCKDOWND = "/usr/libexec/lockdownd"
# the kernel arguments that turn off code signing enforcement (AMFI), for the patched lockdownd
BOOT_ARGS = "amfi=0xff cs_enforcement_disable=1"
# Per build, where verify_activation_record calls the device certificate check (SecTrustEvaluate under a policy that
# pins Apple's root): (file offset, the bl instruction there). It becomes "mov r0, #0", i.e. verified.
LOCKDOWND_DEVICE_CERTIFICATE_CHECKS = {
    "7A341": (0xcd8c, bytes.fromhex("cfeaffeb")),  # iPhone OS 3.0, bl 0x88d0 at 0xdd8c
    "8A293": (0xe354, bytes.fromhex("c7eaffeb")),  # iOS 4.0, bl 0x9e78 at 0xf354
}
MOV_R0_0 = bytes.fromhex("0000a0e3")
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


class ActivationError(Exception):
    pass


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


def activation_record(udid, serial_number, product_type, device_certificate=None):
    """device_certificate: a PEM certificate Apple issued to a device, instead of Skeuo's."""
    key = json.loads(_read("activation_key.json"))
    token = account_token(udid, serial_number, product_type)
    return plistlib.dumps({
        "AccountToken": token,
        "AccountTokenCertificate": _read("activation.pem"),
        "AccountTokenSignature": sign_sha1(token, key),
        "DeviceCertificate": device_certificate or _read("device.pem"),
        "LDActivationVersion": 2,
    })


def system_files(apple_device_certificate=False):
    """The certificates that replace Apple's on the system partition. With a device certificate from Apple, Apple's
    device CA stays."""
    files = {ACTIVATION_CERT: _read("activation.pem"), FACTORY_ACTIVATION_CERT: _read("activation.pem")}
    if not apple_device_certificate:
        files[DEVICE_CA_CERT] = _read("device_ca.pem")
    return files


def patch_lockdownd(build, lockdownd):
    """lockdownd with the device certificate check of verify_activation_record taken out, or None if there is no patch
    for the build (before 3.0 Skeuo's own device certificate verifies)."""
    if build not in LOCKDOWND_DEVICE_CERTIFICATE_CHECKS:
        return None
    offset, call = LOCKDOWND_DEVICE_CERTIFICATE_CHECKS[build]
    if lockdownd[offset:offset + len(call)] != call:
        raise ActivationError("lockdownd of %s doesn't have the expected device certificate check at 0x%x"
                              % (build, offset))
    return lockdownd[:offset] + MOV_R0_0 + lockdownd[offset + len(call):]


def data_files(udid, serial_number, product_type, device_certificate=None):
    """The activation record and the initial data ark, for the data partition of a freshly restored device."""
    return {RECORD: activation_record(udid, serial_number, product_type, device_certificate),
            DATA_ARK: plistlib.dumps(INITIAL_DATA_ARK)}


def _der(data, offset):
    """The (tag, value start, value end) of the DER element at offset."""
    tag, length = data[offset], data[offset + 1]
    offset += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[offset:offset + n], "big")
        offset += n
    return tag, offset, offset + length


def _der_time(tag, value):
    text = value.decode()
    if tag == 0x17:  # UTCTime, YYMMDDHHMMSSZ
        year = int(text[:2])
        text = ("19" if year >= 50 else "20") + text
    return datetime.datetime.strptime(text, "%Y%m%d%H%M%SZ").replace(tzinfo=datetime.timezone.utc)


def certificate_validity(pem):
    """(not before, not after) of a PEM certificate."""
    lines = [line for line in pem.decode().splitlines() if line and not line.startswith("-----")]
    der = base64.b64decode("".join(lines))
    _, pos, _ = _der(der, 0)        # into Certificate
    _, pos, _ = _der(der, pos)      # into tbsCertificate
    tag, _, end = _der(der, pos)
    if tag == 0xA0:                 # [0] version (absent in v1 certificates)
        pos = end
    for _ in range(3):              # serial number, signature algorithm, issuer
        _, _, pos = _der(der, pos)
    _, pos, _ = _der(der, pos)      # into validity
    t1, s1, e1 = _der(der, pos)
    t2, s2, e2 = _der(der, e1)
    return _der_time(t1, der[s1:e1]), _der_time(t2, der[s2:e2])


def load_device_certificate(path):
    """The device certificate in path: a PEM certificate, or an activation record (pod_record.plist) with one."""
    with open(path, "rb") as f:
        data = f.read()
    if not data.lstrip().startswith(b"-----BEGIN"):
        try:
            data = plistlib.loads(data)["DeviceCertificate"]
        except Exception:
            raise ActivationError("%s is neither a PEM certificate nor an activation record" % path)
    try:
        certificate_validity(data)
    except Exception:
        raise ActivationError("can't read the certificate in %s" % path)
    return data


def clock_date(validity, now=None):
    """None if the device can use the host's date with a device certificate valid in validity ((not before, not after)
    as ISO dates), otherwise the date (YYYY-MM-DD) to start the device's clock at: a month before the certificate
    expires, or the day after it became valid when it was valid for less than two months."""
    not_before, not_after = (datetime.datetime.fromisoformat(v) for v in validity)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    margin = datetime.timedelta(days=1)
    if not_before + margin <= now <= not_after - margin:
        return None
    date = max(not_after - datetime.timedelta(days=30), not_before + margin)
    return date.strftime("%Y-%m-%d")
