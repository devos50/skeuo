# Skeuo pipeline

Creates and runs virtual devices from IPSWs. A device is a *bundle*: a directory with the device's disk, NOR and a
`device.json` (see `skeuo/bundle.py`). Everything iOS writes stays in the bundle, so a device keeps its state between
runs.

```bash
export SKEUO_QEMU=/path/to/qemu-system-arm   # default: ../emulator/build/qemu-system-arm

python3 -m skeuo download 2.1.1          # from Apple, into the IPSW cache
python3 -m skeuo restore ~/Library/Application\ Support/Skeuo/ipsw/iPod2,1_2.1.1_5F138_Restore.ipsw ~/Skeuo/my-ipod
python3 -m skeuo run ~/Skeuo/my-ipod
```

Run the commands from this directory (or put it on `PYTHONPATH`). Only the Python standard library is needed.

Apple's S5L8720 bootrom isn't needed: the emulator starts the first boot stage itself, the way the bootrom would (LLB
from the NOR, or iBSS for a restore). To boot through a bootrom dump instead, for comparing with the real thing, pass
`--bootrom` or set `SKEUO_BOOTROM`; a restore then goes through the bootrom's DFU mode.

## Downloading IPSWs

`download <version>` fetches a restore IPSW from Apple's servers into the IPSW cache (`~/Library/Application
Support/Skeuo/ipsw` on macOS, `$XDG_DATA_HOME/Skeuo/ipsw` on Linux, `%LOCALAPPDATA%\Skeuo\ipsw` on Windows, or
`$SKEUO_IPSW_CACHE`); `download --list` shows what is there. An interrupted download resumes where it stopped. A
finished one is checked against the size and MD5 (the ETag) that Apple's server reports, and against a known SHA-1:
Apple's version catalog no longer lists checksums for these old versions (`skeuo/download.py`).

Apple still serves 2.1.1, 2.2 and 4.0 for the iPod touch 2G. iPhone OS 3.0 was a paid upgrade for the iPod touch,
sold through the iTunes Store, and its IPSW was never on a public URL, so a 3.0 device needs an IPSW you have.

## What `restore` does

1. Creates a factory-new device with its own identity: a random serial number and MAC addresses (`identity.py`), an
   empty disk image, which the emulator presents as a formatted, empty NAND (`nand.py`), and a NOR with only the
   factory data, i.e. syscfg and NVRAM (`nor.py`).
2. Starts iBSS in the emulator (over DFU with `--bootrom`) and restores like iTunes: iBSS loads iBEC, iBEC the restore
   ramdisk and kernelcache, then `restored` partitions the NAND, writes the root filesystem it gets through asr and
   flashes the NOR images from the IPSW (`restore.py`, `restored.py`). This takes about a minute.
3. Prepares the restored filesystems for the emulator (`prepare.py`): SpringBoard draws in software
   (`LK_ENABLE_MBX2D=0`), and the device is activated (`activation.py`).

The bundle keeps the disk as `disk.img`, a sparse raw disk image that macOS can mount
(`hdiutil attach -imagekey diskimage-class=CRawDiskImage disk.img`). While the emulator runs, the NAND pages iOS
writes go to `overlay/`; they are folded into `disk.img` when it powers off, or before the next start if it crashed
(not while it is suspended, see below).
Bundles from before this format (one file per NAND page in `nand/`) are converted when they are opened.

## Names, settings and thumbnails

`device.json` also holds the name the app shows (`"name"`, by default "iPod touch (iPhone OS 2.1.1)"; the directory
keeps its name) and the device's `"settings"`: `wifi`, `audio` and `usbmuxd` (libimobiledevice access), all on by
default. Wi-Fi and audio change QEMU's command line, so they can't change while a device is suspended without
discarding its state. The app keeps the gallery picture in `<bundle>/thumbnail.png`. Bundles from before these
existed get the defaults when they are read. `restore --name` names a new device.

## Running, suspending and resuming

`run` boots the bundle with a window (or `--headless`) and serves it to libimobiledevice through a built-in usbmuxd
(`USBMUXD_SOCKET_ADDRESS=127.0.0.1:27015`). Only one `run` can use a bundle at a time (`<bundle>/.lock`).

Stopping a run suspends the device, like closing a laptop: Ctrl-C, SIGTERM, closing the window or quitting QEMU
(Cmd-Q) saves the machine to `<bundle>/suspended.state` (~80 MB), and the next `run` resumes it within a second,
on the screen it was on. The host sees the device unplugged and plugged in again, so libimobiledevice answers about
2 s later.

```bash
python3 -m skeuo run ~/Skeuo/my-ipod                 # boots, or resumes a suspended device
python3 -m skeuo run --power-off ~/Skeuo/my-ipod     # stopping powers off instead of suspending
python3 -m skeuo run --cold-boot ~/Skeuo/my-ipod     # discards a saved state and boots
python3 -m skeuo power-off ~/Skeuo/my-ipod           # discards a saved state
```

The saved state holds RAM, the CPU, every device and the NOR, but not the NAND. The iOS FTL keeps the NAND's
physical layout in RAM, so a state is only valid with `disk.img` and `overlay/` exactly as they were when it was
saved: while a device is suspended, its overlay is not folded into the disk. Powering off (or a cold boot) is when
the overlay is folded again. `device.json` records the state under `"suspended"`: when it was saved, the device's
clock at that moment, and the fingerprint of the emulator it belongs to (QEMU's SHA-256 and its arguments without
paths, ports, window and clock). A state is only loaded by the same QEMU build with the same arguments, including
extra QEMU arguments after `--`; otherwise `run` refuses and asks to run it with those or discard it.

Resuming consumes the state: once QEMU has loaded it, the record and the file are removed. If QEMU crashes or is
killed afterwards, the next `run` folds the overlay and boots cold, as after a power loss. A suspend that did not
finish leaves no record, so its state file is ignored and removed.

The guest keeps its calendar in RAM, so after a resume it continues from the time it was suspended at. A device whose clock starts at a fixed date (see Activation) resumes its clock at the time it was suspended, so it
doesn't jump back to that date, unless that is less than a day before its certificate expires.

## The daemon for the app

`serve` runs the pipeline as a daemon for the Skeuo app. It speaks JSON lines over stdin and stdout: requests with
an id (`list`, `device_types`, `ipsws`, `download_ipsw`, `delete_ipsw`, `create`, `run`, `suspend`, `power_off`, `rename`, `update_settings`,
`remove`, `set_thumbnail`, `screenshot`, `orientation`, `cancel`, `shutdown`), a response for each, and events in between
(`state`, `device`, `removed`, `progress`, `usb`, `log`, `warning`). The protocol is described at the top of
`skeuo/serve.py`.

```bash
python3 -m skeuo serve --library ~/Skeuo
{"id": 1, "method": "run", "params": {"device": "my-ipod"}}
```

The daemon owns the library (`~/Skeuo` by default): a device is a bundle directory in it, and its id is the
directory's name. Only one device runs at a time. It runs without a window: QEMU serves the screen and takes touch
and button input over VNC on 127.0.0.1, also as a WebSocket, on free ports that the `running` state event reports;
there is no VNC password. The window, the VNC server and their ports aren't part of a saved state's fingerprint,
so a device suspended by `run` resumes in the app and the other way round. `remove` moves a bundle to the trash.
When stdin closes, because the app quit, the daemon suspends the running device and exits.

## Activation

Skeuo activates devices itself. lockdownd trusts an activation record when it is signed by the key of
`/System/Library/Lockdown/iPhoneActivation.pem` and its device certificate chains to `iPhoneDeviceCA.pem`. Both are
plain files on the root filesystem, so Skeuo replaces them with its own activation authority
(`skeuo/activation/`, made by `tools/make_activation_ca.py`) and writes a record it signed for the device's UDID.
The UDID is the USB serial number the device reports during the restore. Its keys mean nothing to real devices.

From iPhone OS 3.0 on, Security pins the root of the device certificate's chain to Apple's, so Skeuo's own device
certificate no longer verifies. For 3.0 and 4.0, `prepare` therefore patches lockdownd: `verify_activation_record`
treats the device certificate as verified, while the account token still has to carry Skeuo's signature. The patched
lockdownd no longer matches its code signature, so `run` boots these devices with code signing enforcement off
(`amfi=0xff cs_enforcement_disable=1`; the kernel honours them because the emulated chip is a non-production one).
That also lets unsigned and modified binaries run.

Without the patch, lockdownd doesn't check that the device certificate belongs to the device, so a certificate Apple
issued to any device works too, next to Skeuo's signed account token. Pass one to `restore`, as a PEM file or as the
activation record of a device Apple activated (`/private/var/root/Library/Lockdown/activation_records/pod_record.plist`),
and lockdownd stays unpatched:

```bash
python3 -m skeuo restore iPod2,1_4.0_8A293_Restore.ipsw ~/Skeuo/ipod-4.0 --device-certificate pod_record.plist
```

The certificate is only accepted within its validity period, so when it has expired, `run` starts the device's
clock (QEMU `-rtc base=`) a month before its expiry date.

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

- Preparing the filesystems uses `hdiutil`, so `restore` runs on macOS only for now.
- Activation is verified on 2.1.1 and 2.2 (Skeuo's certificates), and on 3.0 and 4.0 (patched lockdownd; 4.0 also with
  a device certificate from Apple). Bundles restored before the lockdownd patch stay as they were: 3.0 Unactivated
  but usable, 4.0 on the "Connect to iTunes" screen.
- After a resume, the guest's calendar lags by the time the device was suspended (until it reboots).
- 2.2's AMFI doesn't report the boot arguments (3.0's and 4.0's log that enforcement is off); whether unsigned
  binaries run on 2.2 is untested.
