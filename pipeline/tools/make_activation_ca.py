#!/usr/bin/env python3
"""
Generates Skeuo's activation authority (developer tool; needs the openssl command line):

  skeuo/activation/activation.pem       certificate whose key signs account tokens (replaces iPhoneActivation.pem)
  skeuo/activation/activation_key.json  that key's RSA numbers, for signing in plain Python
  skeuo/activation/device_ca.pem        CA that issues device certificates (replaces iPhoneDeviceCA.pem)
  skeuo/activation/device.pem           the device certificate every activation record carries

These keys only make sense to devices that Skeuo itself prepared: it puts the certificates in place of Apple's on the
restored filesystem. Run it once; the outputs are committed.

  python3 tools/make_activation_ca.py [--device-validity START END]
"""
import argparse
import json
import os
import re
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "skeuo", "activation")
KEY_BITS = 1024  # what the 2008-era certificates use
# lockdownd accepts a device certificate only when SecTrustEvaluate returns kSecTrustResultRecoverableTrustFailure
# (5), which is what Apple's certificates got. An expired certificate gets that result; a valid one does not.
DEVICE_VALIDITY = ("20070101000000Z", "20080101000000Z")
# the extensions of the device certificates Apple's activation server issued
DEVICE_EXTENSIONS = """[device]
authorityKeyIdentifier = keyid
subjectKeyIdentifier = hash
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = critical,serverAuth,clientAuth
1.2.840.113635.100.6.10.2 = ASN1:NULL
"""
CA_CONFIG = """[ca]
default_ca = skeuo
[skeuo]
database = %(dir)s/index.txt
new_certs_dir = %(dir)s
serial = %(dir)s/serial
default_md = sha1
policy = anything
email_in_dn = no
[anything]
commonName = supplied
"""


def openssl(*args, **kw):
    return subprocess.run(["openssl", *args], check=True, capture_output=True, text=True, **kw).stdout


def rsa_numbers(key):
    text = openssl("rsa", "-in", key, "-noout", "-text")

    def field(name):
        m = re.search(r"^%s:\s*\n((?:\s+[0-9a-f:]+\n)+)" % name, text, re.M)
        return int(re.sub(r"[\s:]", "", m.group(1)), 16)
    return {"n": "%x" % field("modulus"), "e": "%x" % 65537, "d": "%x" % field("privateExponent")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device-validity", nargs=2, metavar=("START", "END"), default=DEVICE_VALIDITY,
                        help="validity of the device certificate, as YYYYMMDDHHMMSSZ (default: %(default)s)")
    args = parser.parse_args()
    os.makedirs(OUT, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        def path(name):
            return os.path.join(tmp, name)

        for name in ("activation", "device_ca", "device"):
            openssl("genrsa", "-traditional", "-out", path(name + ".key"), str(KEY_BITS))

        openssl("req", "-new", "-x509", "-sha1", "-days", "36500", "-key", path("activation.key"),
                "-subj", "/C=NL/O=Skeuo/OU=Skeuo Activation/CN=Skeuo Activation",
                "-out", path("activation.pem"))
        openssl("req", "-new", "-x509", "-sha1", "-days", "36500", "-key", path("device_ca.key"),
                "-subj", "/C=NL/O=Skeuo/OU=Skeuo Activation/CN=Skeuo Device CA",
                "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-out", path("device_ca.pem"))
        openssl("req", "-new", "-key", path("device.key"), "-subj", "/C=NL/O=Skeuo/OU=Skeuo Device/CN=Skeuo Device",
                "-out", path("device.csr"))
        # openssl ca, unlike openssl x509, takes explicit start and end dates
        with open(path("ca.cnf"), "w") as f:
            f.write(CA_CONFIG % {"dir": tmp} + DEVICE_EXTENSIONS)
        open(path("index.txt"), "w").close()
        with open(path("serial"), "w") as f:
            f.write("01\n")
        openssl("ca", "-batch", "-config", path("ca.cnf"), "-extensions", "device", "-extfile", path("ca.cnf"),
                "-cert", path("device_ca.pem"), "-keyfile", path("device_ca.key"), "-in", path("device.csr"),
                "-startdate", args.device_validity[0], "-enddate", args.device_validity[1], "-notext",
                "-out", path("device.pem"))

        for name in ("activation.pem", "device_ca.pem", "device.pem"):
            with open(path(name)) as src, open(os.path.join(OUT, name), "w") as dst:
                dst.write(src.read())
        with open(os.path.join(OUT, "activation_key.json"), "w") as f:
            json.dump(rsa_numbers(path("activation.key")), f, indent=2)
            f.write("\n")
    print("wrote %s" % os.path.normpath(OUT))


if __name__ == "__main__":
    main()
