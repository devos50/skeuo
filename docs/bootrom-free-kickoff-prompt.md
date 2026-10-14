# Kickoff prompt: boot without the S5L8720 bootrom

Paste this into a new conversation (in ~/Documents/qemu-ios).

---

Skeuo: make the iPod touch 2G emulator boot without Apple's S5L8720 bootrom (SecureROM, iBoot-240.4).

Why
- Every Skeuo user has to find and supply a 64 KB dump of Apple's bootrom (the app's first-run step, the pipeline's
  `--bootrom`/`SKEUO_BOOTROM`, the machine's `bootrom=` option). It can't be shipped, and it's the one thing a user
  can't get from Apple. Removing it is the biggest usability gain left.
- Everything else the emulator runs comes from the IPSW, which the app downloads from Apple: LLB, iBoot, iBSS, iBEC,
  the device tree, the kernelcache. The GID-decrypted keys for the supported firmware are already in the emulator
  (the KBAG table in hw/arm/ipod_touch_aes.c).

Context to read first
- Memory notes: it2g-aes-model, it2g-restore-chain, it2g-usb-link, it2g-unknown1-miu, it2g-fmss-nand-internals,
  it2g-ios-2.2, it2g-ios-3.0, it2g-ios-4.0, it2g-snapshots, feedback-use-ghidra-mcp,
  feedback-ask-for-ghidra-binaries, feedback-short-verification.
- hw/arm/ipod_touch_2g.c: the machine maps the bootrom file as "vrom" at 0x0 (lines ~140) and starts there; the
  `dfu=on` option holds the force-DFU GPIO.
- The pipeline (~/Documents/skeuo/pipeline): `restore.py` boots the emulator in DFU mode and uploads iBSS through the
  bootrom's DFU (usb/dfu.py), then iBEC, ramdisk and kernel through iBSS/iBEC's recovery mode. `emulator.py` passes
  `bootrom=`. The app (~/Documents/skeuo/app) has a first-run bootrom step and copies it to
  ~/Library/Application Support/Skeuo/bootrom.bin.

What the bootrom does for us today, and what must replace it
1. Normal boot: it reads LLB from the NOR, checks its IMG3 signature, decrypts it with the GID key (through the AES
   engine) and runs it; LLB then loads iBoot from the NOR. To replace: load LLB (or even iBoot directly) ourselves.
2. Restore: with the force-DFU GPIO it is a USB DFU device that receives iBSS. To replace: start iBSS directly,
   without DFU (e.g. a machine option with the iBSS image that the pipeline passes, instead of the DFU upload), or
   emulate the bootrom's DFU at the USB model level (more work, less value).

Approach I'd like evaluated (decide with me before building)
- (a) High-level emulation in the machine: a `boot=` option (nor | image) where the machine parses the IMG3 itself
  (LLB from the NOR, or a given iBSS file), decrypts it with the existing GID key table, places it where the bootrom
  would (find the load address and the CPU/SoC state the bootrom leaves: MMU off, which clocks/PLLs, SRAM, the
  vector remap, registers LLB/iBSS read, e.g. the boot source, chip ID/security bits, a boot nonce) and starts the
  CPU there. The signature check can be skipped.
- (b) A small open-source replacement ROM (ARM assembly/C, our own code) that does the same on the emulated hardware
  through the NOR/SPI and AES models. Closer to real hardware, more work.
- Keep `bootrom=` working as an option (useful for checking behaviour against the real thing).

Steps
1. Find what LLB and iBSS (2.1.1 first; then 2.2, 3.0, 4.0) expect from the bootrom: do they call into the ROM
   (function pointers, jumps to 0x0…0x20000), read ROM data, or rely on SRAM/register state it leaves? Use the
   Ghidra MCP (ask me to open LLB/iBSS/the bootrom in Ghidra; don't search the disk for binaries). Trace with lldb
   or QEMU's `-d` where useful.
2. Propose (a) or (b) with what you found, and agree with me.
3. Implement on qemu-ios `skeuo` (QEMU commit style: "hw/arm: ..."). Normal boot of an existing bundle (2.1.1)
   without the bootrom first, then the restore path (iBSS without DFU), then the other versions.
4. Saved states: the machine's options are part of the fingerprint; decide whether a bootrom-less boot changes the
   VMState (e.g. the vrom region) and keep resume working for new bundles.
5. Pipeline (~/Documents/skeuo, commit style "Boot without the bootrom", plus "Move the emulator to ..." submodule
   bumps): drop the bootrom requirement from `restore`, `run` and `serve` (keep `--bootrom` optional), restore via
   iBSS without DFU.
6. App: remove the first-run bootrom step (keep a way to use one in Settings if (a) keeps `bootrom=`), update
   docs/app-plan.md and the READMEs.

Constraints
- Keep verification short: 2.1.1 boots in seconds; one bundle, no multi-minute loops. I test UI behaviour myself.
- Don't push. Ask before installing toolchains.
- Use Ghidra through its MCP; rename/annotate what you reverse there (methods in their class namespaces).
- Note in memory what the bootrom leaves behind and how the new boot path works.

---

Notes for the reader (not part of the prompt)
- Feasible: nothing after the bootrom needs Apple's ROM code as far as we know; LLB, iBoot and iBSS are in the IPSW,
  and the emulator already decrypts GID-encrypted images through its key table. The open questions are what state
  LLB/iBSS expect the bootrom to leave and whether they call back into it; step 1 answers those.
- This also removes the IMG3 signature check of the first stage, which matters for nothing in an emulator.
