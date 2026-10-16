import struct
import unittest
import zlib

from skeuo.firmware1g import decompress_kernel, literal_kernel, patch_usb_kernel


class Firmware1GTests(unittest.TestCase):
    def test_literal_stream_roundtrip_and_checksum(self):
        header = b"complzss" + bytes(0x180 - 8)
        for size in (0, 1, 7, 8, 9, 8193):
            data = bytes(i % 251 for i in range(size))
            encoded = literal_kernel(header, data)
            self.assertEqual(decompress_kernel(encoded), data)
        damaged = bytearray(encoded)
        damaged[-1] ^= 1
        with self.assertRaises(ValueError):
            decompress_kernel(damaged)

    def test_overlapping_match(self):
        # A at dictionary 0xfee, followed by an overlapping 5-byte match.
        data = b"AAAAAA"
        header = bytearray(b"complzss" + bytes(0x180 - 8))
        stream = bytes.fromhex("0141eef2")
        struct.pack_into(">III", header, 8, zlib.adler32(data), len(data), len(stream))
        self.assertEqual(decompress_kernel(header + stream), data)
        with self.assertRaises(ValueError):
            decompress_kernel(header + stream[:-1])

    def test_repair_requires_expected_build_and_code(self):
        header = bytearray(0x800)
        header[:4] = b"8900"
        header[7] = 4
        payload = literal_kernel(b"complzss" + bytes(0x180 - 8), b"unexpected code")
        struct.pack_into("<I", header, 12, len(payload))
        for build in ("other", "4B1"):
            with self.assertRaises(ValueError):
                patch_usb_kernel(build, header + payload)


if __name__ == "__main__":
    unittest.main()
