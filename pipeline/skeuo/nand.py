"""
The NAND of the iPod Touch 2G: 4 CEs of Samsung NAND, laid out by the VSVFL/FTL of the iPhone OS 2.x kernel.

A bundle stores the disk that the FTL presents, not the NAND itself: disk.img, a sparse raw disk image with logical
page n at offset n * BYTES_PER_PAGE (the MBR at page 0, partition 1 = system, partition 2 = data). macOS mounts its
partitions with `hdiutil attach -imagekey diskimage-class=CRawDiskImage`.

The emulator (nand-disk/nand-overlay of the iPod-Touch machine, hw/arm/ipod_touch_nand.c) presents disk.img as a
freshly formatted NAND with every data block in place, and keeps the pages that iOS programs or erases in an overlay
directory, per CE:

  cs<ce>.data    sparse, page p at offset p * BYTES_PER_PAGE
  cs<ce>.spare   sparse, the spare area of page p at offset p * BYTES_PER_SPARE
  cs<ce>.state   one byte per page: 0 = the page of the formatted NAND, 1 = programmed (in .data/.spare), 2 = erased

fold() writes the newest copy of every logical page in the overlay into disk.img and deletes the overlay. The FTL's
own state is not kept: the next boot starts from a freshly formatted NAND again. The overlay together with the
unchanged disk.img is a consistent NAND as well, so an overlay left over from a crash can be folded later.

Older bundles stored the NAND as one file per written page, <nand>/cs<ce>/<page>.page (page data followed by the
spare area); extract() converts those.
"""
import os
import shutil
import struct

BYTES_PER_PAGE = 4096
BYTES_PER_SPARE = 64
META_SIZE = 12  # the part of the spare area that the FTL/VFL sees
PAGES_PER_BLOCK = 128
NUM_CE = 4
BLOCKS_PER_CE = 4096
PAGES_PER_CE = PAGES_PER_BLOCK * BLOCKS_PER_CE
NUM_BANKS = 8  # the two planes of each CE are exposed as two banks
BLOCKS_PER_BANK = BLOCKS_PER_CE // 2
PAGES_PER_SUBLOCK = PAGES_PER_BLOCK * NUM_BANKS

# VSVFL gives 976 out of every 1024 blocks to the user super blocks; the FTL keeps 23 of those for itself
VFL_NUM_OF_SUBLKS = (0x3d0 * BLOCKS_PER_BANK) // 1024
FTL_DATA_VBN_START = 3 + 20
FTL_NUM_OF_LBNS = VFL_NUM_OF_SUBLKS - FTL_DATA_VBN_START
DISK_NUM_OF_LBAS = FTL_NUM_OF_LBNS * PAGES_PER_SUBLOCK
FTL_SPARE_TYPES_DATA = (0x40, 0x41)

OVERLAY_PROGRAMMED = 1

MBR_TYPE_GPT_PROTECTIVE = 0xEE
MBR_PARTITIONS = 0x1BE
COPY_CHUNK = 1 << 22


class NANDError(Exception):
    pass


def virtual_page(ce, ppn):
    """The virtual page that VSVFL keeps at physical page ppn of a CE (for the data blocks, which are never
    remapped)."""
    chip_block, page_in_block = divmod(ppn, PAGES_PER_BLOCK)
    vbn, plane = divmod(chip_block, 2)
    return vbn * PAGES_PER_SUBLOCK + page_in_block * NUM_BANKS + ce + NUM_CE * plane


def data_regions(f, size):
    """Yields (offset, length) of the data regions of a sparse file. Without SEEK_DATA (Windows), all of it."""
    if not hasattr(os, "SEEK_DATA"):
        yield 0, size
        return
    pos = 0
    while pos < size:
        try:
            start = os.lseek(f.fileno(), pos, os.SEEK_DATA)
        except OSError:
            return
        end = os.lseek(f.fileno(), start, os.SEEK_HOLE)
        yield start, end - start
        pos = end


def copy_regions(src, dst, src_offset, dst_offset, length):
    """Copies the data regions of src[src_offset:src_offset + length] to dst at dst_offset, keeping holes."""
    with open(src, "rb") as fs, open(dst, "r+b") as fd:
        end = min(os.fstat(fs.fileno()).st_size, src_offset + length)
        for start, count in data_regions(fs, end):
            start, stop = max(start, src_offset), min(start + count, end)
            while start < stop:
                chunk = min(stop - start, COPY_CHUNK)
                fs.seek(start)
                data = fs.read(chunk)
                fd.seek(dst_offset + start - src_offset)
                fd.write(data)
                start += chunk


def newest_pages(pages):
    """pages: iterable of (ce, physical page, meta, data location). Returns {logical page: data location} for the
    newest copy of every logical page. The FTL stores the logical page of each data page in its spare area with the
    write age of its block; of several copies the newest is the one in the youngest block, and within a block the
    one written last."""
    newest = {}
    for ce, ppn, meta, location in pages:
        if len(meta) < META_SIZE or meta[9] not in FTL_SPARE_TYPES_DATA:
            continue
        lpn, age = struct.unpack_from("<II", meta)
        if lpn >= DISK_NUM_OF_LBAS:
            continue
        order = (age, virtual_page(ce, ppn))
        if lpn not in newest or order > newest[lpn][0]:
            newest[lpn] = (order, location)
    return {lpn: location for lpn, (order, location) in newest.items()}


def page_files(nand):
    """The pages of a NAND in the one-file-per-page format, with (path, offset) of their data."""
    for ce in range(NUM_CE):
        directory = os.path.join(nand, "cs%d" % ce)
        if not os.path.isdir(directory):
            continue
        for entry in os.scandir(directory):
            if not entry.name.endswith(".page"):
                continue
            with open(entry.path, "rb") as f:
                f.seek(BYTES_PER_PAGE)
                meta = f.read(META_SIZE)
            yield ce, int(entry.name[:-5]), meta, (entry.path, 0)


def overlay_pages(overlay):
    """The programmed pages of an overlay, with (path, offset) of their data."""
    for ce in range(NUM_CE):
        base = os.path.join(overlay, "cs%d." % ce)
        try:
            with open(base + "state", "rb") as f:
                state = f.read()
            with open(base + "spare", "rb") as f:
                spare = f.read()
        except FileNotFoundError:
            continue
        ppn = state.find(OVERLAY_PROGRAMMED)
        while ppn != -1:
            yield ce, ppn, spare[ppn * BYTES_PER_SPARE:ppn * BYTES_PER_SPARE + META_SIZE], \
                (base + "data", ppn * BYTES_PER_PAGE)
            ppn = state.find(OVERLAY_PROGRAMMED, ppn + 1)


def write_pages(pages, disk):
    """Writes {logical page: (path, offset)} into the disk image. Pages of zeroes that would land on zeroes (or a
    hole) are skipped, so that the image stays sparse."""
    zero_page = bytes(BYTES_PER_PAGE)
    files = {}
    try:
        with open(disk, "r+b" if os.path.exists(disk) else "w+b") as out:
            size = os.fstat(out.fileno()).st_size
            for lpn in sorted(pages):
                path, offset = pages[lpn]
                if path not in files:
                    if len(files) >= 16:  # an overlay has 4 data files, a page-file NAND one file per page
                        for f in files.values():
                            f.close()
                        files.clear()
                    files[path] = open(path, "rb")
                src = files[path]
                src.seek(offset)
                data = src.read(BYTES_PER_PAGE).ljust(BYTES_PER_PAGE, b"\0")
                out.seek(lpn * BYTES_PER_PAGE)
                if data == zero_page and (lpn * BYTES_PER_PAGE >= size or out.read(BYTES_PER_PAGE) == zero_page):
                    continue
                out.seek(lpn * BYTES_PER_PAGE)
                out.write(data)
            out.flush()
            os.fsync(out.fileno())
    finally:
        for f in files.values():
            f.close()


def extract(nand, disk):
    """Writes the disk that the FTL of a NAND in the one-file-per-page format presents to a new sparse disk
    image."""
    pages = newest_pages(page_files(nand))
    if not pages:
        raise NANDError("no data pages in %s" % nand)
    with open(disk, "wb") as f:
        f.truncate((max(pages) + 1) * BYTES_PER_PAGE)
    write_pages(pages, disk)
    return len(pages)


def fold(overlay, disk):
    """Writes the newest copy of every logical page in the overlay into the disk image and deletes the overlay.
    Folding again after an interruption gives the same result."""
    pages = newest_pages(overlay_pages(overlay))
    write_pages(pages, disk)
    shutil.rmtree(overlay)
    return len(pages)


def partitions(disk):
    """Returns [(number, first page, pages)] of the partitions on the disk: those of the MBR at logical page 0, or, if
    that is a protective MBR (iOS 4 on), those of the GPT behind it. Pages are the disk's 4 KiB logical blocks."""
    with open(disk, "rb") as f:
        mbr = f.read(512)
        if mbr[510:512] != b"\x55\xaa":
            raise NANDError("no MBR on %s" % disk)
        partitions = []
        for i in range(4):
            entry = mbr[MBR_PARTITIONS + 16 * i:MBR_PARTITIONS + 16 * (i + 1)]
            start, size = struct.unpack_from("<II", entry, 8)
            if entry[4] and size:
                partitions.append((i + 1, start, size, entry[4]))
        if [p[3] for p in partitions] != [MBR_TYPE_GPT_PROTECTIVE]:
            return [p[:3] for p in partitions]

        f.seek(BYTES_PER_PAGE)
        header = f.read(92)
        if header[:8] != b"EFI PART":
            raise NANDError("protective MBR without a GPT on %s" % disk)
        entries_lba, count, entry_size = struct.unpack_from("<QII", header, 0x48)
        f.seek(entries_lba * BYTES_PER_PAGE)
        table = f.read(count * entry_size)
    partitions = []
    for i in range(count):
        entry = table[i * entry_size:(i + 1) * entry_size]
        first, last = struct.unpack_from("<QQ", entry, 32)
        if entry[:16] != bytes(16):
            partitions.append((i + 1, first, last - first + 1))
    return partitions
