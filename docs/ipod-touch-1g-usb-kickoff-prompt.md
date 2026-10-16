Bring up USB on the iPod touch 1G (S5L8900, n45ap, iPod1,1) machine, so that Skeuo can restore a 1G from an IPSW
and I can SSH into it over USB. This is step 5 of docs/multi-device-plan.md ("The USB link on the 1G"). Read the plan
first, especially "The 1.1.5 kernel" (the USB race) and "The 1G's NOR"/"The 1G's NAND". The previous kickoff prompt,
docs/ipod-touch-1g-kickoff-prompt.md, has the tools and how the 1G boots today.

## The goal, in three checkpoints

1. **USB in the booted system.** A 1.1.5 device built by hand (`make_nor_1g.py`, `make_nand_disk_1g.py`) boots to
   SpringBoard with its USB device stack up and the cable connected, without the device-tree workaround, and
   libimobiledevice reaches it through `skeuo run`'s usbmuxd (`ideviceinfo` answers).
2. **Restore.** `python3 -m skeuo restore ~/Library/Application\ Support/Skeuo/ipsw/iPod1,1_1.1.5_4B1_Restore.ipsw
   <bundle>` makes a working 1G bundle from a factory-new disk and NOR, the way it does for the 2G, and `skeuo run`
   boots it to the home screen.
3. **SSH.** `ssh root@...` gets a shell on the running device, over USB (the 1G has no Wi-Fi yet: SDIO times out).

Stop at each checkpoint, record it in the plan, commit, and tell me what you found before going on.

## What's there

- **The 1G machine** (`hw/arm/ipod_touch_1g.c`, qemu-ios branch `skeuo-multi-device`): USB OTG (0x38400000) and the USB
  PHY (0x3c400000) are unimplemented regions. `-d unimp` shows what 1.1.5 touches today (usb-otg 0x800-0x81c,
  0x900-0xbc8, 0xe00; usb-phys 0x000, 0x008, 0x018).
- **The 2G has all the pieces**, shared or ready to share:
  - `s5l.usb_otg` (`s5l_usb_otg.c`, already built under `CONFIG_S5L`), the Synopsys OTG core, parameterised by its
    hardware config words (the 2G passes `s5l8720_usb_hwcfg`; the old `ipod_touch_1g` branch has
    `s5l8900_usb_hwcfg`). `s5l.usbphys` (`s5l_usb_phys.c`) has the cable state.
  - The USB link to the host (`ipod_touch_usb_link.c`): a chardev protocol (HELLO, SETUP/OUT/IN, RESET, CANCEL) behind
    the machine's `usb-chardev` option. The PMU's `usb_present` and the PHY's `cable_connected` follow it.
  - In the pipeline, `skeuo/usb/`: `link.py` (the host side of that protocol), `dfu.py` (DFU and recovery mode:
    upload, commands), `mux.py` and `muxd.py` (usbmux, and a usbmuxd on `127.0.0.1:27015` for libimobiledevice,
    which already tunnels TCP connections to a device port).
  - `restore.py`/`restored.py`: the 2G's restore (iBSS → iBEC → restore ramdisk → restored: partitions, asr, NOR
    images), `prepare.py`/`activation.py` after it, `emulator.py` for the QEMU command line. Only the iPod2,1
    profile exists (`skeuo/devices/ipod2_1.py`); the 1G needs its own (`ipod1_1.py`, the plan's "Pipeline").
- **The USB race.** 1.1.5's AppleS5L8900XUSBWrangler panics in `phyRegistered` on a null notifier, because the PHY
  (`otgphyctrl`) is always published before the wrangler stores its notifier. It isn't timing or a missing register
  (the plan has the evidence). `make_nor_1g.py` sidesteps it by renaming `usb-otg`'s compatible, which leaves 1.1.5
  with no USB. **Checkpoint 1 needs a real answer to this.** Ideas, none tried: find what lets a real device win
  the race (an interrupt, a register, or a property the PHY or the clock controller waits on that we answer too
  early); compare with the old `ipod_touch_1g` branch, which got through; as a last resort, a targeted patch that a
  restore could apply too (say what and why before doing it). 2.2.1's iPod1,1 kernel uses AppleSynopsysOTG2 instead
  and may not have the race, but there's no 2.x iPod1,1 IPSW here.
- **The 1.1.5 IPSW** (`iPod1,1_1.1.5_4B1_Restore.ipsw`, the only firmware Apple serves for iPod1,1; extract it into its
  own scratch folder) has `Firmware/dfu/` with WTF.s5l8900xall, iBSS.n45ap and iBEC.n45ap (8900 containers, key
  0x837), the all_flash images, kernelcache.release.s5l8900xrb, the restore ramdisk 018-3764-1.dmg ("User") and the
  root filesystem 018-3755-1.dmg. Restore.plist: DFU product ID 4642 (0x1222), recovery 4736 (0x1280).
- **What a 1.1.x restore needs is mostly unknown**: the plan decided to do 1.1.x "later, as its own step", assuming
  2.x/3.x would come first, but they were paid upgrades and no IPSW is on hand, so 1.1.5 it is. To find out:
  whether the emulator can start iBSS directly as it does on the 2G (the bootrom stand-in, `s5l8900.bootrom`, has
  no USB; WTF is the DFU-mode stage on the S5L8900), what iBSS/iBEC 1.1.5 need from USB in recovery mode, and how
  1.1.5's restored talks to the host (2.x's protocol is in `restored.py`; 1.x's may differ: compare the ramdisk's
  restored with it). Also where a real restore writes LLB and the other NOR images (the plan's "The 1G's NOR": for
  now LLB is first and found by tag), and how it lays out the NAND (Whimory 2.1's legacy format, which `nand-disk`
  presents; `nand.py` still only knows the 2G's VSVFL layout and can't fold the 1G's overlay).
- **What the hand-built disk does that a restore must do too**, done today by `make_nand_disk_1g.py`: lockdownd
  patched to settle on Activated (1.1.x has no code signing), 2.1.1's initial data ark, /private/var copied to the
  data volume. Those belong in `prepare.py` for the 1G.
- **SSH: nothing exists yet.** iPhone OS has no sshd. Since 1.1.x runs unsigned code, `prepare.py` can install one
  in the system volume with a LaunchDaemons plist; 1.x's root password is "alpine". The host reaches it through the
  usbmux tunnel (`muxd.py` already connects a TCP client to a device port; libimobiledevice's `iproxy` against
  `USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015`, or a `skeuo` command that forwards a local port). Whether 1.1.5's
  device side speaks the same usbmux protocol as 2.x is to check. **Where the sshd comes from is my decision**:
  propose options (for example building dropbear for armv6 against the device's own libSystem from the user's IPSW,
  so nothing Apple ships with Skeuo) and ask me before downloading any third-party binary or package.

## Tools

- Build: `packaging/macos/build-qemu.sh` (release build in `packaging/macos/build/qemu/`; `ninja qemu-system-arm` in
  that folder rebuilds).
- `pipeline/tools/1g/`: `make_nor_1g.py`, `make_nand_disk_1g.py`, `run1g.sh`, `iboot_console.sh`, `dis.py` (see the
  previous kickoff prompt). A run with the cable needs `usb-chardev=<id>` and a matching `-chardev`, as `emulator.py`
  does for the 2G.
- Boots take about 20 seconds to SpringBoard; keep test runs short (25-30 s), not 1-2 minutes. Buttons with HMP
  `sendkey p 300` / `sendkey h 300`, touches over QMP (`input-send-event`, absolute x/y in 0..0x7fff and the left
  `btn`), screenshots with `screendump`.
- Tracing: `-trace 'pl080*'`, `-d unimp,guest_errors`; lldb on `-gdb tcp::12345 -S` (`lldb --arch armv6`,
  `gdb-remote 12345`). The kernelcache is in Ghidra as `/iPod Touch 1G/1.1.5/kernelcache.n45ap.1.1.5.macho` (the
  `mcp__ghidra__*` tools; load the `xref` tool group for cross-references); SpringBoard and lockdownd 1.1.5 are there
  too. openiBoot is the best reference for S5L8900 registers.
- To read the system volume: cut partition 1 out of a disk image (MBR with 2048-byte LBAs) and
  `hdiutil attach -readonly -nobrowse -imagekey diskimage-class=CRawDiskImage`.

## Ground rules

- Skeuo ships no Apple code. Use Apple binaries only to learn how things work; anything installed on a device is
  built from the user's IPSW or from free software.
- Keep the machine contract (emulator `docs/system/arm/ipod-touch.rst`): a 1G option that isn't supported is refused,
  not ignored. The 2G must keep booting, suspending and resuming; check it with a 2.1.1 bundle when you change shared
  code (`s5l_usb_otg.c`, the USB link, the pipeline's USB code).
- Commit in reviewable pieces in the emulator and in Skeuo, and keep the plan up to date as you learn things. Ask me
  before pushing.
