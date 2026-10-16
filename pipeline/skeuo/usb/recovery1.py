"""iPhone OS 1.x recovery's message protocol (before control/bulk recovery).

The wire layout is also documented by libirecovery's legacyCMD implementation.
"""
import struct
import time

from .dfu import DeviceError

HEADER = struct.Struct('<HHII')


def request(link, kind, size, address=0, timeout=5):
    link.bulk_write(4, HEADER.pack(kind, 0x1234, size, address), timeout=timeout)
    reply = link.bulk_read(0x83, HEADER.size, timeout=timeout)
    if len(reply) != HEADER.size or HEADER.unpack(reply)[:2] != (0x808, 0x1234):
        raise DeviceError('legacy recovery rejected request: %s' % reply.hex())


def command(link, text, timeout=5):
    data = (text + '\n').encode() + b'\0'
    data = data.ljust((len(data) + 15) & ~15, b'\0')
    request(link, 0x803, len(data), timeout=timeout)
    link.bulk_write(2, data, timeout=timeout)
    # The acknowledgement precedes command execution; don't overwrite its buffer.
    time.sleep(0.1)


def upload(link, data):
    request(link, 0x805, len(data), 0x09000000)
    for offset in range(0, len(data), 512):
        link.bulk_write(5, data[offset:offset + 512], timeout=10)
    command(link, 'setenv filesize %d' % len(data))
