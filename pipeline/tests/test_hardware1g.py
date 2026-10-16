"""Optional QEMU tests with synthetic data; no firmware or bootrom dump needed.

SKEUO_TEST_QEMU=/path/to/qemu-system-arm PYTHONPATH=pipeline python3 -m unittest discover -s pipeline/tests -v
"""
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(os.environ.get('SKEUO_TEST_QEMU'), 'set SKEUO_TEST_QEMU for hardware tests')
class Hardware1GTests(unittest.TestCase):
    def test_installed_llb_crypto_irqs_and_sst_programming(self):
        def aes(key, data):
            return subprocess.run(['openssl', 'enc', '-e', '-aes-128-cbc', '-K', key,
                                   '-iv', '0' * 32, '-nopad'], input=data, capture_output=True, check=True).stdout

        with tempfile.TemporaryDirectory(prefix='skeuo-qtest.') as work:
            path = Path(work)
            # Our own synthetic ARM bytes, wrapped like an installed LLB.
            code = bytes.fromhex('0e0000ea') + bytes(range(60))
            key836 = aes('0123456789abcdef0123456789abcdef',
                         bytes.fromhex('00e5a0e6526fae66c5c1c6d4f16d6180')).hex()
            nor = bytearray(b'\xff' * (1 << 20))
            nor[0x8000:0x8008] = b'89001.0\x01'
            struct.pack_into('<I', nor, 0x800c, len(code))
            nor[0x8800:0x8840] = aes(key836, code)
            (path / 'nor.bin').write_bytes(nor)
            (path / 'disk.img').write_bytes(b'')
            sock = path / 'qtest.sock'
            args = [os.environ['SKEUO_TEST_QEMU'], '-M',
                    f'iPod-Touch-1G,nor={path}/nor.bin,nand-disk={path}/disk.img,nand-overlay={path}/overlay',
                    '-cpu', 'max', '-S', '-display', 'none', '-serial', 'none', '-monitor', 'none',
                    '-audio', 'none', '-qtest', f'unix:{sock},server=on,wait=off']
            with open(path / 'qemu.log', 'w') as log:
                proc = subprocess.Popen(args, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 10
                    while not sock.exists():
                        if proc.poll() is not None or time.monotonic() >= deadline:
                            self.fail((path / 'qemu.log').read_text())
                        time.sleep(0.02)
                    with socket.socket(socket.AF_UNIX) as conn:
                        conn.settimeout(3)
                        conn.connect(str(sock))
                        with conn.makefile('rwb') as stream:
                            def request(command):
                                stream.write(command.encode() + b'\n')
                                stream.flush()
                                reply = stream.readline().decode().strip()
                                self.assertTrue(reply.startswith('OK'), (command, reply))
                                return reply.split()[1] if ' ' in reply else None

                            self.assertEqual(bytes.fromhex(request('read 0x22000000 64')[2:]), code)
                            request('write 0x09000000 16 0x345a2d6c5050d058780da431f0710e15')
                            for offset, value in [(8, 1), (0x14, 1), (0x18, 16), (0x20, 0x09001000),
                                                  (0x24, 16), (0x28, 0x09000000), (0x2c, 16),
                                                  (0x6c, 1), (0x10, 7), (4, 1)]:
                                request(f'writel {0x38c00000 + offset:#x} {value:#x}')
                            self.assertEqual(request('read 0x09001000 16'),
                                             '0x188458a6d15034dfe386f23b61d43774')
                            self.assertEqual(int(request('readl 0x38e01008'), 16) & 0x80, 0x80)
                            request('writel 0x38c0000c 7')
                            self.assertEqual(int(request('readl 0x38e01008'), 16) & 0x80, 0)
                            for address, value in [(0xaaaa, 0xaa), (0x5554, 0x55), (0xaaaa, 0x98)]:
                                request(f'writew {0x24000000 + address:#x} {value:#x}')
                            self.assertEqual(int(request('readw 0x24000020'), 16), ord('Q'))
                            request('writew 0x24000000 0xf0')
                            for address, value in [(0xaaaa, 0xaa), (0x5554, 0x55), (0xaaaa, 0xa0),
                                                   (0xa0000, 0x5a5a)]:
                                request(f'writew {0x24000000 + address:#x} {value:#x}')
                            self.assertEqual(int(request('readw 0x240a0000'), 16), 0x5a5a)
                finally:
                    proc.terminate()
                    proc.wait(timeout=5)
            self.assertEqual((path / 'nor.bin').read_bytes()[0xa0000:0xa0002], b'\x5a\x5a')
