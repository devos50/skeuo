"""
NAND images of the iPod Touch 2G: 4 CEs of Samsung NAND, laid out the way the VSVFL production format and FTL_Format
of the iPhone OS 2.x kernel do it. The emulator stores every written page as <nand>/cs<ce>/<page>.page (page data
followed by the spare area); pages without a file are erased.

- format() writes an empty, formatted NAND: what a device has before its first restore.
- extract() takes the disk the FTL presents out of a NAND that iOS wrote itself, so its filesystems can be changed on
  the host; build() writes a new NAND from such a disk.

Ported from generate_nand.c and nand_disk.py of generate_nand_it2g.
"""
import os
import struct

BYTES_PER_PAGE = 4096
BYTES_PER_SPARE = 64
META_SIZE = 12  # the part of the spare area that the FTL/VFL sees
PAGES_PER_BLOCK = 128
NUM_CE = 4
BLOCKS_PER_CE = 4096
NUM_BANKS = 8  # the two planes of each CE are exposed as two banks
BLOCKS_PER_BANK = BLOCKS_PER_CE // 2
PAGES_PER_SUBLOCK = PAGES_PER_BLOCK * NUM_BANKS

# VSVFL gives 976 out of every 1024 blocks to the user super blocks, the rest is reserved to replace bad blocks
VFL_NUM_OF_SUBLKS = (0x3d0 * BLOCKS_PER_BANK) // 1024
VFL_RESERVED_BLOCKS_PER_BANK = BLOCKS_PER_BANK - VFL_NUM_OF_SUBLKS
VFL_CXT_BLOCK = 1  # the VFL context lives in the blocks after block 0
VFL_INFO_SECTION_SIZE = 4
VFL_NUM_OF_VFL_CXT_COPIES = 8
VFL_META_VERSION = 2
VFL_VENDOR_SPECIFIC_TYPE = 0x100014
VFL_CTX_SPARE_TYPE = 0x80
VFL_BAD_MAP_TABLE_AVAILABLE_MARK = 0xFFF0
VFL_BAD_MAP_TABLE_UNUSABLE_MARK = 0xFFFF
WMR_MAX_RESERVED_SIZE = 820
VFL_INITIAL_CXT_AGE = 0xFFFFFF00  # ages count down: the context with the lowest age is the newest

FTL_CXT_SECTION_SIZE = 3
FREE_SECTION_SIZE = 20
LOG_SECTION_SIZE = FREE_SECTION_SIZE - 3
FTL_DATA_VBN_START = FTL_CXT_SECTION_SIZE + FREE_SECTION_SIZE
FTL_NUM_OF_LBNS = VFL_NUM_OF_SUBLKS - FTL_DATA_VBN_START
FTL_CXT_VBN = 0
FTL_MAP_TABLE_FIRST_VPN = 5
FTL_INITIAL_CXT_AGE = 0xFFFFFFFF
FTL_SPARE_TYPE_CXT_INDEX = 0x43
FTL_SPARE_TYPES_DATA = (0x40, 0x41)
FTL_SPARE_TYPE_DATA = 0x41
MAX_NUM_OF_MAP_TABLES = 18
MAX_NUM_OF_EC_TABLES = 36
MAX_NUM_OF_LOGCXT_MAPS = 34
DISK_NUM_OF_LBAS = FTL_NUM_OF_LBNS * PAGES_PER_SUBLOCK

# both the NAND signature and the bad block table are stored in the last block of each CE
SPECIAL_BLOCK = BLOCKS_PER_CE - 1
NAND_SIG_PAGE = SPECIAL_BLOCK * PAGES_PER_BLOCK
BBT_PAGE = NAND_SIG_PAGE + 1

# chip blocks that are replaced by a block in the reserved area of the same plane (block 0 and the VFL info blocks)
REMAPPED_BLOCKS = (0, 1, 2, 3, 4)

MBR_PARTITIONS = 0x1BE


class NANDError(Exception):
    pass


def remap_chip_block(chip_block):
    """The chip block that replaces a remapped chip block. VSVFL takes replacement i of a plane from virtual block
    VFL_NUM_OF_SUBLKS + i of that plane's bank."""
    plane_idx = [0, 0]
    for block in REMAPPED_BLOCKS:
        plane = block & 1
        if block == chip_block:
            return (VFL_NUM_OF_SUBLKS + plane_idx[plane]) * 2 + plane
        plane_idx[plane] += 1
    return chip_block


def vpn_to_ppn(vpn):
    """Virtual page -> (CE, physical page on that CE), like VSVFL."""
    bank = vpn % NUM_BANKS
    vbn = vpn // PAGES_PER_SUBLOCK
    page_in_block = (vpn % PAGES_PER_SUBLOCK) // NUM_BANKS
    # two-plane LSB reordering: the banks >= NUM_CE map to the odd blocks of a CE
    chip_block = vbn * 2 + bank // NUM_CE
    return bank % NUM_CE, remap_chip_block(chip_block) * PAGES_PER_BLOCK + page_in_block


def lpn_to_ppn(lpn):
    lbn = lpn // PAGES_PER_SUBLOCK
    return vpn_to_ppn((lbn + FTL_DATA_VBN_START) * PAGES_PER_SUBLOCK + lpn % PAGES_PER_SUBLOCK)


def virtual_page(ce, ppn):
    """The virtual page that VSVFL keeps at physical page ppn of a CE (the inverse of vpn_to_ppn for the data blocks,
    which are never remapped)."""
    chip_block, page_in_block = divmod(ppn, PAGES_PER_BLOCK)
    vbn, plane = divmod(chip_block, 2)
    return vbn * PAGES_PER_SUBLOCK + page_in_block * NUM_BANKS + ce + NUM_CE * plane


class Writer:
    def __init__(self, nand):
        if os.path.exists(nand):
            raise NANDError("%s exists already" % nand)
        self.nand = nand
        for ce in range(NUM_CE):
            os.makedirs(os.path.join(nand, "cs%d" % ce))

    def page(self, data, meta, ce, page_index):
        # the part of the spare area that is not used by the meta data stays erased
        spare = (meta or b"").ljust(BYTES_PER_SPARE, b"\xff")
        with open(os.path.join(self.nand, "cs%d" % ce, "%d.page" % page_index), "wb") as f:
            f.write((data or b"").ljust(BYTES_PER_PAGE, b"\0"))
            f.write(spare)

    def data_page(self, data, lpn):
        """A page of a data block, with the meta data that FTL_Read and _FTLRestore expect: the logical page, a write
        age older than anything the FTL writes later, and the data spare type. Bytes 8 and 10 must stay 0xFF, they
        are the ECC mark."""
        meta = bytearray(b"\xff" * META_SIZE)
        struct.pack_into("<II", meta, 0, lpn, 0)
        meta[9] = FTL_SPARE_TYPE_DATA
        self.page(data, bytes(meta), *lpn_to_ppn(lpn))

    def special_page(self, magic, data, page_index):
        """A page in the format the VFL uses for its special blocks: a signature, the data length and the data."""
        page = bytearray(BYTES_PER_PAGE)
        page[:len(magic)] = magic
        struct.pack_into("<I", page, 0x34, len(data))
        page[0x38:0x38 + len(data)] = data
        for ce in range(NUM_CE):
            self.page(bytes(page), None, ce, page_index)

    def vfl_context(self):
        for ce in range(NUM_CE):
            meta = bytearray(2048)
            struct.pack_into("<III", meta, 0, ce, VFL_INITIAL_CXT_AGE, 0)  # dwGlobalCxtAge, dwCxtAge, dwFTLType
            # the context is written in groups of VFL_NUM_OF_VFL_CXT_COPIES pages to info block wCxtLocation (an
            # index in awInfoBlk); the next group goes after the first one
            struct.pack_into("<HH", meta, 12, 0, VFL_NUM_OF_VFL_CXT_COPIES)

            # replace the blocks that overlap with the VFL info area by blocks from the reserved area of the same plane
            bad_map = [VFL_BAD_MAP_TABLE_AVAILABLE_MARK] * WMR_MAX_RESERVED_SIZE
            plane_idx = [0, 0]
            for block in REMAPPED_BLOCKS:
                plane = block & 1
                bad_map[plane * VFL_RESERVED_BLOCKS_PER_BANK + plane_idx[plane]] = block
                plane_idx[plane] += 1
            # the last reserved block of the second plane holds the NAND signature and the BBT
            bad_map[2 * VFL_RESERVED_BLOCKS_PER_BANK - 1] = VFL_BAD_MAP_TABLE_UNUSABLE_MARK

            struct.pack_into("<H", meta, 16, len(REMAPPED_BLOCKS))           # wNumOfInitBadBlk
            struct.pack_into("<HH", meta, 22, *plane_idx)                    # awReplacementIdx
            struct.pack_into("<%dH" % WMR_MAX_RESERVED_SIZE, meta, 38, *bad_map)
            struct.pack_into("<%dH" % VFL_INFO_SECTION_SIZE, meta, 1678,
                             *range(VFL_CXT_BLOCK, VFL_CXT_BLOCK + VFL_INFO_SECTION_SIZE))
            struct.pack_into("<HH", meta, 1686, VFL_NUM_OF_SUBLKS, VFL_NUM_OF_SUBLKS)  # FTL and VFL super blocks
            struct.pack_into("<%dH" % FTL_CXT_SECTION_SIZE, meta, 1690,
                             *range(FTL_CXT_VBN, FTL_CXT_VBN + FTL_CXT_SECTION_SIZE))
            struct.pack_into("<I", meta, 1754, VFL_VENDOR_SPECIFIC_TYPE)
            struct.pack_into("<I", meta, 2036, VFL_META_VERSION)

            spare = struct.pack("<IIBB", VFL_INITIAL_CXT_AGE, 0, 0, VFL_CTX_SPARE_TYPE)
            for i in range(VFL_NUM_OF_VFL_CXT_COPIES):
                self.page(bytes(meta), spare, ce, VFL_CXT_BLOCK * PAGES_PER_BLOCK + i)

    def ftl_page(self, data, vpn):
        spare = struct.pack("<IIBB", FTL_INITIAL_CXT_AGE, 0, 0xFF, FTL_SPARE_TYPE_CXT_INDEX)
        self.page(data, spare, *vpn_to_ppn(vpn))

    def ftl_context(self):
        ctx_vpn = FTL_CXT_VBN * PAGES_PER_SUBLOCK
        # the first page of a FTL context block identifies the block, and is the (empty) EC/RC/log table page
        self.ftl_page(None, ctx_vpn)

        meta = bytearray(2048)
        struct.pack_into("<II", meta, 0, FTL_INITIAL_CXT_AGE - 1, 1)                    # dwAge, dwWriteAge
        struct.pack_into("<H", meta, 8, FREE_SECTION_SIZE)                              # wNumOfFreeVb
        struct.pack_into("<%dH" % FREE_SECTION_SIZE, meta, 14,
                         *range(FTL_CXT_SECTION_SIZE, FTL_CXT_SECTION_SIZE + FREE_SECTION_SIZE))
        for i in range(LOG_SECTION_SIZE + 1):
            struct.pack_into("<H", meta, 420 + i * 20 + 4, 0xFFFF)                      # aLOGCxtTable[i].wVbn
        struct.pack_into("<%dH" % FTL_CXT_SECTION_SIZE, meta, 786,
                         *range(FTL_CXT_VBN, FTL_CXT_VBN + FTL_CXT_SECTION_SIZE))       # awMapCxtVbn

        # the logical block -> virtual block mapping tables
        items_per_map = BYTES_PER_PAGE // 2
        for i in range(MAX_NUM_OF_MAP_TABLES):
            vpn = ctx_vpn + FTL_MAP_TABLE_FIRST_VPN + i
            struct.pack_into("<I", meta, 56 + i * 4, vpn)
            lbns = range(i * items_per_map, (i + 1) * items_per_map)
            table = struct.pack("<%dH" % items_per_map,
                                *(lbn + FTL_DATA_VBN_START if lbn < FTL_NUM_OF_LBNS else 0xFFFF for lbn in lbns))
            self.ftl_page(table, vpn)

        # the erase counter, log context and read counter tables are all zero, so they all use the first page
        struct.pack_into("<%dI" % MAX_NUM_OF_EC_TABLES, meta, 128, *[ctx_vpn] * MAX_NUM_OF_EC_TABLES)
        struct.pack_into("<%dI" % MAX_NUM_OF_EC_TABLES, meta, 800, *[ctx_vpn] * MAX_NUM_OF_EC_TABLES)
        struct.pack_into("<%dI" % MAX_NUM_OF_LOGCXT_MAPS, meta, 272, *[ctx_vpn] * MAX_NUM_OF_LOGCXT_MAPS)
        struct.pack_into("<II", meta, 976, 0xFFFFFFFF, 0xFFFFFFFF)                      # adwStatPtrs

        # the FTL meta data goes into the last page of the context block, the FTL searches it backwards from there
        meta_vpn = ctx_vpn + PAGES_PER_SUBLOCK - 1
        struct.pack_into("<II", meta, 792, meta_vpn, 1)                 # dwCurrMapCxtPage, boolFlashCxtIsValid
        struct.pack_into("<II", meta, 2040, 0x46560000, ~0x46560000 & 0xFFFFFFFF)   # dwVersion, dwVersionNot
        self.ftl_page(bytes(meta), meta_vpn)

    def low_level_format(self):
        self.vfl_context()
        self.ftl_context()
        self.special_page(b"NANDDRIVERSIGN", struct.pack("<I", 0x43313131), NAND_SIG_PAGE)
        # all blocks are good; the VFL rebuilds its bad block map from awBadMapTable when it opens the NAND
        self.special_page(b"DEVICEINFOBBT", b"\xff" * (BLOCKS_PER_CE // 8), BBT_PAGE)


def format(nand):
    """Writes an empty, formatted NAND."""
    Writer(nand).low_level_format()


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


def build(disk, nand):
    """Writes a new NAND from a disk image (logical page n at offset n * BYTES_PER_PAGE). Only the logical blocks
    that hold data are written, each of them completely, since the FTL identifies a data block by the meta data of
    its last page when it rebuilds its tables."""
    writer = Writer(nand)
    writer.low_level_format()
    block_size = PAGES_PER_SUBLOCK * BYTES_PER_PAGE
    zero_page = bytes(BYTES_PER_PAGE)
    with open(disk, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size > DISK_NUM_OF_LBAS * BYTES_PER_PAGE:
            raise NANDError("%s is larger than the disk (%d pages)" % (disk, DISK_NUM_OF_LBAS))
        blocks = set()
        for start, length in data_regions(f, size):
            blocks.update(range(start // block_size, (start + length - 1) // block_size + 1))
        for lbn in sorted(blocks):
            f.seek(lbn * block_size)
            data = f.read(block_size)
            if not hasattr(os, "SEEK_DATA") and not any(data):
                continue  # without hole information, skip blocks that are all zeroes
            for i in range(PAGES_PER_SUBLOCK):
                page = data[i * BYTES_PER_PAGE:(i + 1) * BYTES_PER_PAGE]
                writer.data_page(page if len(page) == BYTES_PER_PAGE else page + zero_page[len(page):],
                                 lbn * PAGES_PER_SUBLOCK + i)
    return len(blocks)


def newest_pages(nand):
    """Returns {logical page: path of the page file with its newest copy}. The FTL stores the logical page of each
    data page in its spare area with the write age of its block; of several copies the newest is the one in the
    youngest block, and within a block the one written last."""
    newest = {}
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
            if len(meta) < META_SIZE or meta[9] not in FTL_SPARE_TYPES_DATA:
                continue
            lpn, age = struct.unpack_from("<II", meta)
            order = (age, virtual_page(ce, int(entry.name[:-5])))
            if lpn not in newest or order > newest[lpn][0]:
                newest[lpn] = (order, entry.path)
    return {lpn: path for lpn, (order, path) in newest.items()}


def extract(nand, disk):
    """Writes the disk the FTL of a NAND presents to a sparse disk image."""
    pages = newest_pages(nand)
    if not pages:
        raise NANDError("no data pages in %s" % nand)
    with open(disk, "wb") as f:
        f.truncate((max(pages) + 1) * BYTES_PER_PAGE)
        for lpn, path in pages.items():
            with open(path, "rb") as page:
                f.seek(lpn * BYTES_PER_PAGE)
                f.write(page.read(BYTES_PER_PAGE))
    return len(pages)


def mbr_partitions(disk):
    """Returns [(number, first page, pages)] of the MBR at logical page 0."""
    with open(disk, "rb") as f:
        mbr = f.read(512)
    if mbr[510:512] != b"\x55\xaa":
        raise NANDError("no MBR on %s" % disk)
    partitions = []
    for i in range(4):
        entry = mbr[MBR_PARTITIONS + 16 * i:MBR_PARTITIONS + 16 * (i + 1)]
        start, size = struct.unpack_from("<II", entry, 8)
        if entry[4] and size:
            partitions.append((i + 1, start, size))
    return partitions
