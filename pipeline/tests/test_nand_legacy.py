import pathlib
import struct
import tempfile
import unittest

from skeuo import nand
from skeuo.devices.ipod1_1 import PROFILE
from skeuo.devices.ipod2_1 import PROFILE as TWO_G


class LegacyNANDTests(unittest.TestCase):
    def test_capacity_and_replacement(self):
        layout = PROFILE.nand
        self.assertEqual(nand.disk_pages(layout), 3872 * 1024)
        self.assertEqual(nand.virtual_page(layout, 7, 5 * 128 + 127), 3894 * 1024 + 1023)
        self.assertEqual(nand.disk_pages(TWO_G.nand), (1952 - 23) * 1024)

    def test_fold_bank_overlay_selects_newest_age(self):
        layout = PROFILE.nand
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            overlay = root / "overlay"
            overlay.mkdir()
            disk = root / "disk"
            disk.write_bytes(b"original".ljust(2048, b"\0"))
            # A data page, an older duplicate, and a context page that must be ignored.
            for bank, age, content, kind in ((0, 2, b"new", 0x40), (1, 1, b"old", 0x41),
                                              (2, 99, b"context", 0x43)):
                ppn = 204 * 128
                state = bytearray(ppn + 1)
                state[ppn] = 1
                (overlay / f"bank{bank}.state").write_bytes(state)
                with open(overlay / f"bank{bank}.spare", "wb") as f:
                    f.seek(ppn * 64)
                    meta = bytearray(64)
                    struct.pack_into("<II", meta, 0, 0, age)
                    meta[9] = kind
                    f.write(meta)
                with open(overlay / f"bank{bank}.data", "wb") as f:
                    f.seek(ppn * 2048)
                    f.write(content.ljust(2048, b"\0"))
            self.assertEqual(nand.fold(layout, str(overlay), str(disk)), 1)
            self.assertEqual(disk.read_bytes(), b"new".ljust(2048, b"\0"))
            self.assertFalse(overlay.exists())


if __name__ == "__main__":
    unittest.main()
