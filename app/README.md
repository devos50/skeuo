# Skeuo app

The desktop app: a Tauri 2 shell (Rust, `src-tauri/`) around a Svelte 5 front end (`src/`). It runs the pipeline
daemon (`skeuo serve`, see `../pipeline`) and asks it for everything about the devices; it never touches a bundle
itself. Each running device gets a window that draws its screen from QEMU's VNC WebSocket.

```bash
npm install
SKEUO_QEMU=~/Documents/qemu-ios/build/qemu-system-arm npm run tauri dev
```

Development needs Node and current Rust (Tauri 2.12 needs Rust 1.90 or later). A debug build (`npm run tauri dev`)
starts `python3 -m skeuo serve` from `../pipeline`, and QEMU is found as the pipeline finds it (`SKEUO_QEMU`, or the
emulator submodule's build directory). A release build runs the Python, pipeline and QEMU in its resources instead
(see `../packaging/macos`, which builds the DMG). `SKEUO_PYTHON`, `SKEUO_PIPELINE` and `SKEUO_QEMU` override each.

## What it does (milestones 3 to 6)

- **Data:** the app keeps its files in `~/Library/Application Support/Skeuo` (the platform's data directory): the
  pipeline's IPSW cache is `ipsw/` there, and the app's settings are `settings.json` (for now only the library,
  default `~/Skeuo`). There is no first-run step: the emulator starts the firmware itself, so Apple's bootrom isn't
  needed.
- **Gallery:** every device in the library with its thumbnail, name, version and state. Double-click starts or
  resumes a device; while one runs, the others can't start. The context menu has Resume/Start, Restart (Cold Boot),
  Suspend, Power Off (with a confirmation), Edit, Show in Finder and Move to Trash. The grid scrolls.
- **Edit:** name, thumbnail (any picture, cropped to the screen, or Reset to the drawn lock screen) and settings
  (Wi-Fi, audio, libimobiledevice access), plus the device's details (version, activation, serial, UDID). Wi-Fi and
  audio change the emulator's command line, so they can't change while the device runs, and changing them on a
  suspended device asks first, since it discards the saved state.
- **Settings** (the gear): the library folder (changing it restarts the daemon on the new one; not while a device
  runs), the firmware cache (download, resume or delete each version's IPSW), and an optional boot ROM. Choosing a
  copy of the S5L8720 SecureROM (iBoot-240.4, checked by SHA-256, kept as `bootrom.bin` in the data directory) makes
  devices boot through it, to compare with the real thing; Remove goes back to booting directly. Both restart the
  daemon, so not while a device runs. The bootrom is Apple's code, so it is never part of the repository or the app.
- **New device:** the "+" card or toolbar button opens a dialog: device type (only the iPod touch 2G for now),
  name, version (the IPSW comes from Apple's servers if it isn't cached; 3.0 needs a local IPSW, as does any
  version through Advanced), activation (Skeuo's own, or a device certificate from Apple), and under Advanced
  Wi-Fi, audio, libimobiledevice access and a NOR images folder. The card appears at once and shows the download
  and restore progress; Cancel Download in its menu stops a download (the restore can't be stopped). A restore
  that fails leaves an "Incomplete" card with its logs, which Move to Trash removes.
- **Device window:** the screen in a device frame we draw ourselves (`DeviceFrame.svelte`), whose home, sleep and
  volume buttons work. Fit to the window, or 1× (320 points wide) and 2×, which size the window to the device.
  Rotate left/right turns the whole device and tells the emulator's accelerometer (the daemon's `orientation`
  request), so apps that rotate follow; touch is mapped back through the rotation, and the window turns with it.
  Screenshots (as the screen is seen, rotated) go to the Desktop. The ⋯ menu has Take Screenshot, Restart and Power
  Off. A USB indicator shows while libimobiledevice sees the device. Every 5 s, and when the window closes, the last
  frame with the screen lit becomes the gallery thumbnail. Closing the window suspends the device. Quitting Skeuo
  suspends the running device too (the daemon does that when its stdin closes).
- **Shortcuts** (as in Apple's Simulator): ⇧⌘H Home, ⌘L Sleep/Wake, ⌘↑/⌘↓ Volume, ⌘←/⌘→ Rotate, ⌘S Screenshot,
  ⌘1/⌘2/⌘3 Actual size/Double size/Fit. H, P, - and = hold Home, Sleep/Wake and Volume for as long as they are down
  (hold P for "slide to power off").

## Layout

- `src-tauri/src/lib.rs`: the commands the UI calls (`status`, `import_bootrom`, `remove_bootrom`, `rpc`, `start_device`,
  `restart_device`, `set_library`, `thumbnail`, `reveal`, `pick_path`: native file dialogs, since the pipeline needs paths,
  `save_screenshot`), the device windows (closed when their device stops), and shutting the daemon down on exit.
- `src-tauri/src/daemon.rs`: the daemon process: requests by id, events forwarded to every window as `daemon`.
- `src/lib/daemon.svelte.js`: the device list as reactive state, kept current from the daemon's events.
- `src/lib/rfb.js`: the RFB client from the spike (`spike/`).
- `src/Gallery.svelte`, `DeviceCard.svelte`, `CreateDialog.svelte`, `DeviceFrame.svelte`, `EditDialog.svelte`, `SettingsDialog.svelte`, `DeviceWindow.svelte`, `Menu.svelte`,
  `Confirm.svelte`.
