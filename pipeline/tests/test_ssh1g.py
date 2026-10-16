import base64
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from skeuo import hfs, ssh1g


@unittest.skipUnless(shutil.which('ssh-keygen'), 'needs ssh-keygen')
class SSH1GKeysTests(unittest.TestCase):
    def test_keys_are_private_and_reused_and_host_conversion_matches_public_key(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work) / 'ssh'
            public = ssh1g.client_key(directory)
            private = (directory / 'id_ed25519').read_bytes()
            self.assertEqual(ssh1g.client_key(directory), public)
            self.assertEqual((directory / 'id_ed25519').read_bytes(), private)
            self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(directory / 'id_ed25519').st_mode & 0o777, 0o600)
            host = ssh1g.dropbear_host_key(directory)
            self.assertEqual(ssh1g.dropbear_host_key(directory), host)
            # Dropbear stores a string algorithm then a 64-byte seed+public pair.
            self.assertEqual(host[:19], struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 64))
            self.assertEqual(len(host), 83)
            outer = base64.b64decode((directory / 'host_ed25519.pub').read_bytes().split()[1])
            self.assertEqual(host[-32:], outer[-32:])
            self.assertNotEqual(host[-32:], base64.b64decode(public.split()[1])[-32:])

    def test_corrupt_host_key_is_rejected(self):
        with self.assertRaises(hfs.HFSError):
            ssh1g.openssh_to_dropbear(b'not a key')
        with tempfile.TemporaryDirectory() as work:
            ssh1g.client_key(work)
            data = (Path(work) / 'id_ed25519').read_bytes()
            raw = bytearray(base64.b64decode(b''.join(data.splitlines()[1:-1])))
            raw[19:23] = b'xxxx'  # cipher must be none
            broken = b'-----BEGIN OPENSSH PRIVATE KEY-----\n' + base64.b64encode(raw) + b'\n-----END OPENSSH PRIVATE KEY-----\n'
            with self.assertRaises(hfs.HFSError):
                ssh1g.openssh_to_dropbear(broken)
