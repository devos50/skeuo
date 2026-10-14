# Display/input spike (milestone 2)

A bare page that shows a running device and sends it touches and button presses, to check the screen-over-VNC
design before building the app (see `docs/app-plan.md`).

- `web/rfb.js`: a small RFB client of our own (~200 lines, no dependencies) for QEMU's VNC WebSocket: no
  authentication, raw and CopyRect encodings, QEMU's absolute pointer, and QEMU's extended key events, which carry
  scancodes, so the host's keyboard layout doesn't matter.
- `web/index.html`: the screen, buttons (Home, Power, Volume, Rotate, Mute, also on the keys H, P, =, -, R, M by
  physical key), 1×/1.5×/2× scaling, and measurements (updates per second, data rate, update latency, touch to
  next frame).
- `spike.py`: starts `skeuo serve`, runs a device and serves the page on a local port (ES modules don't load from
  `file://`). Ctrl-C suspends the device. It prints QEMU's CPU use every 5 s.
- `tauri/`: the same page in a Tauri 2 window. It starts `skeuo serve`, runs the device, passes the WebSocket port
  to the page in an init script, and closing the window suspends the device. Build it with plain `cargo build`
  (no Tauri CLI). `rust-version` is 1.85 to match the installed Rust; Cargo.lock was resolved with
  `CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS=fallback`, which picks Tauri 2.11 (2.12 needs Rust 1.90).

```bash
export SKEUO_QEMU=~/Documents/qemu-ios/build/qemu-system-arm SKEUO_BOOTROM=/path/to/bootrom
python3 spike.py my-ipod [--cold-boot]          # then open the URL it prints
cd tauri && cargo run -- my-ipod
```

## Findings (2026-10-14, iPhone OS 2.1.1, M-series Mac)

- **Screen:** works, including the dimming before auto-lock and sleep (the LCD model scales by the backlight).
  Updates come when the guest draws: 10 per second for the stopwatch (about 130 KB/s), 12 to 18 during
  SpringBoard animations (up to 5 MB/s, since raw rectangles are up to 600 KB). On loopback that is nothing, and
  no compression is needed.
- **Touch:** taps land on what they point at (icons, the dialog's Dismiss button, the stopwatch's Start), so the
  fingertip offset in the multitouch model holds with VNC's absolute pointer as it does with the SDL window. A
  drag at a realistic speed unlocks the lock screen. Touch to next frame: 50 to 120 ms, most of it the guest
  responding.
- **Buttons:** Home, Power (sleep and wake), Volume (the HUD shows), Rotate and Mute work as key events. A press
  must last a while: a key released at once (as automation sends it) can be over before iOS reads the button GPIO,
  so the page holds every button at least 100 ms.
- **CPU:** QEMU uses one full core whether or not a VNC client is connected and whether or not the screen changes
  (about 102% in every case): that is the emulated CPU, which never idles, not the VNC server. The browser side is
  negligible: in the Tauri window the WebKit processes stay under 0.5% each.
- **Tauri (macOS, WKWebView):** the page from `tauri://localhost` connects to `ws://127.0.0.1:<port>` with the
  CSP off and no other configuration (WebKit's networking process holds the WebSocket to QEMU). Whether it draws
  and takes input as in the browser still has to be checked by eye. Not tried yet: WebView2 (Windows) and WebKitGTK (Linux).
