import base64
import hashlib
import os
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

from skeuo import hfs, ssh


@unittest.skipUnless(shutil.which('ssh-keygen'), 'needs ssh-keygen')
class SSHKeysTests(unittest.TestCase):
    def test_keys_are_private_and_reused_and_host_conversion_matches_public_key(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work) / 'ssh'
            public = ssh.client_key(directory)
            private = (directory / 'id_ed25519').read_bytes()
            self.assertEqual(ssh.client_key(directory), public)
            self.assertEqual((directory / 'id_ed25519').read_bytes(), private)
            self.assertEqual(os.stat(directory).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(directory / 'id_ed25519').st_mode & 0o777, 0o600)
            host = ssh.dropbear_host_key(directory)
            self.assertEqual(ssh.dropbear_host_key(directory), host)
            # Dropbear stores a string algorithm then a 64-byte seed+public pair.
            self.assertEqual(host[:19], struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 64))
            self.assertEqual(len(host), 83)
            outer = base64.b64decode((directory / 'host_ed25519.pub').read_bytes().split()[1])
            self.assertEqual(host[-32:], outer[-32:])
            self.assertNotEqual(host[-32:], base64.b64decode(public.split()[1])[-32:])

    def test_corrupt_host_key_is_rejected(self):
        with self.assertRaises(hfs.HFSError):
            ssh.openssh_to_dropbear(b'not a key')
        with tempfile.TemporaryDirectory() as work:
            ssh.client_key(work)
            data = (Path(work) / 'id_ed25519').read_bytes()
            raw = bytearray(base64.b64decode(b''.join(data.splitlines()[1:-1])))
            raw[19:23] = b'xxxx'  # cipher must be none
            broken = b'-----BEGIN OPENSSH PRIVATE KEY-----\n' + base64.b64encode(raw) + b'\n-----END OPENSSH PRIVATE KEY-----\n'
            with self.assertRaises(hfs.HFSError):
                ssh.openssh_to_dropbear(broken)


class SSHAssetTests(unittest.TestCase):
    def test_each_product_has_assets_matching_its_manifest(self):
        for product in ssh.ASSETS:
            files = ssh.payloads(product)
            self.assertEqual(set(files), {'dropbear', 'dash'})
        self.assertNotEqual(ssh.payloads('iPod1,1'), ssh.payloads('iPod2,1'))

    def test_supported_firmware(self):
        self.assertTrue(ssh.supported('iPod1,1', '4B1'))
        self.assertTrue(ssh.supported('iPod2,1', '5F138'))
        self.assertFalse(ssh.supported('iPod2,1', '4B1'))
        self.assertFalse(ssh.supported('iPod3,1', '5F138'))

    def test_2g_payloads_carry_a_valid_sha1_code_signature(self):
        # iPhone OS 2.x kills unsigned pages and only understands SHA-1 CodeDirectories.
        for name, data in ssh.payloads('iPod2,1').items():
            ncmds, = struct.unpack_from('<I', data, 16)
            offset, signature = 28, None
            for _ in range(ncmds):
                cmd, size = struct.unpack_from('<II', data, offset)
                if cmd == 0x1d:  # LC_CODE_SIGNATURE
                    signature = struct.unpack_from('<II', data, offset + 8)
                offset += size
            self.assertIsNotNone(signature, name)
            dataoff, datasize = signature
            self.assertEqual(dataoff + datasize, len(data))
            magic, _, count = struct.unpack_from('>III', data, dataoff)
            self.assertEqual(magic, 0xfade0cc0)
            slots = dict(struct.unpack_from('>II', data, dataoff + 12 + 8 * i) for i in range(count))
            cd = dataoff + slots[0]
            (magic, _, version, _, hash_offset, _, _, code_slots, code_limit, hash_size, hash_type, _, page_bits,
             _) = struct.unpack_from('>IIIIIIIIIBBBBI', data, cd)
            self.assertEqual((magic, version, hash_size, hash_type), (0xfade0c02, 0x20001, 20, 1), name)
            self.assertEqual(code_limit, dataoff)
            page = 1 << page_bits
            self.assertEqual(code_slots, (code_limit + page - 1) // page)
            for slot in range(code_slots):
                expected = data[cd + hash_offset + 20 * slot:cd + hash_offset + 20 * (slot + 1)]
                chunk = data[slot * page:min((slot + 1) * page, code_limit)]
                self.assertEqual(hashlib.sha1(chunk).digest(), expected, '%s page %d' % (name, slot))
