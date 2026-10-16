import os
import tempfile
import unittest
from types import SimpleNamespace

from skeuo.restored import NORServer


class NORDataTests(unittest.TestCase):
    def test_image2_decodes_images_but_preserves_llb_envelope(self):
        with tempfile.TemporaryDirectory() as path:
            llb, image = [os.path.join(path, name) for name in ('llb', 'iboot')]
            for file, data in ((llb, b'LLB envelope'), (image, b'IMG envelope')):
                with open(file, 'wb') as stream:
                    stream.write(data)
            replies = []
            client = SimpleNamespace(conn=SimpleNamespace(send=replies.append))

            def decode(data):
                self.assertEqual(data, b'IMG envelope')
                return b'Img2 payload'

            NORServer(llb, [image], log=lambda _: None, decode=decode)(client, {})
            self.assertEqual(replies[-1], {'LlbImageData': b'LLB envelope', 'NorImageData': [b'Img2 payload']})
            NORServer(llb, [image], log=lambda _: None)(client, {})
            self.assertEqual(replies[-1], {'LlbImageData': b'LLB envelope', 'NorImageData': [b'IMG envelope']})
