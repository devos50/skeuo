import os
import plistlib
import tempfile
import unittest

from skeuo.ipsw import IPSW, IPSWError


class IPSWMapTests(unittest.TestCase):
    def test_selects_product_board_after_generic_dfu_entry(self):
        with tempfile.TemporaryDirectory() as path:
            info = {'ProductType': 'iPod1,1', 'ProductVersion': '1.1.5', 'ProductBuildVersion': '4B1',
                    'DeviceMap': [{'BoardConfig': 's5l8900xall', 'DFUProductID': 0x1222},
                                  {'BoardConfig': 'n45ap', 'RecoveryModeProductID': 0x1280}]}
            with open(os.path.join(path, 'Restore.plist'), 'wb') as f:
                plistlib.dump(info, f)
            ipsw = IPSW(path, path)
            self.assertEqual(ipsw.board, 'n45ap')
            self.assertEqual(ipsw.device_map['RecoveryModeProductID'], 0x1280)
            info['DeviceMap'] = [{'BoardConfig': 'wrong'}]
            with open(os.path.join(path, 'Restore.plist'), 'wb') as f:
                plistlib.dump(info, f)
            with self.assertRaises(IPSWError):
                IPSW(path, path)
