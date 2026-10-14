# Skeuo app

The desktop app: a Tauri 2 shell (Rust, `src-tauri/`) around a Svelte 5 front end (`src/`). It runs the pipeline
daemon (`skeuo serve`, see `../pipeline`) and asks it for everything about the devices; it never touches a bundle
itself. Each running device gets a window that draws its screen from QEMU's VNC WebSocket.

```bash
npm install
SKEUO_QEMU=~/Documents/qemu-ios/build/qemu-system-arm SKEUO_BOOTROM=/path/to/bootrom npm run tauri dev
```

Development needs Node and current Rust (Tauri 2.12 needs Rust 1.90 or later). The app starts `python3 -m skeuo serve`
from `../pipeline`; set `SKEUO_PYTHON` or `SKEUO_PIPELINE` to use others. QEMU is found as the pipeline finds it
(`SKEUO_QEMU`, or the emulator submodule's build directory).

## What it does so far (milestones 3 and 4)

- **First run:** asks for the S5L8720 bootrom (SecureROM iBoot-240.4, 64 KB), checks its SHA-256 and keeps a copy
  as `bootrom.bin` in `~/Library/Application Support/Skeuo` (the platform's data directory). The pipeline's IPSW
  cache is `ipsw/` there, and the app's settings are `settings.json` (for now only the library, default `~/Skeuo`).
  When `SKEUO_BOOTROM` names a bootrom (as for the pipeline), the app imports that one at startup, with the same
  check, and skips this step. The bootrom is Apple's code, so it is never part of the repository or the app bundle.
- **Gallery:** every device in the library with its thumbnail, name, version and state. Double-click starts or
  resumes a device; while one runs, the others can't start. The context menu has Resume/Start, Restart (Cold Boot),
  Suspend, Power Off (with a confirmation), Show in Finder and Move to Trash. The grid scrolls.
- **New device:** the "+" card or toolbar button opens a dialog: device type (only the iPod touch 2G for now),
  name, version (the IPSW comes from Apple's servers if it isn't cached; 3.0 needs a local IPSW, as does any
  version through Advanced), activation (Skeuo's own, or a device certificate from Apple), and under Advanced
  Wi-Fi, audio, libimobiledevice access and a NOR images folder. The card appears at once and shows the download
  and restore progress; Cancel Download in its menu stops a download (the restore can't be stopped). A restore
  that fails leaves an "Incomplete" card with its logs, which Move to Trash removes.
- **Device window:** the screen, scaled to the window; touch with the mouse; Home, Sleep/Wake, Volume and Rotate as
  toolbar buttons and on the keys H, P, -, = and R. Every 10 s, and when the window closes, the last frame with the
  screen lit becomes the gallery thumbnail. Closing the window suspends the device. Quitting Skeuo suspends the
  running device too (the daemon does that when its stdin closes).

## Layout

- `src-tauri/src/lib.rs`: the commands the UI calls (`status`, `import_bootrom`, `rpc`, `start_device`,
  `thumbnail`, `reveal`, `pick_path`: native file dialogs, since the pipeline needs paths), the device windows (closed when their device stops), and shutting the daemon down on exit.
- `src-tauri/src/daemon.rs`: the daemon process: requests by id, events forwarded to every window as `daemon`.
- `src/lib/daemon.svelte.js`: the device list as reactive state, kept current from the daemon's events.
- `src/lib/rfb.js`: the RFB client from the spike (`spike/`).
- `src/Gallery.svelte`, `DeviceCard.svelte`, `CreateDialog.svelte`, `DeviceWindow.svelte`, `FirstRun.svelte`, `Menu.svelte`,
  `Confirm.svelte`.
