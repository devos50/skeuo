# Skeuo

Run classic iPhone OS on any computer: pick an IPSW, press Restore, and use the device, with its disk kept between sessions.

Skeuo is the product around an emulator. The emulator is a QEMU fork that lives on the
[`skeuo` branch of devos50/qemu-ios](https://github.com/devos50/qemu-ios/tree/skeuo) and is
pinned here as the `emulator/` submodule.

Status: early. The emulator boots the iPod touch 2G (S5L8720, `n72ap`) to SpringBoard, and
`pipeline/` turns an IPSW into a device with one command (see [pipeline/README.md](pipeline/README.md)).
There is no app yet.

## Layout

| Path | Purpose |
|---|---|
| `emulator/` | Submodule: the QEMU fork with the device models |
| `app/` | Cross-platform launcher: device library, screen, hardware buttons, QMP control |
| `pipeline/` | IPSW → device bundle (NOR, NAND, config), via an in-emulator restore |
| `packaging/` | macOS, Windows and Linux installers, signing, auto-update |
| `docs/` | Design notes and user documentation |

## Roadmap

1. Port the emulator onto the latest upstream QEMU as a clean patch series.
2. Automate IPSW → bootable device bundle, and decide how the bootrom and firmware keys are obtained.
3. Snapshots (VMState for every device model) for instant resume.
4. App shell that owns the display and input.
5. Packaging and CI that boots every supported IPSW to SpringBoard.

## Firmware

Skeuo ships no Apple code. Users supply their own IPSW, which the app can fetch straight from
Apple's servers.
