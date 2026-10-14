# Skeuo app: plan

Status: planned (2026-10-13), decisions taken 2026-10-14, not started. Roadmap step 4 (app shell), after IPSW → bundle automation (done) and
suspend/resume (done). Packaging/CI (step 5) gets its own plan once the toolkit is settled.

## Vision (from Martijn, 2026-10-13)

- Cross-platform, modern-looking app. The model is a VM manager (think UTM / Parallels / VirtualBox).
- Opening Skeuo shows a **gallery of your emulators**, each with a **thumbnail** of its screen and a **name**.
- **Creating a new emulator is quick:** a short dialog with a few settings (iOS version first of all), then it is built.
- Emulators can be **renamed/edited and removed**.
- The screen reaches the app over a channel (option (b)): QEMU runs without its own window and the app draws the
  screen and sends input itself. QEMU's SDL window and an embedded QEMU library are out.

## Decisions (2026-10-14)

- Toolkit: **Tauri 2**.
- The app **downloads IPSWs from Apple's servers** itself (the user doesn't have to supply one).
- **One device runs at a time.** The app can't start a second one while one is running; there is a single usbmuxd bridge.
- **No VNC password**; the server listens on 127.0.0.1 only.
- The guest clock lagging after a resume stays as it is for now.

## Architecture

```
┌──────────────── Skeuo app (Tauri 2: Rust core + web UI) ───────────────┐
│ gallery · create dialog · device windows · settings                   │
│        │ JSON-lines RPC (stdio)            │ WebSocket (RFB/VNC)       │
└────────┼───────────────────────────────────┼──────────────────────────┘
         ▼                                   ▼
  skeuo pipeline daemon (Python)     QEMU -display none -vnc …,websocket=…
  bundles, restore, run/suspend,      screen out, touch + buttons in
  QMP, usbmuxd bridge                 (audio straight to the host)
```

- **The pipeline owns the bundles.** The app never edits a bundle itself; it asks the pipeline (`skeuo serve`) to
  list, create, run, suspend, power off, rename, delete. That keeps the NAND/fold/state rules (`bundle.py`) in one place.
- **Screen and input over QEMU's VNC server with WebSocket** (`-vnc 127.0.0.1:…,websocket=<port>`). Works on every
  platform with no emulator changes, and a web UI can talk to it directly:
  - Screen: the LCD model already scales pixels by the backlight, so dimming and sleep show correctly.
  - Touch: the LCD model takes absolute pointer and left-button events (`ipod_touch_lcd.c`), and QEMU's VNC server sends
    absolute events when the device wants them.
  - Buttons: key events, as today (`h` home, `p` power, `+`/`-` volume, `r` rotate, `m` host mute,
    `ipod_touch_2g.c`). The app shows buttons and keyboard shortcuts and sends the keysyms.
  - Later, if needed: a shared-memory framebuffer (lower CPU, no encoding), multi-touch (pinch) via QEMU's
    multi-touch input events (`INPUT_EVENT_KIND_MTT`, QMP `input-send-event`) once the multitouch model takes
    more than one contact.
- **Toolkit: Tauri 2** (Rust core, web front end in Svelte or React, styled to look like a native modern app).
  It's small and cross-platform, and the web UI can connect to QEMU's WebSocket. Risk to check in the spike:
  WebKitGTK on Linux.
- **Python ships with the app** (python-build-standalone, ~30 MB), and the pipeline stays stdlib-only. Porting the
  pipeline to Rust stays possible later; the RPC boundary makes it a drop-in.
- **One device at a time**, so the usbmuxd bridge from `skeuo run` stays as it is (one device per bridge), owned by
  the daemon.
- **IPSW download in the pipeline** (`skeuo download` / an RPC request): find the iPod2,1 restore IPSW URLs on Apple's
  servers, download with resume and progress into a cache in the app's data directory, and check the checksum Apple
  publishes. The app shows the versions it can download next to the ones already in the cache.

## Data model

Bundles stay where they are (default library `~/Skeuo`, configurable). New in `device.json`:

- `name`: shown in the gallery (default: "iPod touch (iOS 4.0)"); the directory name stays as it is.
- `settings`: options picked at creation, editable later (see below).
- `thumbnail.png` in the bundle: the last lit frame the app showed (taken from the client, because the screen
  may be asleep at suspend time). If there is none yet, use the firmware's default lock screen artwork, which we draw ourselves.

The app's own settings (library path, bootrom location, IPSW cache) live in the platform's config directory.

## Screens

1. **First run:** pick the S5L8720 bootrom (it can't be shipped; check its SHA-256 and copy it to the app's data
   directory).
2. **Gallery:** a grid of cards with the thumbnail, name, iOS version and a state badge (running / suspended / off).
   Double-click to start or resume (only one at a time: while one runs, the others can't start); a context menu with Edit, Power off, Show in Finder and Remove. A "+" card creates a new one.
3. **New emulator dialog:**
   - Name
   - iOS version: 2.1.1, 2.2, 3.0 or 4.0. The IPSW is downloaded from Apple when it isn't in the cache yet
     (with progress; picking a local file is an advanced option).
   - Activation: Skeuo's own (default) or an Apple device certificate (`--device-certificate`).
   - Advanced (collapsed): Wi-Fi on/off, audio on/off, libimobiledevice access on/off, NOR images override.
   - The restore runs in the background with a progress bar (the restore steps are already logged:
     DFU → iBEC → ramdisk → asr → NOR → prepare), and the card appears straight away with a "creating" state.
4. **Device window:** the screen in a simple drawn device frame (our own artwork, not Apple's), resizable and
   scalable 1×/2×. A toolbar or side buttons for home, power, volume, rotate and screenshot. Status: running,
   "connected to libimobiledevice", and a suspend indicator. Closing the window suspends (as `run` does now);
   the menu has Power off, Restart and Cold boot.
5. **Edit:** rename and thumbnail are always editable. Settings that change the QEMU command line (Wi-Fi,
   machine options) only apply when the device is off. If it is suspended, ask: "this discards the
   suspended state".
6. **Remove:** confirm, then move the bundle to the trash (no hard delete).

## Milestones

1. **Pipeline API.** Add `skeuo serve`: JSON-lines RPC over stdio with requests (list, create, run, suspend,
   power_off, rename, update_settings, remove, set_thumbnail) and events (progress, state changes, device attached).
   Add `name`/`settings` to device.json, and make `run` usable without a window (`-display none -vnc …`) with the
   VNC/WebSocket port reported in an event. This can be tested without any GUI.
2. **Display/input spike.** A bare HTML page with an RFB client (noVNC, or a small one of our own; RFB with raw/ZRLE
   encoding at 320×480 is simple) against a running device. Measure latency and CPU, check touch accuracy
   (the fingertip offset in `ipod_touch_multitouch.c` must still hold) and the buttons. Try it in Tauri's webviews
   (WebKit on macOS, WebView2, WebKitGTK).
3. **App skeleton.** A Tauri project in `app/`: it starts the daemon, with the gallery, the first-run bootrom step and
   start/suspend.
4. **Create flow.** The new-emulator dialog, the IPSW download from Apple, and the background restore with progress.
5. **Device window polish.** Frame, scaling, rotation (rotate the frame along with the accelerometer), shortcuts,
   screenshots, live thumbnails.
6. **Edit/remove**, settings.

Then packaging: bundle QEMU and its dylibs (glib, pixman, SDL can go, slirp, libpng), Python, code signing and
notarization, and Windows/Linux builds.

## Open questions

- Svelte or React for the front end (pick one in milestone 3).
- How much RAM a device needs (`-m 2G` today; could be smaller).
- Device frame artwork: generic, drawn by us, to avoid Apple's trade dress.
- Later: correct the guest clock after a resume.
