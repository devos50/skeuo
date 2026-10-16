import os
import struct
import tempfile
import unittest
import zlib

from skeuo.nor import factory_nor, nvram, set_nvram_variables, NVRAM_OFFSET, NVRAM_SIZE


class NVRAMTests(unittest.TestCase):
    def test_updates_other_bank_preserving_variables_and_partitions(self):
        with tempfile.TemporaryDirectory() as path:
            file = os.path.join(path, 'nor.bin')
            image = bytearray(factory_nor({}, {'wifiaddr': '02:03:04:05:06:07', 'auto-boot': 'false'}))
            # Give bank B a newer valid generation and a panic-partition marker.
            bank = bytearray(nvram({'wifiaddr': '02:aa:bb:cc:dd:ee', 'auto-boot': 'false'}))
            bank[0x900] = 0x42
            struct.pack_into('<I', bank, 0x14, 20)
            struct.pack_into('<I', bank, 0x10, zlib.adler32(bank[0x14:]))
            image[NVRAM_OFFSET + NVRAM_SIZE:] = bank
            with open(file, 'wb') as stream:
                stream.write(image)
            set_nvram_variables(file, {'boot-args': 'serial=1 debug=0x8 -v', 'auto-boot': 'true'})
            with open(file, 'rb') as stream:
                result = stream.read()
            updated = result[NVRAM_OFFSET:NVRAM_OFFSET + NVRAM_SIZE]
            self.assertEqual(struct.unpack_from('<I', updated, 0x14)[0], 21)
            self.assertEqual(struct.unpack_from('<I', updated, 0x10)[0], zlib.adler32(updated[0x14:]))
            self.assertIn(b'wifiaddr=02:aa:bb:cc:dd:ee\0', updated)
            self.assertIn(b'auto-boot=true\0', updated)
            self.assertIn(b'boot-args=serial=1 debug=0x8 -v\0', updated)
            self.assertEqual(updated[0x900], 0x42)
            self.assertEqual(result[NVRAM_OFFSET + NVRAM_SIZE:], bank)
            self.assertEqual(result[:NVRAM_OFFSET], image[:NVRAM_OFFSET])

    def test_invalid_or_overfull_bank_is_not_written(self):
        with tempfile.TemporaryDirectory() as path:
            file = os.path.join(path, 'nor.bin')
            image = factory_nor({}, {'unchanged': 'yes'})
            with open(file, 'wb') as stream:
                stream.write(image)
            with self.assertRaises(ValueError):
                set_nvram_variables(file, {'too-large': 'x' * NVRAM_SIZE})
            with open(file, 'rb') as stream:
                self.assertEqual(stream.read(), image)
            with open(file, 'wb') as stream:
                stream.write(b'\xff' * len(image))
            with self.assertRaises(ValueError):
                set_nvram_variables(file, {'boot-args': '-v'})
