#!/usr/bin/env python3
"""Install the same SSH setup as restore into an existing, powered-off 4B1 bundle."""
import argparse
import os
import sys
import tempfile

# This directory also has dis.py; do not let it shadow Python's stdlib dis.
sys.path[0] = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
from skeuo import nand, ssh1g
from skeuo.bundle import Bundle, BundleError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle')
    args = parser.parse_args()
    bundle = Bundle.open(args.bundle)
    if bundle.profile.product != 'iPod1,1' or bundle.info['firmware']['build'] != '4B1':
        parser.error('SSH installation is tested only for iPod1,1 1.1.5 (4B1)')
    ssh1g.check_available()
    bundle.lock()
    try:
        if bundle.suspended:
            raise BundleError('power off the bundle before installing SSH')
        bundle.fold()
        page = bundle.profile.nand.bytes_per_page
        parts = {n: (start, size) for n, start, size in nand.partitions(bundle.profile.nand, bundle.disk)}
        with tempfile.TemporaryDirectory(prefix='ssh-install.', dir=bundle.path) as work:
            images = {}
            for n in (1, 2):
                start, size = parts[n]
                images[n] = os.path.join(work, str(n) + '.img')
                with open(images[n], 'wb') as stream:
                    stream.truncate(size * page)
                nand.copy_regions(bundle.disk, images[n], start * page, 0, size * page)
            ssh1g.install(images[1], images[2], os.path.join(bundle.path, 'ssh'))
            for n, image in images.items():
                start, size = parts[n]
                nand.copy_regions(image, bundle.disk, 0, start * page, size * page)
    finally:
        bundle.unlock()
    print('Installed USB SSH; client identity:', os.path.join(bundle.path, 'ssh/id_ed25519'))


if __name__ == '__main__':
    main()
