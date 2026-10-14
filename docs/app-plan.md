# Skeuo app: plan

Status: planned (2026-10-13), decisions taken 2026-10-14. Milestones 1 (pipeline API), 2 (display/input spike) and
3 (app skeleton, Svelte) 4 (create flow), 5 (device window) and 6 (edit, settings) done on 2026-10-14. Next: packaging (roadmap step 5). Roadmap step 4 (app shell), after IPSW → bundle automation (done)
and suspend/resume (done). Packaging/CI (step 5) gets its own plan once the toolkit is settled.

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
- **IPSW download in the pipeline** (`skeuo download` / the `download_ipsw` request): the iPod2,1 restore IPSWs on
  Apple's servers, downloaded with resume and progress into a cache in the app's data directory. The app shows the
  versions it can download next to the ones already in the cache (the `ipsws` request).
  - Apple still serves 2.1.1, 2.2 and 4.0 (`secure-appldnld.apple.com`, checked 2026-10-14). **3.0 isn't
    downloadable:** it was a paid iPod touch upgrade from the iTunes Store and was never on a public URL (Apple's
    catalog only names a `protected://` asset, for 3.1.3). The create dialog needs "pick a local IPSW" for 3.0.
  - Apple's version catalog only lists a FirmwareSHA1 for the versions it still offers (4.1, 4.2.1). What Apple's
    server does publish is the size and an ETag that is the file's MD5; a download is checked against those and a
    pinned SHA-1 (which matches ipsw.me and a copy from 2008).

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

1. **Pipeline API.** *Done 2026-10-14.* Add `skeuo serve`: JSON-lines RPC over stdio with requests (list, create, run, suspend,
   power_off, rename, update_settings, remove, set_thumbnail) and events (progress, state changes, device attached).
   Add `name`/`settings` to device.json, and make `run` usable without a window (`-display none -vnc …`) with the
   VNC/WebSocket port reported in an event. This can be tested without any GUI.
2. **Display/input spike.** *Done 2026-10-14 on macOS, see `app/spike/README.md`.* A bare HTML page with an RFB client (noVNC, or a small one of our own; RFB with raw/ZRLE
   encoding at 320×480 is simple) against a running device. Measure latency and CPU, check touch accuracy
   (the fingertip offset in `ipod_touch_multitouch.c` must still hold) and the buttons. Try it in Tauri's webviews
   (WebKit on macOS, WebView2, WebKitGTK).
3. **App skeleton.** A Tauri project in `app/`: it starts the daemon, with the gallery, the first-run bootrom step and
   start/suspend. *Done 2026-10-14 with Svelte 5, see `app/README.md`.*
4. **Create flow.** The new-emulator dialog, the IPSW download from Apple, and the background restore with progress.
   *Done 2026-10-14. The dialog also has a device-type menu (Martijn's request: more devices later; only the
   iPod touch 2G for now, `DEVICE_TYPES` in ipsw.py and the daemon's `device_types` request). Move to Trash came
   along from milestone 6, for incomplete devices.*
5. **Device window polish.** Frame, scaling, rotation (rotate the frame along with the accelerometer), shortcuts,
   screenshots, live thumbnails. *Done 2026-10-14. The emulator's accelerometer got an `orientation` property
   (qemu-ios b7db9dbad6) that the app sets and reads back after a resume; the frame is CSS, generic.*
6. **Edit/remove**, settings. *Done 2026-10-14: an Edit dialog (name, thumbnail from a picture or reset, settings,
   device details; the "discards the suspended state" question) and app Settings (library folder, bootrom, IPSW
   cache with download/resume/delete).*

Then packaging: bundle QEMU and its dylibs (glib, pixman, SDL can go, slirp, libpng), Python, code signing and
notarization, and Windows/Linux builds.

## What milestones 1 and 2 settled (2026-10-14)

- `skeuo serve` (`pipeline/skeuo/serve.py`): JSON lines, requests answered out of order (each runs in its own thread),
  events between them. Device id = bundle directory name. Besides the planned requests it has `ipsws`,
  `download_ipsw`, `screenshot` (QMP screendump through the daemon, which holds the one QMP connection) and `cancel`
  (for downloads). `create` reports the new device as "creating" first and keeps a failed restore as "incomplete"
  (with its logs) for the app to remove. The run logic moved to `session.py`, shared with `skeuo run`.
- Restore progress comes from the restore's log lines (`RESTORE_PROGRESS` in serve.py). A 2.1.1 create takes about a
  minute: 10 s to boot the ramdisk, 15 s of asr, 20 s more of restored, 15 s of prepare.
- The display: QEMU's VNC WebSocket and a small RFB client of our own (`app/spike/web/rfb.js`, raw + CopyRect) are
  enough; noVNC isn't needed. Button presses need a minimum length (100 ms). VNC costs no measurable CPU; QEMU itself
  uses a full core all the time, because the emulated CPU never idles — worth looking at separately (laptops).
- Tauri: plain `cargo` builds it, no Tauri CLI needed for development. Tauri 2.12 needs Rust 1.90; the installed
  1.85 builds Tauri 2.11 with the MSRV-aware resolver. For the app, update Rust first.
- A 2.1.1 bundle whose activation cache got lost shows "Connect to iTunes" (BrickState) and then sleeps; see the
  activation notes. The old `~/Skeuo/ipod-2.1.1` is in that state.

## What milestone 3 settled (2026-10-14)

- Front end: **Svelte 5** (chosen 2026-10-14) with Vite; no SvelteKit. Rust updated to 1.99, Tauri 2.12, the Tauri CLI
  as a dev dependency (`npm run tauri dev`).
- The Rust side stays thin: it spawns the daemon, relays requests (`rpc`) and events (`daemon`), checks and stores the
  bootrom, opens a window per running device (index.html?device=…&ws=…) and closes it when the device stops.
  Thumbnails reach the gallery as raw bytes through a command, so no asset-protocol scope is needed.
- The bootrom is pinned by SHA-256 (SecureROM iBoot-240.4, 64 KB) and copied to `<data dir>/Skeuo/bootrom.bin`; the
  IPSW cache is `<data dir>/Skeuo/ipsw`, the same default the pipeline uses.
- Closing a device window sends the last lit frame as the thumbnail, then suspends. Quitting the app closes the
  daemon's stdin, which suspends the running device.
- Not yet: the "+" card and create dialog (milestone 4), Edit/Remove (6), a drawn device frame and scaling presets (5).

## Open questions

- WebView2 and WebKitGTK still have to be tried with the spike page.
- How much RAM a device needs (`-m 2G` today; could be smaller).
- Device frame artwork: generic, drawn by us, to avoid Apple's trade dress.
- Later: correct the guest clock after a resume.
