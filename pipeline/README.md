# Skeuo pipeline

Creates and runs virtual devices from IPSWs. A device is a *bundle*: a directory with the device's disk, NOR and a
`device.json` (see `skeuo/bundle.py`). Everything iOS writes stays in the bundle, so a device keeps its state between
runs.

```bash
export SKEUO_BOOTROM=/path/to/s5l8720-bootrom.bin
export SKEUO_QEMU=/path/to/qemu-system-arm   # default: ../emulator/build/qemu-system-arm

python3 -m skeuo restore iPod2,1_2.1.1_5F138_Restore.ipsw ~/Skeuo/my-ipod
python3 -m skeuo run ~/Skeuo/my-ipod
```

Run the commands from this directory (or put it on `PYTHONPATH`). Only the Python standard library is needed.

## What `restore` does

1. Creates a factory-new device with its own identity: a random serial number and MAC addresses (`identity.py`), an
   empty disk image, which the emulator presents as a formatted, empty NAND (`nand.py`), and a NOR with only the
   factory data, i.e. syscfg and NVRAM (`nor.py`).
2. Boots the emulator in DFU mode and restores like iTunes: iBSS over DFU, iBEC, the restore ramdisk and kernelcache,
   then `restored` partitions the NAND, writes the root filesystem it gets through asr and flashes the NOR images
   from the IPSW (`restore.py`, `restored.py`). This takes about a minute.
3. Prepares the restored filesystems for the emulator (`prepare.py`): SpringBoard draws in software
   (`LK_ENABLE_MBX2D=0`), and the device is activated (`activation.py`).

The bundle keeps the disk as `disk.img`, a sparse raw disk image that macOS can mount
(`hdiutil attach -imagekey diskimage-class=CRawDiskImage disk.img`). While the emulator runs, the NAND pages iOS
writes go to `overlay/`; they are folded into `disk.img` when it stops, or before the next start if it crashed.
Bundles from before this format (one file per NAND page in `nand/`) are converted when they are opened.

`run` boots the bundle with a window and serves it to libimobiledevice through a built-in usbmuxd
(`USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015`).

## Activation

Skeuo activates devices itself. lockdownd trusts an activation record when it is signed by the key of
`/System/Library/Lockdown/iPhoneActivation.pem` and its device certificate chains to `iPhoneDeviceCA.pem`. Both are
plain files on the root filesystem, so Skeuo replaces them with its own activation authority
(`skeuo/activation/`, made by `tools/make_activation_ca.py`) and writes a record it signed for the device's UDID.
The UDID is the USB serial number the device reports during the restore. Its keys mean nothing to real devices.

## Supported firmware

iPod touch 2G (`iPod2,1`): iPhone OS 2.1.1 (5F138), 2.2 (5G77a), 3.0 (7A341) and iOS 4.0 (8A293). Each needs the image keys in the
emulator's GID key table, and a NAND formatted for the epoch of its NAND driver (`NAND_EPOCHS` in `skeuo/ipsw.py`;
2.1.1 is epoch 1, 2.2 epoch 2, 3.0 epoch 3, 4.0 epoch 4). A bundle is one device with one firmware, so to switch between versions, restore one bundle per
version and run the one you want:

```bash
python3 -m skeuo restore iPod2,1_2.2_5G77a_Restore.ipsw ~/Skeuo/ipod-2.2
python3 -m skeuo run ~/Skeuo/ipod-2.2      # or ~/Skeuo/ipod-2.1.1, ~/Skeuo/ipod-3.0, ~/Skeuo/ipod-4.0
```

## Limitations

- The bootrom is Apple's code, so it is not included.
- Preparing the filesystems uses `hdiutil`, so `restore` runs on macOS only for now.
- Activation is verified on 2.1.1 and 2.2. 3.0 stays Unactivated: its lockdownd only accepts device certificates whose
  chain ends at Apple's root or factory CA (Security pins their SHA-1), so replacing the certificate files doesn't help.
  An unactivated iPod is still usable on 3.0, because lockdownd only enables the brick state on devices with a
  baseband. 4.0 has the same certificate check but enables the brick state on the iPod too, so it boots to the
  "Connect to iTunes" activation screen.
