import mmap
import struct
import tempfile
import unittest

from skeuo import hfs


def record_key(name, parent):
    uname = name.encode("utf-16-be")
    return struct.pack(">HIH", 6 + len(uname), parent, len(name)) + uname


class ChownTests(unittest.TestCase):
    def image(self, catalog_block, total_blocks=1):
        """A 64 KiB image with 4 KiB blocks whose catalog is one extent at catalog_block, and a record for
        'mobile' in directory 2 both inside the catalog and outside it (as stale data elsewhere would be)."""
        data = bytearray(16 * 4096)
        data[1024:1026] = b"H+"
        struct.pack_into(">I", data, 1024 + 0x28, 4096)
        struct.pack_into(">I", data, 1024 + 0x110 + 12, total_blocks)
        struct.pack_into(">II", data, 1024 + 0x110 + 16, catalog_block, 1)
        key = record_key("mobile", 2)
        for offset in (catalog_block * 4096 + 100, 12 * 4096):
            data[offset:offset + len(key)] = key
            struct.pack_into(">H", data, offset + len(key), hfs.FOLDER_RECORD)
        f = tempfile.NamedTemporaryFile()
        f.write(data)
        f.flush()
        return f, catalog_block * 4096 + 100 + len(key), 12 * 4096 + len(key)

    def owner(self, path, record):
        with open(path, "rb") as f:
            return struct.unpack_from(">II", f.read(), record + hfs.OWNER_OFFSET)

    def test_only_the_catalog_is_searched(self):
        f, inside, outside = self.image(catalog_block=4)
        with f:
            with open(f.name, "rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                self.assertEqual(hfs.catalog_extents(data), [(4 * 4096, 5 * 4096)])
            hfs.chown(f.name, [("mobile", 2, hfs.FOLDER_RECORD, 501, 501)])
            self.assertEqual(self.owner(f.name, inside), (501, 501))
            self.assertEqual(self.owner(f.name, outside), (0, 0))

    def test_whole_image_when_the_catalog_has_overflow_extents(self):
        f, inside, outside = self.image(catalog_block=4, total_blocks=3)
        with f:
            hfs.chown(f.name, [("mobile", 2, hfs.FOLDER_RECORD, 501, 501)])
            self.assertEqual(self.owner(f.name, inside), (501, 501))
            self.assertEqual(self.owner(f.name, outside), (501, 501))

    def test_missing_record_is_an_error(self):
        f, _, _ = self.image(catalog_block=4)
        with f, self.assertRaises(hfs.HFSError):
            hfs.chown(f.name, [("Media", 2, hfs.FOLDER_RECORD, 501, 501)])
