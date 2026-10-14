Skeuo roadmap step 4: build the Skeuo app (Tauri 2), starting with milestones 1 and 2 of the app plan.

Context
- Read ~/Documents/skeuo/docs/app-plan.md first: the vision, the decisions of 2026-10-14, the architecture, the screens and the milestones. Then read the memory notes skeuo-app-vision, skeuo-project, it2g-snapshots, it2g-multitouch-coords and it2g-usb-link.
- Product repo: ~/Documents/skeuo (dirs app/ (empty), pipeline/, packaging/, docs/; emulator/ is a submodule of qemu-ios `skeuo`). Emulator: ~/Documents/qemu-ios, branch `skeuo`, binary ~/Documents/qemu-ios/build/qemu-system-arm.
- Pipeline: ~/Documents/skeuo/pipeline, Python standard library only. `python3 -m skeuo restore|run|power-off`, with SKEUO_QEMU=~/Documents/qemu-ios/build/qemu-system-arm and SKEUO_BOOTROM=~/Documents/ipod_touch_2g_emulation/bootrom_240_4. Bundles: ~/Skeuo/ipod-{2.1.1,2.2,4.0}. ipod-3.0 is damaged; re-restore it if you need it. Relevant code: skeuo/__main__.py (cmd_run: lock, resume/suspend, power-off), skeuo/emulator.py (QEMU command line, QMP client, suspend/resume, fingerprint), skeuo/bundle.py (device.json, saved state, fold rules), skeuo/ipsw.py, skeuo/restore.py, skeuo/usb/muxd.py.
- Decisions: Tauri 2 with a web front end; the app downloads IPSWs from Apple's servers; one device runs at a time; no VNC password (bind to 127.0.0.1 only); the guest clock lag after a resume stays as it is.

What to build in this conversation
1. Milestone 1, the pipeline API:
   - `skeuo serve`: JSON-lines RPC over stdio. Requests: list, create (restore with progress events), run (boot or resume), suspend, power_off, rename, update_settings, remove (move to trash), set_thumbnail, download_ipsw. Events: progress, state changes (off / starting / running / suspending / suspended), device attached/detached. Only one device may run; refuse a second run.
   - device.json gains `name` and `settings`; the bundle gains `thumbnail.png`. Keep format-2 bundles readable, and give existing bundles a default name.
   - Headless run for the app: `-display none` plus `-vnc 127.0.0.1:<n>,websocket=<port>` (free ports), reported in an event. Keep the suspend/resume behaviour and the bundle lock from `skeuo run`. The VNC options must not end up in the saved-state fingerprint (they're host-side details, like the ports already are).
   - IPSW download: find the restore IPSW URLs for iPod2,1 2.1.1 (5F138), 2.2 (5G77a), 3.0 (7A341) and 4.0 (8A293) on Apple's servers (verify that each URL still resolves, and don't guess), download with resume and progress into a cache directory, and check the checksum Apple publishes if there is one. A plain `skeuo download <version>` CLI as well.
2. Milestone 2, the display/input spike: a bare HTML page with an RFB client (noVNC or a small one of our own) against a device running headless with the VNC WebSocket. Check that the screen shows (including dimming and sleep), that touch lands where it should (the fingertip offset), that home/power/volume/rotate work as key events, and how much latency and CPU it costs. Then try the same page in a minimal Tauri 2 webview on macOS.
3. If both go well, ask me before starting milestone 3 (the app skeleton in app/: gallery, first-run bootrom step, start/suspend). Ask me about Svelte vs React then.

Constraints
- Keep verification short: one bundle (2.1.1 boots in seconds), no multi-minute loops. I test UI behaviour myself.
- QEMU's QMP serves one client at a time. The daemon holds the connection, so route screendumps and the like through the daemon.
- Commit in the skeuo repo in its existing style (short imperative subjects, e.g. "Suspend and resume devices"). Emulator changes, if any, go on qemu-ios `skeuo` in QEMU style ("hw/arm: ...", "ui: ..."), followed by a "Move the emulator to ..." submodule bump. Don't push. Ask before installing toolchains (Rust, Node, the Tauri CLI) with brew/rustup/npm.
- At the end, update docs/app-plan.md (status, what changed) and the pipeline README.
