# Skeuo with more than one device: plan

Status: agreed (2026-10-14). Steps 1 and 2 of the order of work done (2026-10-15). The first new device is the
iPod touch 1G (S5L8900, `n45ap`, `iPod1,1`), whose emulator lives on the
[`ipod_touch_1g` branch of devos50/qemu-ios](https://github.com/devos50/qemu-ios/tree/ipod_touch_1g).

Decisions (Martijn, 2026-10-14):
- The models both devices share are renamed after the chip family (`ipod_touch_spi.c` → `s5l_spi.c`; `s5l87xx` was proposed first, but it
  doesn't cover the S5L8900), in one
  commit before the 1G's models arrive.
- 1G firmware: 2.x and 3.x first; 1.1.x later, as its own step. **Changed (2026-10-15): 1.1.5 first.** Apple only
  serves 1.1 to 1.1.5 for iPod1,1 (2.x and 3.x were paid upgrades, never on a public URL), and the 1G branch only
  ever booted 1.1.x. 2.x and 3.x come later, from IPSWs users supply.
- The 1G ships without Wi-Fi at first; Wi-Fi is a later capability.
- Experimental devices are shown to every user, marked as experimental.

## Where things stand

- **Emulator, 2G** (`emulator/` = qemu-ios `skeuo`, d7729e5337): one machine, `iPod-Touch` (`TYPE_IPOD_TOUCH`,
  `IPodTouchMachineState`), in `hw/arm/ipod_touch_2g.c` with ~35 `hw/arm/ipod_touch_*.c` device models. It is on
  current upstream QEMU, saves every device model (suspend/resume), and starts LLB from the NOR without the bootrom.
- **Emulator, 1G** (qemu-ios `ipod_touch_1g`, last commit 2023-11-07): 99 commits on QEMU from December 2021
  (merge base 89f3bfa326). It reaches the kernel, draws the screen, and takes multitouch, home and power. It is not
  ready for Skeuo:
  - It boots through the S5L8900 bootrom, with the bootrom's address table patched to jump to its own routines, and
    loads an already-decrypted iBoot from a file (`iboot=`), so a user would need two files from a real device.
  - The NAND is a directory of files (`nand=`), not a disk image with an overlay like the 2G's `nand-disk` and
    `nand-overlay`.
  - The NOR is 1 MB of parallel CFI flash (`pflash_cfi02`), where the 2G has SPI NOR.
  - No VMState (so no suspend), no USB link to the host (so no restore over USB, no usbmuxd), no audio, and the
    machine is also called `iPod-Touch`, with `mc->desc = "iPod Touch"`.
- **The same file names, with different contents.** The 1G branch has 21 `ipod_touch_*.c` files. 16 of them have a
  2G counterpart that started from the same code and has grown 2-5× since (VMState, bootrom-free boot, fixes):
  for example AES 134 → 627 lines, NAND 246 → 584, timer 142 → 364, USB OTG 616 → 934, LIS302DL 54 → 254. Five
  exist only on the 1G: the 8900 engine (the S5L8900's IMG2/8900 container decryption), the ADM, the NAND ECC, the
  LCD panel, and the machine `ipod_touch.c`.
- **Pipeline**: the 2G is assumed in a handful of places. `ipsw.py` has `DEVICE_TYPES = {"iPod2,1": ...}`,
  `download.py` the iPod2,1 firmware catalog, `nand.py` the 2G's VSVFL layout, `emulator.py` the
  `-M iPod-Touch,...` string, `restore.py`/`emulator.py` the S5L8720 bootrom. The rest is already per product: a
  bundle's `device.json` records `product`, `serve` has a `device_types` request and `create` takes a `product`.
- **App**: the bootrom check in `lib.rs` (S5L8720 size and SHA-256), "iPod touch (2nd generation)" in
  `EditDialog.svelte`, the key map in `DeviceWindow.svelte`, the S5L8720 text in `SettingsDialog.svelte`, and the
  device frame.

## Principle: one emulator, one Skeuo, a profile per device

Devices differ in their chip, their device models, their firmware format and what they can do. Skeuo should know
those differences in exactly one place per layer, and everything above it should ask instead of assume:

```
app          asks the pipeline what devices exist and what each can do
  │ device_types (profiles)
pipeline     one profile per product (iPod1,1, iPod2,1): firmware, NAND, restore, machine, capabilities
  │ -M <machine>,<the machine contract's options>
emulator     one qemu-system-arm, one machine per device, device models shared where the hardware is shared
```

## Emulator

### Port the 1G forward; don't merge the branch

The branch is 40,000 upstream commits behind `skeuo`, and its shared device models are early copies of the 2G's.
Merging would mean reconciling both histories file by file and would still leave the 1G without suspend. Instead,
port the 1G onto `skeuo` as a new machine, as a patch series like the 2G's ("hw/arm: ..."), taking from the 1G
branch only what is specific to the S5L8900 and the 1G's board.

Keep one `qemu-system-arm` with both machines. Two emulator builds would double the bundled emulator (~25 MB with its
dylibs, packaging-plan.md) and every fix to a shared model would have to be made twice.

### Machines

- `iPod-Touch-2G` (the current `iPod-Touch`, renamed) and `iPod-Touch-1G`, in `hw/arm/ipod_touch_2g.c` and
  `hw/arm/ipod_touch_1g.c`, each with its own state struct (`IPodTouch2GMachineState`, `IPodTouch1GMachineState`).
- A machine file holds only its board: the memory map, the interrupt numbers, the GPIO wiring, which device models
  it creates and how it connects them. The S5L8900 and S5L8720 constants go in `include/hw/arm/s5l8900.h` and
  `include/hw/arm/s5l8720.h`.
- Bundles don't store the machine name (the pipeline builds `-M` at every start), so the rename needs no migration.
  `iPod-Touch` can stay as an alias of the 2G for a while for people running QEMU by hand.

### Device models: shared where the hardware is shared

- **The same IP block with small differences: one model.** Start from the 2G model (it has the VMState and the
  fixes) and add the 1G's differences as qdev properties, set by the machine (a register's reset value, a FIFO depth,
  a revision). These are named after the chip family, not the device: `hw/arm/s5l_spi.c`, type `s5l.spi`, and so
  on. Done in step 2 for the blocks the 1G branch also models, after comparing their registers: SPI (the FIFO
  status fields sit at different bits), timer (7 timers on the 1G, 8 on the 2G, same layout), GPIO, sysic, chip
  ID, SHA1, USB OTG (the 1G branch's `s5l8900_usb_hwcfg` already parameterizes the OTG core) and PHY, MBX, TV out
  and SDIO.
  - **AES is shared after all** (found 2026-10-15 in LLB's driver): the registers are the same; the 1G branch
    had the input and output addresses swapped, unnoticed because the boot chain works in place. The S5L8900's
    boot chain passes SRAM at the uncached alias (bit 31 set) and writes the key and IV as big-endian words, so
    the model has `dma-mask` and `big-endian-words`. It keeps its `ipod_touch_aes` name until the next rename.
  - **I2C** has the same layout on both chips and builds under `CONFIG_S5L` (still `ipod_touch_i2c`).
  - **Timer**: the S5L8900 keeps its interrupt status at 0x10000 (0x118 on the S5L8720), with a latch at 0xf8
    (`irqstat-offset`, `irqlatch-offset`). **Chip ID**: only a revision (2) at the top of 0x4 (`chip`).
  - **SDIO** is renamed but still builds with the 2G: the 2G's BCM4325 Wi-Fi card is built into it. The 1G's card
    is a different chip (a Marvell), so the card has to become a device on an SDIO bus before the 1G's Wi-Fi.
  - **SPI** no longer creates the board's devices itself; the machine puts the NOR and the multitouch controller
    on the controllers' buses. **On the S5L8900** (found 2026-10-15 in iBoot 1.1.5's driver) the word size sits at
    bits 13-14 of the configuration, the FIFOs are 8 bytes deep with their levels at bits 4-7 (TX) and 8-11 (RX) of
    the status, and there is no TX count register (0x4c). The driver is interrupt driven and treats TX empty as an
    event it acknowledges. All properties of `s5l.spi` (`cfg-word-size-shift`, `status-*`, `rx-fifo-depth`,
    `tx-count`); the 2G's defaults are unchanged.
  - **GPIO**: the S5L8900's pin configuration register is at 0x320 (0x1e0 on the S5L8720), the `fsel-offset`
    property; output lines now cover 32 pads (the 1G's LCD chip select is 0x1800).
  - Not compared yet: I2C, the watchdog, and the 2G-only blocks; they keep `ipod_touch_*` names until the port
    shows whether the 1G has them.
- **Separate chips on both boards.** The LIS302DL accelerometer is the same part; the 1G uses the 2G model
  (`hw/arm/lis302dl.c`), with the 1G's I2C address and GPIOs set by the machine. The PMU is less clear: the 1G
  branch reads the RTC as BCD registers (`RTCSC` at 0x59 ... `RTCYR` at 0x5F, as on a PCF50633), the 2G model
  as a counter at 0x5C. To check before the 1G uses `ipod_touch_pcf50633_pmu.c`; the 2G's PMU may be a
  different part.
- **Hardware that really differs: separate models.** The 8900 engine and the ADM (S5L8900 only), the 1G's NAND
  controller and ECC, the 1G's LCD controller and panel, the first-generation multitouch controller, the 1G's clock
  tree, and parallel NOR (QEMU's `pflash_cfi02`) instead of SPI NOR. Each new model gets VMState from the start.
- Rename in a separate commit before the 1G models arrive, so the port's diffs stay readable, and add the commit to
  `.git-blame-ignore-revs`.

### The machine contract

What the pipeline and the app rely on, written down in the emulator (`docs/system/arm/ipod-touch.rst`) and kept the
same for every machine:

- **Options**: `nand-disk`, `nand-overlay`, `nand-epoch`, `nor`, `usb-chardev`, `boot-image`, `boot-args`,
  `bootrom`, `dfu`, and the `wifi`/`audio` settings. A machine that can't do one yet refuses it with a clear error
  instead of ignoring it.
- **QOM paths**: `/machine/accelerometer` with `orientation`, and any later ones, on every machine that has the part.
- **Input**: the LCD model takes absolute pointer events; the same keys for home, power, volume, rotate and mute.
- **Boot**: without a bootrom the machine starts the first boot stage from the NOR (or `boot-image`) itself. For the
  1G that means the machine unpacks LLB from its container on the NOR (the 8900 engine's job) and runs it, as the 2G
  does with IMG3, so neither the bootrom nor a decrypted iBoot is needed.
- **Run states**: `-action shutdown=pause`, migration to a file for suspend, loading with `-incoming`.
- **Identity**: `query-machines` and the machine's `desc` name the device ("iPod touch (1st generation)"), so the
  pipeline can check that the QEMU it was given has the machine it needs.

### Build

`CONFIG_IPOD_TOUCH_1G` and `CONFIG_IPOD_TOUCH_2G` in `hw/arm/Kconfig`, both selecting `CONFIG_S5L` for the
shared models (`CONFIG_S5L` exists since step 2). The release build (packaging-plan.md) builds both.

## Pipeline: device profiles

A package `pipeline/skeuo/devices/` with one module per product and a registry:

```python
@dataclass(frozen=True)
class Profile:
    product: str            # "iPod1,1"
    name: str               # "iPod touch (1st generation)"
    board: str              # "n45ap"
    soc: str                # "S5L8900"
    machine: str            # "iPod-Touch-1G"
    firmwares: dict         # version -> build, url, size, md5, sha1 (today's download.FIRMWARES)
    bootrom: BootromSpec    # size and SHA-256 of the optional bootrom dump
    image_format: str       # "img2" (8900 containers) or "img3"
    nand: NandLayout        # geometry and FTL/VFL kind ("legacy", "vsvfl")
    restore: str            # how a bundle is restored (see below)
    capabilities: frozenset # {"wifi", "audio", "accelerometer", "suspend", "usbmux"}
    support: str            # "supported" or "experimental"
```

- `ipsw.py`, `download.py`, `nand.py`, `emulator.py` and `restore.py` take the profile instead of the 2G's
  constants; `devices.get(bundle.info["product"])` finds it for an existing bundle.
- `device_types` returns the profiles (with capabilities and support level), so the app learns new devices without
  changes of its own. `create` refuses a product without a profile, as it refuses an unknown one today.
- Settings a device doesn't have are refused (`set_settings` with `audio` on a device without the capability).

### Firmware for the 1G

The iPod touch 1G shipped iPhone OS 1.1 to 3.1.3.

- **2.x and 3.x** use the same restored protocol as the 2G, so the in-emulator restore should work once the machine
  has the USB link, with the profile picking the 1G's NAND layout, image format and boot path. Target these first.
  To check: which of these firmwares' files are IMG3 and which still come in 8900 containers on the S5L8900.
- **1.1.x** uses 8900 containers and an older restore, with a different ramdisk and filesystem layout. Supporting it
  probably means a second restore path (or building the NAND image offline). Decided: later, as its own step.
- **Downloads**: which 1G IPSWs Apple still serves needs checking, as was done for the 2G (download.py). Like
  iPhone OS 3.0 on the 2G, some 1G upgrades were paid and may never have been on a public URL; those need "pick a
  local IPSW".

### The 1G's NOR (found 2026-10-15)

What LLB 1.1.5 (iBoot-204.3.16) needs from the NOR, so that Skeuo can write one itself (today
`pipeline/tools/1g/make_nor_1g.py` builds a test NOR from an IPSW):

- The image list's superblock at 0x8400: "2GMI", granule (0x40), image offset and boot block size (in granules),
  the number of granules to scan, and a CRC-32 of the first 0x30 bytes at 0x30. Images from offset × granule.
- LLB looks for the list on `nor0` (then `spi0`) and boots the `ibot` image; a failure ends in its USB DFU mode
  through the bootrom's routines, which the machine doesn't have.
- Each image as a restore leaves it, which differs from the IPSW's Img2 (header version 3):
  - its length in granules at 0x18 (0xffffffff in the IPSW);
  - flags at 0x1c: bit 24 (installed), bit 1 (signed for this device) and bit 9 (data encrypted);
  - the first extension's size at 0x60 has to cover what its CRC (at 0x68) covers: the IPSW's value plus 0xc;
  - the header's CRC-32 at 0x64 over 0x0-0x63;
  - the data AES-128-CBC encrypted (zero IV) with the device's image key: 16 fixed bytes encrypted with the UID key
    and a fixed IV (both in LLB, and in `ipod_touch_1g.c`);
  - a data signature at 0x20-0x5f: SHA-1 of the encrypted data plus 44 fixed bytes, encrypted with the image key;
  - a header signature at 0x3e0-0x3ff: SHA-1 of 0x0-0x3df plus 12 fixed bytes, encrypted with the image key.
  The image key comes from the emulator's UID key, so a NOR made this way only works in the emulator, which is fine.
- Still to learn: where a real restore puts LLB (for now it is the first image, and the machine finds it by tag),
  and whether iBoot needs more (SysCfg at 0x4000 holds only a stub).
- **NVRAM** (iBoot 1.1.5, FUN_18004b74 and FUN_18008576; the real dump has the same layout): two banks of 0x2000
  bytes at the end of `nor0` (0xfc000 and 0xfe000), the bank with the higher epoch wins. A bank is CHRP NVRAM: a 0x5a
  partition named "nvram" (header checksum at 1, length in 16-byte units at 2, name at 4) with the Adler-32 of 0x14
  to the end of the bank at 0x10 and the epoch at 0x14, then partitions from 0x20 up to a 0x7f free partition. The
  variables are in "common" (0x70, 0x800 bytes): "name=value" strings ending in a zero. `debug-uarts` is a mask of
  the UARTs iBoot writes its console to (1 = UART0); `boot-args` goes to the kernel. `make_nor_1g.py` writes
  `debug-uarts=1` and `boot-args=serial=1 debug=0x8 -v` (or its third argument).

### iBoot 1.1.5 and the bootrom (found 2026-10-15)

iBoot 1.1.5 (iBoot-204.3.16, at 0x18000000; in Ghidra as `/iPod Touch 1G/1.1.5/iBoot.n45ap.1.1.5.bin`) still
relies on the bootrom, through a jump table at 0x20000000 that it calls directly (ARM, `blx`):

- **USB**: its main init (0x18000794) calls 0x180036ec, which fills a context (two 64 KB buffers of 0xa5 and 0x5a,
  0x21000 bytes at 0x22000000), registers interrupts 0x27, 0x28 and 0x13 (USB OTG) with handlers that jump to
  0x20000034, 0x20000038 and 0x2000003c, and calls 0x20000044 (start) and 0x20000024 (with the clock) with it. The
  machine has nothing at 0x20000000, so iBoot runs into empty memory and panics.
- **The 8900 engine**: 0x2000002c and 0x20000030 take three arguments and return 1 on success (iBoot's wrappers at
  0x18003814 and 0x180037a8 gate clock 0x2d first). These are the routines the ipod_touch_1g branch patched in the
  bootrom's pointer table (0x2000008c/0x20000090).

iBoot also copies the bootrom's 64 KB to 0x0fd00000 and checks its CRC against the bootroms it knows how to patch.

The machine stands in for these with `s5l8900.bootrom` (decided 2026-10-15, like the ipod_touch_1g branch's
patched routine table but without the bootrom): a jump table written in the emulator over the bootrom's 64 KB,
each entry passing r0-r2 and its offset to the device. 0x2c checks the 8900 magic, 0x30 decrypts with key 0x837
(no signature checks), the USB entries do nothing, others are logged with `-d unimp`. The decrypt path hasn't run
yet: iBoot uses it when it loads an 8900 container, such as the kernelcache. iBoot then goes on to the NAND: it probes each chip enable (writes
0x77800 | bank to 0x0, command 0xff then 0x90 to 0x8, waits on 0x48, reads the ID at 0x80), times out on all of
them, and then starts its own USB OTG driver (recovery mode), waiting for the core's reset (0x38400010). So the
next pieces are the bootrom stand-ins, then the NAND controller (the 1G branch and openiBoot have it).

The LCD panel (`ipod-touch-1g.lcd-panel`, SPI1, chip select GPIO 0x1800): iBoot reads the ID from registers
0x5a-0x5c and waits for bit 0 of 0x15. The ID 71 c2 00 (from the 1G branch) decodes as PVT1, TMD, project M68,
driver NSC-Merlot; 0x10 in the third byte would say N45. iBoot keeps it for the device tree (`lcd-panel-id`), so
whether the kernel cares is still to see. iBoot also writes 2-byte commands to something on SPI0 (chip select
GPIO 0x700). iBoot prints nothing on UART0 so far.

### The 1G's NAND (found 2026-10-15)

`s5l8900.nand` is the FMC (0x38a00000) with 8 banks of Hynix NAND (0xa514d3ad: 4096 blocks of 128 pages of
2048 + 64 bytes per bank, the 8 GB model), `s5l8900.nand-ecc` the H1 ECC engine (0x38f00000, interrupt 0x2b), and the
pages come through DMAC0 (a PL080, peripheral 8). The registers are in the model's comment. The ECC engine computes
nothing: it fails only all-0xff sectors, as the real one does for erased pages, which the FIL relies on.

iBoot 1.1.5's NAND stack is Whimory 2.1 (FTL, VFL, FIL "H1"), the "legacy" format openiBoot reads. Since
2026-10-15 (qemu-ios `skeuo-multi-device` 88a5b4ce76, cb0998517f) the model presents a disk image in it, like the
2G's (`nand-disk`/`nand-overlay`; `nand-epoch` is refused), in `hw/arm/s5l8900_nand_disk.c`. What iBoot 1.1.5 needs
(FUN_18015ca0 opens it), checked in Ghidra and by running it:

- **The geometry** iBoot prints and keeps at 0x18024530/0x18024560: 4096 superblocks, 3872 user superblocks, 1024
  pages per superblock; VFL virtual blocks start at physical block 201, the FTL keeps 23 blocks for itself (3
  context, 20 free). So logical block n is FTL block 23 + n is physical block 224 + n on every bank, which uses the
  bank's last block too.
- **Signature**: 0x43303033 in the first word of any page of block 0 of bank 0 (the generator's 0x43303032 was 1.1's).
- **DEVICEINFOBBT** on every bank, in one of the first 3 pages of a block in the last 10%, and it must carry the
  factory bad block table (length at 0x34, a bit per block from 0x38, set = good): VFL_Open looks for its context
  only in blocks the table calls good. The generator's page had the magic and no table. It is in the last block,
  which the VFL then marks bad (aBadMark is a bit per 8 blocks, most significant first) and replaces by reserved
  block 5 (aBadMapTable[0] = 4095, wBadMapTableMaxIdx 1, reserved area 5-200).
- **VFL context**: the first good block among 1-199 with a context page (spare byte 8 = 0, byte 9 = 0x80) gives
  awInfoBlk (0x7a2); of those blocks the one whose page 0 has the lowest non-zero spare age wins, and its last group
  of 8 copies is read. The bank with the highest dwGlobalCxtAge gives aFTLCxtVbn. Checksums at 0x7f8 (sum and XOR,
  seed 0xAABBCCDD); iBoot's check only fails when the sum is wrong and the XOR right.
- **FTL context**: of FTL blocks aFTLCxtVbn, the one whose page 0 has spare type 0x43-0x4f and the lowest age; its
  meta data is the last page with spare type 'C' (searched backwards). The map (4 pages), log map (17), erase
  counters (4) and read counters (4, only with dwVersion 0x46560000) must all be readable: they point at the zero
  first page. The generator's struct layouts (vfl.h, ftl.h) match iBoot 1.1.5.
- **Spare**: 12 bytes of meta data, then the ECC (zero here). A data page's meta holds its logical page and 0xff in
  byte 10 (FTL_Read complains otherwise).
- **Partitions**: iBoot reads only an MBR (the four entries at 0x1be, any non-zero type, no 0x55aa check, no GPT),
  with LBAs in the block device's 2048-byte blocks (falling back to 512 if the partitions don't fit). Partition 1
  is `nand0a`, the default boot-partition. 1.1.5's fstab mounts disk0s1 at / (ro) and disk0s2 at /private/var.
- iBoot then mounts the HFSX system volume, loads `/System/Library/Caches/com.apple.kernelcaches/
  kernelcache.s5l8900xrb` (the IPSW's 8900 container, encrypted) to 0x0b000000, has the bootrom stand-in decrypt it
  (entry 0x30), decompresses it and starts the kernel, which runs (in FIQ mode around 0xc006152c-0xc0061640 after
  20 s) with nothing on the serial port.

Programming and erasing came with the ADM (2026-10-16, see "The 1.1.5 kernel"); the 1.1.5 kernel reads the same
MBR as iBoot (disk0s1, disk0s2), so no GPT is needed. Still to do: folding the 1G's overlay in `nand.py`.
`pipeline/tools/1g/make_nand_disk_1g.py` builds a test disk from the 1.1.5 IPSW: the root filesystem is a FileVault
(encrcdsa) DMG, VFDecrypt key c7973558e8f6af22e38d4573737d1533f1d5eec202bf86a32d941975d76f8906c7f0afe4 (from The
iPhone Wiki), holding an Apple Partition Map with the HFSX volume ("LittleBear4B1.N45Bundle").

### The 1.1.5 kernel (found 2026-10-15)

The kernelcache (Darwin 9.0.0d1, xnu-933.0.0.211, RELEASE_ARM_S5L8900XRB) is an 8900 container (key 0x837)
holding "complzss" (LZSS, 0x180-byte header); the kernel has symbols, the prelinked kexts don't (their personalities
are in the prelink plist). With the NVRAM above it logs to UART0 and, with `-v`, to the screen. What it needed:

- **The timer's interrupt status** (qemu-ios a4c5e8ee49): the S5L8900 has seven timers, so timer n's status is at
  (6 - n) * 8, not (7 - n) * 8. The kernel's decrementer is timer 4 (6 MHz, routed to the FIQ), and its FIQ handler
  acknowledges it with 0x30000 at 0xf8; iBoot's handler reads timer 4 at bit 16 too. With the S5L8720's layout the
  FIQ never cleared (the old "spins around 0xc006152c"). `s5l.timer` has a `timers` property (7 on the 1G).
- **The LCD controller** (df9e248aaa, `s5l8900.lcd`): iBoot fills the kernel's video boot arguments from the
  window registers it set up (base at 0x78, width << 16 | height at 0x7c, format bits 8-10 at 0x74 for window 1;
  windows of 0x18 bytes from 0x58). Reading 0 there left the kernel in PE_init_iokit, whose loop that centres the
  boot logo against half the screen height doesn't end for a height of 0. The model keeps the registers and draws
  the window (320x480, 32 or 16 bits per pixel). Window enable bits and the interrupt are unknown.
- **The MBX** (619a7efe09, the 2G's `s5l.mbx`): AppleMBX's core reset ends with 0x80 in 0x85c and 0 in 0x81c and
  then reads 0x12c until bit 8 (REGION_DONE), with no timeout. The model now raises it for 0x85c bit 7; the 2.1.1
  kernel never writes 0x85c.

The kernel then starts its IOKit drivers (VIC, edge IC, GPIO, power and clock controllers, DMACs, USB, ADM, MPVD,
SPI, I2C, timer, watchdog, I2S, MBX, NOR access) and **panicked in AppleS5L8900XUSBWrangler::phyRegistered**
(0xc04c24e0, a null pointer). This is a race in Apple's driver, not a missing register, and we work around it in the
NOR's device tree (2026-10-16):

- **The race.** The wrangler's start (the call at 0xc04c2338) adds a publish notification for AppleS5L8900XUSBPhy
  and only stores the notifier (at +0x6c) when that call returns; the handler removes the notifier first thing. If
  the PHY (`otgphyctrl`) is already published, the handler runs inside the call on a null notifier.
- **Why the PHY always wins here** (traced with lldb; the kernelcache is now in Ghidra as
  `/iPod Touch 1G/1.1.5/kernelcache.n45ap.1.1.5.macho`). AppleS5L8900XIO (0xc04911e8) publishes the arm-io children
  in device-tree order, each matched on a new config thread, all at the same fixed priority (0x51, no usage decay
  yet), so the run queue is FIFO. Two wait chains start from the clock controller's `registerService(2)`:
  - The PHY's start powers its block off: `IODelay(200)`, then `enableDeviceClock` → AppleS5L8900XIO, which sleeps
    on its command gate (0xc0491668) until its own `function-clock_gate` (clkrstgen) lookup returns. `otgphyctrl`
    has no `power-gates`, so it needs nothing else.
  - AppleARMCPU::start (0xc0157bc0) waits in `AppleARMFunction::withProvider("function-cpu_idle")` for the power
    controller. The power controller's start (0xc0498190) publishes only after
    `waitForService(AppleS5L8900XClockController)`. Then the CPU yields in `processor_start` (equal priority yields),
    `cpu_start` → `enableCPUInterrupt` wakes the VIC (blocked in IOCPUInterruptController::registerInterrupt until
    the CPU is enabled), the VIC registers IOInterruptController00403C70 and wakes the wrangler, asleep in
    IOFilterInterruptEventSource → lookUpInterruptController.
  - The clock controller's registration wakes AppleS5L8900XIO first (it started waiting first), then the power
    controller. AppleS5L8900XIO wakes the PHY before the power controller has even run, and the PHY needs one more
    pass through the run queue where the CPU → VIC → wrangler chain needs three or four. In the trace the PHY is
    queued about 7000 ticks (1 ms) ahead of the CPU.
- **Not timing, not a device.** None of these waits depends on a register or an interrupt. The panic is the same
  with a 0.1, 1 or 5 ms quantum (std_quantum patched from lldb), with `sched_cswtime` changed (the kernel measures
  it at boot, 18 to 1098 ticks from run to run, and `clock_delay_until` sleeps rather than spins above 8x it; the
  PHY's `IODelay` comes before its wait, so it doesn't matter), with `-icount shift=1` or 3 (5 and 7 livelock on the
  timer), and with empty boot-args (no serial KDP, no kprintf). A real device tree (iPod1,1 on 2.2.1, which uses
  AppleSynopsysOTG2 rather than the wrangler) has the arm-io children in the same order. Why a real device or the
  old `ipod_touch_1g` branch (whose timer is only approximate) gets through is not known.
- **The workaround.** `make_nor_1g.py` renames `otgphyctrl`'s compatible to `otgphyctrl,disabled` (same length) in
  the device tree it writes to the NOR, so AppleS5L8900XUSBPhy never matches; the wrangler waits for a PHY that
  never comes and the kernel boots on. 1.1.5's USB device stack won't come up while this is in place; revisit it
  when the 1G needs USB (restore, usbmuxd), where a 2.x kernel's driver may not have the race at all.

With the PHY disabled the kernel starts the serial ports, DMA channels, MPVD, MBX, the light sensor, the PMU
(pcf50635, which reads 625 mV for each DOWN converter), multitouch (Z2, bootloading over SPI with DMA), and then
panicked in AppleS5L8900XADMFMC: "ADM not ready to start". On the way it touches only unimplemented regions that
don't stop it: clock0 (reads 0x000, 0x008, 0x404, writes 0x004/0x008/0x404), usb-otg (0x800-0x81c, 0x900-0xbc8,
0xe00) and usb-phys (0x000, 0x008), and timer 6's register 0x14.

**The ADM** (qemu-ios a407aef35d, 5e037dae43; 2026-10-16). The ADM (0x38800000, interrupt 0x25) is a core that runs
the NAND firmware the kernel uploads ("CalmADMFMCFirmware-17"); `s5l8900.adm` carries out that firmware's commands
instead of running it. The protocol, from AppleS5L8900XADM (admStart 0xc04aa270, interrupt handler 0xc04a9de0) and
AppleS5L8900XADMFMC (start 0xc04acb14, command issue 0xc04abf9c, wait 0xc04ab88c, I/O 0xc04ac248 and 0xc04ab93c):

- CTRL (0x00): bit 0 runs the core, bit 1 is set while it is stopped, bit 2 is a soft reset (the kernel waits for it
  to clear). Code sections' physical addresses go to 0x50 and 0x68-0x80, data sections' to 0x54 and 0x84-0x8c; the
  kernel then writes 0x70 and sets bit 0, and AppleS5L8900XADMFMC waits (11 x 50 ms) for the POST byte at the start
  of data section 2 (0x3378 bytes) to reach 0x50, with the abort code after it 0.
- INT (0x04): bit 4 a command is done ("upload"), bit 6 the firmware logged to its ring at data section 2 + 0x2b58
  (the kernel prints it), bit 5 something the stop path waits for. Writing n acknowledges bit n; writing 2 hands over
  a command. Results are read from 0x30-0x3c: status (0 ok, 1 HW error, 2 bad argument, 0xff timeout), completion
  (0, 1, 2 = write errors), and for reads 0xfe when the page is blank (the kernel returns e00002e5).
- The command block at data section 2 + 0x1104, big-endian: opcode at 0x24 (1 reset, which leaves each bank's chip
  ID in data section 3; 2/3 interleaved/plain read; 4/5 interleaved/plain write; 6 erase), page count at 0x28, meta
  bytes per page at 0x2c (12), banks at 0x30, chip enables from 0x34, flags at 0x3c (bit 0: meta data only), ECC mode
  at 0x3e, bank index per page from 0x44, page per page from 0x244, a DMA segment list from 0xa44. The interleaved
  commands give one bank and first page per bank, and the pages go round the banks. The old branch's HLE read the
  opcodes little-endian (0x100-0x600).
- The page data doesn't go through the ADM: the kernel moves it through the FMC's FIFO with its own PL080 channel,
  after ringing the doorbell (writes add a 16-byte pad after each page). The meta data goes through data section 3.
  The model queues the pages on the NAND (a read stream refills the FIFO as the DMA drains it; a write stream
  programs a page per 2048 + 16 bytes and signals "stream-done", which completes the command) and writes pages and
  erases into the overlay.

With it the FTL opens ("Apple NAND Driver (AND) 0x43303033", FIL/VFL/FTL Init and Open OK), the system volume mounts
read-only at / and the data volume journaled at /private/var, and launchd starts the daemons (configd, lockdown,
mDNSResponder, mediaserverd, SpringBoard). With an empty data volume they failed on missing /var directories, so
`make_nand_disk_1g.py` now fills the data volume with the system volume's /private/var (as a restore does; the copy
is owned by uid 501).

**The screen** (qemu-ios 4fd7088c32, 2de433bacf). SpringBoard (pid 15) ran but drew nothing: its main thread sat in
an IOMobileFramebuffer call, in the swap wait 0xc037d378 (sleeping on the swap queue at +0x164, mode 2), on the
TV out's framebuffer, AppleH1TVOut (found by walking allproc from lldb: p_comm at proc+0xeb, the task at proc+0x138,
its threads from task+0x28 linked at thread+0x1ac, user registers at *(thread+0x28c), the kernel context at
*(thread+0x29c)+0x10). Two interrupts were missing:

- AppleH1CLCD changes the windows to the next buffer only from its interrupt (0x0d): enables at 0x14, status at
  0x18 (write 1s to clear), bit 0 each frame, bits 8-13 underruns. `s5l8900.lcd` raises bit 0 at 60 Hz.
- AppleH1TVOut turns the TV out on when a client hands it a buffer (SpringBoard does for every display): SDO+0x280 =
  1 (clear), SDO+0x284 = 0 (unmask), SDO+0x000 = 1 (enable), and finishes a buffer only on the SDO's frame interrupt
  (0x280 bit 0). The TV out's blocks are, from its `reg`, the SDO at 0x39300000 (interrupt 0x1e), the mixer at
  0x39200000 (interrupt 0x26, underflows at 0x4c) and a third block at 0x39100000 that takes the source formats.
  `s5l8900.tvout` keeps their registers and raises the SDO's frame interrupt at 60 Hz while it is enabled.

With both, SpringBoard draws the "Connect to iTunes" screen (1.1.5 is not activated). The boot-args don't matter
here: without them the Apple logo stays up instead of the console, and the same happens. But then the device idles
into sleep (the PMU driver enables idle sleep, the LCD and the drivers go to power state 0) and **the kernel panics in
the USB wrangler's power-down** (0xc04c1340, in 0xc04c11f8): it calls its PHY (this+0x68), which is null because the
`otgphyctrl` workaround keeps the PHY from matching. So the USB PHY race needs a real answer after all.

Not there yet either: the WM8758 codec on I2C1 (0x1a) doesn't answer, SDIO (Wi-Fi, "Timeout waiting for CMDRDY"),
and multitouch ("Could not detect HBPP").

## App

- The create dialog asks for the device first (from `device_types`), then the firmware. With one supported device
  the device step can stay hidden.
- Per profile: the frame art (the 1G's chrome back and its bezel), the screen size (320×480 on both), the key map,
  and which toggles the edit dialog shows (from the capabilities).
- Settings holds one optional bootrom per chip: S5L8900 and S5L8720 are different files, checked against the
  profile's `bootrom` instead of the constants in `lib.rs`.
- Experimental devices are shown to everyone (decided), marked as such in the create dialog, on the device card and
  in the edit dialog.
- The 1G's profile has no `wifi` capability at first, so the edit dialog hides the toggle and the create dialog
  leaves it off.

## Support policy

- A device is `experimental` until it restores and reaches SpringBoard for every firmware in its catalog, and
  suspends and resumes. Experimental devices appear in the app (marked), so they get used and reported on, but
  don't block a release.
- When CI comes (packaging-plan.md), its boot test runs per profile; only `supported` profiles fail the build.

## Order of work

1. **Profiles with only the 2G.** `pipeline/skeuo/devices/` with the iPod2,1 profile, and the pipeline and app
   reading from it. Changes no behaviour, and removes the 2G assumptions from the code that ships now. Done
   (2026-10-15); the key map, the device frame and the bootrom slot per chip are still the 2G's, for step 6.
2. **The machine contract and the rename**, in the emulator: rename the 2G machine to `iPod-Touch-2G` (with the
   alias), rename the shared models to `s5l_*`, write the contract down. Update `emulator.py` to the new name.
   Done (2026-10-15) on qemu-ios branch `skeuo-multi-device`: the contract is `docs/system/arm/ipod-touch.rst` in
   the emulator, and the iPod2,1 profile uses `iPod-Touch-2G`. A 2.1.1 device boots, suspends and resumes with it.
3. **The 1G machine on `skeuo`**, with stub regions for the parts not ported yet: first to LLB without the bootrom,
   then iBoot, then the kernel on the serial log, then SpringBoard from a NAND image made by hand.
   LLB and iBoot from the NOR done (2026-10-15, qemu-ios `skeuo-multi-device` b0b41a843c): LLB runs from the
   NOR, loads iBoot from it to 0x18000000 and starts it. See "The 1G's NOR" below for what a NOR has to hold.
   SPI and the LCD panel done (2026-10-15, efb02708ae): iBoot reads the panel's ID, sets up the display and
   then calls the bootrom's USB stack, which the machine doesn't have. See "iBoot 1.1.5 and the bootrom" below.
   The bootrom's services done (2026-10-15, 4b79b3893f): iBoot gets to the NAND, finds none and starts USB
   recovery mode. The NAND controller done (2026-10-15, 5fbb206159): iBoot finds the NAND and initialises its FTL,
   and stops because the NAND is empty. The NAND as a disk image done (2026-10-15, cb0998517f, read only): iBoot
   mounts 1.1.5's system volume, loads and decrypts the kernelcache and starts the kernel. See "The 1G's NAND".
   The kernel on the serial log done (2026-10-15, a4c5e8ee49..619a7efe09): the NVRAM in the NOR, the timer's
   interrupt layout, the LCD controller and the MBX. The kernel starts its IOKit drivers and panics in the USB
   wrangler (a race, see "The 1.1.5 kernel").
4. **The 1G's NAND as a disk image** with `nand-disk`/`nand-overlay`, and VMState for the 1G models: suspend works.
   The presentation and the options are done (step 3); writes into the overlay and `nand.py` are left.
5. **The USB link on the 1G** and the in-emulator restore of 2.x/3.x with the iPod1,1 profile, `experimental`.
6. **App**: device picker, 1G frame, capabilities in the edit dialog, the S5L8900 bootrom slot.
7. Later: Wi-Fi on the 1G (finishing the 1G branch's SDIO work), 1.1.x, and `supported` once the support policy's
   bar is met.
