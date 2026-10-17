#!/usr/bin/env python3
"""Add an ad-hoc SHA-1 code signature to a 32-bit Mach-O executable.

iPhone OS 2.x kills pages that have no code signature, even when the boot
arguments let AMFI accept any signature. Its kernel only understands SHA-1
CodeDirectories (version 0x20001), not the SHA-256 ones current linkers emit.
The signature is a SuperBlob with a CodeDirectory and an empty requirements
set, appended to __LINKEDIT, as classic ldid wrote them. It is deterministic.
"""
import hashlib
import struct
import sys

MH_MAGIC = 0xfeedface
LC_SEGMENT = 0x1
LC_CODE_SIGNATURE = 0x1d
PAGE = 4096
SUPERBLOB = 0xfade0cc0
CODEDIRECTORY = 0xfade0c02
REQUIREMENTS = 0xfade0c01
CD_HEADER = 44  # version 0x20001 ends after spare2
SHA1 = 1


def sign(data, identifier):
    data = bytearray(data)
    magic, _, _, _, ncmds, sizeofcmds, _ = struct.unpack_from('<7I', data)
    if magic != MH_MAGIC:
        raise ValueError('not a 32-bit little-endian Mach-O')
    offset, linkedit, first_section = 28, None, len(data)
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, offset)
        if cmd == LC_CODE_SIGNATURE:
            raise ValueError('already signed')
        if cmd == LC_SEGMENT:
            name = data[offset + 8:offset + 24].rstrip(b'\0')
            if name == b'__LINKEDIT':
                linkedit = offset
            nsects, = struct.unpack_from('<I', data, offset + 48)
            for n in range(nsects):
                section_offset, = struct.unpack_from('<I', data, offset + 56 + n * 68 + 40)
                if section_offset:
                    first_section = min(first_section, section_offset)
        offset += size
    if linkedit is None:
        raise ValueError('no __LINKEDIT segment')
    if offset + 16 > first_section:
        raise ValueError('no room for LC_CODE_SIGNATURE; link with -headerpad')
    # segment_command: cmd, cmdsize, segname[16], vmaddr, vmsize, fileoff, filesize, ...
    vmsize, fileoff, filesize = struct.unpack_from('<III', data, linkedit + 28)
    if fileoff + filesize != len(data):
        raise ValueError('__LINKEDIT does not end the file')

    code_limit = (len(data) + 15) & ~15
    data += bytes(code_limit - len(data))
    requirements = struct.pack('>III', REQUIREMENTS, 12, 0)
    ident = identifier.encode() + b'\0'
    special = [hashlib.sha1(requirements).digest(), bytes(20)]  # slots -2 and -1 (Info.plist: none)
    code_slots = (code_limit + PAGE - 1) // PAGE
    hash_offset = CD_HEADER + len(ident) + 20 * len(special)
    cd_length = hash_offset + 20 * code_slots
    total = 12 + 8 * 2 + cd_length + len(requirements)

    # The load command and segment sizes are part of the first page's hash, so fix them first.
    struct.pack_into('<II', data, 16, ncmds + 1, sizeofcmds + 16)
    struct.pack_into('<IIII', data, offset, LC_CODE_SIGNATURE, 16, code_limit, total)
    filesize = code_limit + total - fileoff
    vmsize = max(vmsize, (filesize + PAGE - 1) & ~(PAGE - 1))
    struct.pack_into('<III', data, linkedit + 28, vmsize, fileoff, filesize)

    hashes = b''.join(hashlib.sha1(data[i:i + PAGE]).digest() for i in range(0, code_limit, PAGE))
    directory = struct.pack('>IIIIIIIIIBBBBI', CODEDIRECTORY, cd_length, 0x20001, 0, hash_offset, CD_HEADER,
                            len(special), code_slots, code_limit, 20, SHA1, 0, 12, 0)
    directory += ident + b''.join(reversed(special)) + hashes
    superblob = struct.pack('>III', SUPERBLOB, total, 2) + struct.pack('>IIII', 0, 28, 2, 28 + cd_length)
    data += superblob + directory + requirements
    assert len(data) == code_limit + total
    return bytes(data)


def main():
    for path in sys.argv[1:]:
        with open(path, 'rb') as f:
            signed = sign(f.read(), path.rsplit('/', 1)[-1])
        with open(path, 'wb') as f:
            f.write(signed)


if __name__ == '__main__':
    main()
