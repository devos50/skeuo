#!/usr/bin/env python3
"""Build the SSH assets from supplied source archives and the user's firmware.

For the iPod touch 1G, the device libraries come from the user's 1.1.5 IPSW; for the 2G, from a restored
iPhone OS 2.1.1 bundle (whose root filesystem is already decrypted). No downloads or system-wide installs.
See README.md for inputs and provenance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / 'pipeline'))
from skeuo import hfs, nand
from skeuo.bundle import Bundle
from skeuo.firmware1g import ROOTFS_KEYS
from skeuo.ipsw import IPSW
import codesign

LIBRARIES = ('libSystem.B.dylib', 'libgcc_s.1.dylib')
TARGETS = {'1g': ('ssh1g_assets', 'armv6-apple-ios1.0'), '2g': ('ssh2g_assets', 'armv6-apple-ios2.0')}


def ipsw_libraries(path, work, libdir, run, error):
    ipsw = IPSW(path, str(work / 'ipsw'))
    if ipsw.product != 'iPod1,1' or ipsw.build != '4B1':
        error('this build needs the iPod1,1 1.1.5 (4B1) IPSW')
    decrypted = work / 'system.dmg'
    run(['vfdecrypt', '-i', ipsw.system_image(), '-k', ROOTFS_KEYS['4B1'], '-o', decrypted])
    with hfs.mounted(str(decrypted), readonly=True) as root:
        for name in LIBRARIES:
            shutil.copyfile(Path(root) / 'usr/lib' / name, libdir / name)


def bundle_libraries(path, work, libdir, error):
    bundle = Bundle.open(path)
    if bundle.profile.product != 'iPod2,1' or bundle.info['firmware']['build'] != '5F138':
        error('this build needs a restored iPod2,1 2.1.1 (5F138) bundle')
    page = bundle.profile.nand.bytes_per_page
    start, size = {n: (s, z) for n, s, z in nand.partitions(bundle.profile.nand, bundle.disk)}[1]
    image = work / 'system.img'
    with open(image, 'wb') as stream:
        stream.truncate(size * page)
    # Read only what is folded into disk.img; the bundle is not changed.
    nand.copy_regions(bundle.disk, str(image), start * page, 0, size * page)
    with hfs.mounted(str(image), readonly=True) as root:
        for name in LIBRARIES:
            shutil.copyfile(Path(root) / 'usr/lib' / name, libdir / name)


def source_kit(output):
    """Ship complete free-software source/build inputs alongside the binaries."""
    with tarfile.open(output / 'sources.tar.xz', 'w:xz') as archive:
        for path in HERE.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.add(path, arcname=str(path.relative_to(REPO)))
        for path in (REPO / 'pipeline/skeuo').rglob('*.py'):
            archive.add(path, arcname=str(path.relative_to(REPO)))
        for path in (REPO / 'pipeline/skeuo/ssh1g_assets/licenses').glob('*'):
            archive.add(path, arcname=str(path.relative_to(REPO)))
    licenses = REPO / 'pipeline/skeuo/ssh1g_assets/licenses'
    if output.resolve() != licenses.parent.resolve():
        shutil.copytree(licenses, output / 'licenses', dirs_exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    firmware = parser.add_mutually_exclusive_group(required=True)
    firmware.add_argument('--ipsw', help='iPod1,1 1.1.5 IPSW: build the 1G assets')
    firmware.add_argument('--bundle', help='powered-off iPod2,1 2.1.1 bundle: build the 2G assets')
    parser.add_argument('--dropbear-source', required=True)
    parser.add_argument('--dash-source', required=True)
    parser.add_argument('--ld', required=True)
    parser.add_argument('--sdk', required=True)
    parser.add_argument('--work', required=True, help='new scratch directory')
    parser.add_argument('--output', help='default: the pipeline asset directory for the device')
    args = parser.parse_args()
    target = '1g' if args.ipsw else '2g'
    assets, triple = TARGETS[target]
    if not args.output:
        args.output = str(REPO / 'pipeline/skeuo' / assets)
    work = Path(args.work).resolve()
    work.mkdir(parents=True)  # refuse to reuse an earlier build
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, SKEUO_SSH_SDK=str(Path(args.sdk).resolve()),
               SKEUO_SSH_LD=str(Path(args.ld).resolve()), SKEUO_SSH_TARGET=target)
    log = open(work / 'build.log', 'w')

    def run(command, cwd=work, overrides=None):
        subprocess.run([str(x) for x in command], cwd=cwd, env=dict(env, **(overrides or {})),
                       check=True, stdout=log, stderr=subprocess.STDOUT)

    expected = {
        'dropbear-2026.94': 'e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81',
        'dash-0.5.13.5': '719d381d6d0ef968c6bab2dfab374470671816c03d765dec1b7509d858ae0fd1',
    }
    for source, name in [(args.dropbear_source, 'dropbear-2026.94'),
                         (args.dash_source, 'dash-0.5.13.5')]:
        if hashlib.sha256(Path(source).read_bytes()).hexdigest() != expected[name]:
            parser.error('source archive checksum mismatch: ' + name)
        with tarfile.open(source) as archive:
            # Source archives are local inputs; reject paths/links escaping work.
            archive.extractall(work, filter='data')
        if not (work / name / 'configure').is_file():
            parser.error('expected configured release source: ' + name)
    libdir = work / 'sysroot/usr/lib'
    libdir.mkdir(parents=True)
    if args.ipsw:
        ipsw_libraries(args.ipsw, work, libdir, run, parser.error)
    else:
        bundle_libraries(args.bundle, work, libdir, parser.error)
    for name in ('cc.py', 'crt.S', 'compat.c'):
        shutil.copyfile(HERE / name, work / name)
    (work / 'cc.py').chmod(0o755)
    cc = str(work / 'cc.py')
    for name in ('crt', 'compat'):
        run([cc, '-c', work / (name + ('.S' if name == 'crt' else '.c')), '-o', work / (name + '.o')])
    common = {'CC': cc, 'CFLAGS': '-Os -fno-stack-protector'}
    dropbear = work / 'dropbear-2026.94'
    shutil.copyfile(HERE / 'localoptions.h', dropbear / 'localoptions.h')
    run(['./configure', '--host=arm-apple-darwin', '--disable-zlib', '--disable-harden',
         '--disable-lastlog', '--disable-utmp', '--disable-utmpx', '--disable-wtmp',
         '--disable-wtmpx', '--disable-shadow', '--disable-pam'], cwd=dropbear,
        overrides=dict(common, ac_cv_func_login='no', ac_cv_func_logout='no', ac_cv_func_logwtmp='no'))
    cfg = dropbear / 'config.h'
    text = cfg.read_text()
    # configure's libutil search can re-enable login despite ac_cv_func_login.
    # Login accounting isn't available on iPhone OS 1; keep it disabled.
    for name in ('HAVE_LOGIN', 'HAVE_LOGOUT', 'HAVE_LOGWTMP'):
        text = text.replace('#define ' + name + ' 1', '/* #undef ' + name + ' */')
    cfg.write_text(text)
    run(['make', '-j6', 'PROGRAMS=dropbear'], cwd=dropbear)
    dash = work / 'dash-0.5.13.5'
    run(['./configure', '--host=arm-apple-darwin', '--without-libedit'], cwd=dash, overrides=common)
    cfg = dash / 'config.h'
    cfg.write_text(cfg.read_text().replace('#define HAVE_F_DUPFD_CLOEXEC 1', '#define HAVE_F_DUPFD_CLOEXEC 0'))
    run(['make', '-j6'], cwd=dash)
    for name, binary in [('dropbear', dropbear / 'dropbear'), ('dash', dash / 'src/dash')]:
        data = binary.read_bytes()
        if target == '2g':
            data = codesign.sign(data, name)
        (output / name).write_bytes(data)
    hashes = {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in ('dropbear', 'dash')}
    (output / 'manifest.json').write_text(json.dumps({'dropbear': '2026.94', 'dash': '0.5.13.5',
                                                   'target': triple, 'sha256': hashes}, indent=2) + '\n')
    source_kit(output)
    print('Built SSH assets in', output, '; log:', work / 'build.log')


if __name__ == '__main__':
    main()
