"""SSH over USB for restored devices: source-built Dropbear and a POSIX shell.

Each product has its own build of the same sources (packaging/ssh1g): iPhone OS 1.x and 2.x+ have
incompatible stat/inode ABIs, and 2.x+ needs a code signature. BUILDS lists the firmware they were
tested on.

Only the client public key enters the guest. The client private key stays in the bundle's
ssh/ directory. A separate host key is generated during preparation and
installed on the data volume, so its identity survives an immediate power-off.
"""
import base64
import struct
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

from . import hfs

ASSETS = {'iPod1,1': Path(__file__).with_name('ssh1g_assets'),
          'iPod2,1': Path(__file__).with_name('ssh2g_assets')}
# 2G 3.0 (7A341) is not publicly downloadable and has not been tested.
BUILDS = {'iPod1,1': {'4B1'}, 'iPod2,1': {'5F138', '5G77a', '8A293'}}
DAEMON = '/System/Library/LaunchDaemons/org.skeuo.dropbear.plist'


def supported(product, build):
    return build in BUILDS.get(product, ())


def payloads(product):
    assets = ASSETS[product]
    try:
        manifest = json.loads((assets / 'manifest.json').read_text())
    except (OSError, ValueError) as exc:
        raise hfs.HFSError('SSH assets for %s are missing; see packaging/ssh1g/README.md' % product) from exc
    files = {}
    for name in ('dropbear', 'dash'):
        data = (assets / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != manifest['sha256'][name]:
            raise hfs.HFSError('SSH asset checksum mismatch: %s for %s' % (name, product))
        files[name] = data
    return files


def check_available(product):
    payloads(product)
    if not shutil.which('ssh-keygen'):
        raise hfs.HFSError('SSH preparation needs ssh-keygen on PATH')


def client_key(directory):
    """Create once, so installing again preserves the user's login identity."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    key = directory / 'id_ed25519'
    if not key.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                        '-C', 'Skeuo USB SSH', '-f', str(key)], check=True)
    os.chmod(key, 0o600)
    return subprocess.run(['ssh-keygen', '-y', '-P', '', '-f', str(key)],
                          capture_output=True, check=True).stdout.rstrip() + b'\n'


def dropbear_host_key(directory):
    """Convert a local, unencrypted OpenSSH Ed25519 key to Dropbear's format."""
    key = Path(directory) / 'host_ed25519'
    if not key.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '',
                        '-C', 'Skeuo host', '-f', str(key)], check=True)
    os.chmod(key, 0o600)
    return openssh_to_dropbear(key.read_bytes())


def openssh_to_dropbear(pem):
    def string(value):
        return struct.pack('>I', len(value)) + value

    try:
        raw = base64.b64decode(b''.join(pem.splitlines()[1:-1]), validate=True)
        if not raw.startswith(b'openssh-key-v1\0'):
            raise ValueError('not an OpenSSH key')
        position = 15

        def field():
            nonlocal position
            length, = struct.unpack_from('>I', raw, position)
            position += 4
            value = raw[position:position + length]
            position += length
            if len(value) != length:
                raise ValueError('truncated key')
            return value

        if field() != b'none' or field() != b'none' or field() != b'':
            raise ValueError('expected an unencrypted key')
        count, = struct.unpack_from('>I', raw, position)
        position += 4
        if count != 1:
            raise ValueError('expected one key')
        outer_public = field()
        raw = field()
        position = 8
        if raw[:4] != raw[4:8]:
            raise ValueError('private key check integers differ')
        if field() != b'ssh-ed25519':
            raise ValueError('expected Ed25519')
        public, secret = field(), field()
        if (len(public) != 32 or len(secret) != 64 or secret[32:] != public
                or outer_public != string(b'ssh-ed25519') + string(public)):
            raise ValueError('inconsistent Ed25519 key')
        return string(b'ssh-ed25519') + string(secret)
    except (ValueError, struct.error) as exc:
        raise hfs.HFSError('invalid local SSH host key: ' + str(exc)) from exc


def launch_daemon():
    return plistlib.dumps({
        'Label': 'org.skeuo.dropbear',
        'ProgramArguments': ['/usr/sbin/dropbear', '-i', '-E', '-s',
                             '-r', '/var/root/.ssh/dropbear_ed25519_host_key'],
        'Sockets': {'Listeners': {'SockServiceName': '22', 'SockType': 'stream',
                                  'SockFamily': 'IPv4', 'SockNodeName': '127.0.0.1'}},
        'inetdCompatibility': {'Wait': False},
        'StandardErrorPath': '/dev/console',
    })


def install(product, system_image, data_image, key_directory):
    files = payloads(product)
    public_key = client_key(key_directory)
    host_key = dropbear_host_key(key_directory)
    hfs.add_files(system_image, {'/usr/sbin/dropbear': files['dropbear'], '/bin/sh': files['dash'],
                                '/etc/shells': b'/bin/sh\n', DAEMON: launch_daemon()},
                  {'/usr/sbin/dropbear': 0o755, '/bin/sh': 0o755})
    hfs.add_files(data_image, {'/root/.ssh/authorized_keys': public_key,
                               '/root/.ssh/dropbear_ed25519_host_key': host_key},
                  {'/root/.ssh/authorized_keys': 0o600, '/root/.ssh/dropbear_ed25519_host_key': 0o600})
    with hfs.mounted(data_image) as root:
        home = os.path.join(root, 'root')
        os.chmod(home, 0o700)
        os.chmod(os.path.join(home, '.ssh'), 0o700)
        entries = [('root', os.stat(root).st_ino, hfs.FOLDER_RECORD),
                   ('.ssh', os.stat(home).st_ino, hfs.FOLDER_RECORD)]
    # /private/var was copied with ownership ignored during restore. Existing
    # directories also need root ownership for Dropbear's strict mode checks.
    hfs.chown_root(data_image, entries)
