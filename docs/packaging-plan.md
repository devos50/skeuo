# Skeuo packaging and CI: plan

Status: agreed (2026-10-14), roadmap step 5. Nothing is built yet.

Decisions (Martijn, 2026-10-14):
- Apple silicon only (arm64, macOS 13+).
- A standalone Python (python-build-standalone) in the bundle.
- Signing and notarization once there is an Apple Developer account again; ad-hoc signed builds until then.
- Auto-updates later.
- No CI for now; the CI section below stays as the plan for later.
- Skeuo is licensed GPL-3.0-or-later (LICENSE); the emulator keeps QEMU's GPLv2.

Since the bootrom-free boot (qemu-ios d7729e5337) a Skeuo user needs nothing from Apple but the IPSWs, which the app
downloads itself. So a package is: the app, the emulator, the pipeline and a Python to run it. No first-run step, no
files to supply.

## Where things stand

- **App** (`app/`): Tauri 2.12 + Svelte 5. `bundle.active` is false in `tauri.conf.json`; the icons are there.
  The daemon is started as `python3 -m skeuo serve` from `pipeline_dir()`, which is `$SKEUO_PIPELINE` or
  `CARGO_MANIFEST_DIR/../../pipeline`: a compile-time path to the repository, so a built app only works on this Mac.
  Python comes from `$SKEUO_PYTHON` or `python3` on the PATH.
- **Pipeline** (`pipeline/`): standard library only, Python 3.12 here. QEMU is `--qemu`, `$SKEUO_QEMU`, or
  `emulator/build/qemu-system-arm`. `prepare` changes the restored HFS+ filesystems through `hdiutil`
  (`hfs.py`), so creating a device works on macOS only. Everything else (download, restore, run, serve, the usbmuxd
  bridge on TCP, trash) already has Windows/Linux paths or needs none.
- **Emulator** (`emulator/` submodule = qemu-ios `skeuo`): the local build is a debug build (`buildtype=debug`,
  unstripped, 32 MB) with SDL, slirp and plugins, and links Homebrew's glib, pixman, libslirp, libpng, jpeg-turbo,
  zstd, faad2, mpg123, SDL2 (sdl2-compat) and libX11, plus system libs (curl, sasl, pam, ncurses, iconv, bz2, z).
  The device needs none of the iPod firmware blobs in `pc-bios/`.
- **Repository**: devos50/skeuo is private, has no LICENSE, no tests and no CI.

## What the package contains (macOS)

```
Skeuo.app/Contents/
  MacOS/skeuo                     the Tauri app
  Resources/pipeline/skeuo/...    the pipeline's Python sources
  Resources/python/               a relocatable CPython (bin/python3, lib/python3.12/...)
  Resources/qemu/qemu-system-arm  the emulator, with its dylibs in Resources/qemu/lib (rpath @loader_path/lib)
```

Tauri's `bundle.resources` copies these; `bundle.externalBin` (sidecars) would work for QEMU too, but it wants a
target-triple suffix and doesn't handle the dylibs, so plain resources are simpler.

App changes for this: in a bundled app, `start_daemon` takes the pipeline, Python and QEMU from
`app.path().resource_dir()` and passes QEMU to the daemon (`--qemu` or `SKEUO_QEMU`). The environment variables keep
overriding it, and the repository paths stay the fallback for `npm run tauri dev`. The compile-time
`CARGO_MANIFEST_DIR` path must only be used in debug builds.

Estimated size: QEMU release build, stripped, ~15 MB, its dylibs ~10 MB, Python ~40 MB (trimmed: no tkinter,
idlelib, test, ensurepip), app ~10 MB: about 75 MB installed, ~30 MB as a DMG.

### The emulator build

A release configure, only what the device uses:
`--target-list=arm-softmmu --enable-slirp --disable-sdl --disable-gtk --disable-curl --disable-vnc-jpeg
--disable-png --disable-zstd --disable-plugins --disable-docs --disable-tools --disable-curses --disable-auth-pam
--disable-vnc-sasl --disable-libusb`, with faad2 and mpg123 (the AMC audio decoder needs them) and Cocoa left in
for `skeuo run`'s window. The app draws the screen over VNC (raw encoding), so VNC stays and needs no PNG/JPEG. That
leaves glib (with pcre2, gettext's libintl), pixman, libslirp, faad2 and mpg123 to ship.

Two ways to get those dylibs:

1. **Homebrew + relink** (start here): build against Homebrew, then a script copies every non-system dylib into
   `qemu/lib`, rewrites the install names with `install_name_tool` to `@loader_path/lib/...`, and checks with
   `otool -L` that nothing points into `/opt/homebrew` any more. Quick, but the binaries only run on macOS versions
   as new as the build machine's Homebrew bottles target, so set `MACOSX_DEPLOYMENT_TARGET` and build on the oldest
   runner we support.
2. **Static deps built from source** (later, if 1 bites): a small script builds the five libraries with a fixed
   deployment target and links them statically. More reproducible; more to maintain.

Decided: Apple silicon only, macOS 13+ (no universal binary).

### Python

Decided: python-build-standalone. The options were:

- **python-build-standalone** (chosen): Astral's relocatable CPython (`install_only_stripped` builds), shipped
  in Resources. The pipeline runs unchanged as `python -m skeuo serve`, and the CLI (`restore`, `run`) stays usable
  from the bundled Python for people who want it. ~40 MB before trimming.
- **Freezing the pipeline** (PyInstaller or Nuitka) into one `skeuo` executable: smaller and one file to sign, but
  another build tool, slower start (PyInstaller unpacks), and the CLI only via that binary.
- **The system's Python**: macOS has `/usr/bin/python3` only with the Command Line Tools, so it would ask users to
  install them. Not an option for a consumer app.

## Signing, notarization, distribution (macOS)

- Every Mach-O inside the app (QEMU, its dylibs, Python's binary and extension modules, the app) is signed with a
  Developer ID certificate and the hardened runtime, inside out, then the app, then the DMG.
- Entitlements: QEMU's TCG generates code (MAP_JIT), so QEMU needs `com.apple.security.cs.allow-jit`. The app and
  Python need none, unless notarization flags Python's extension modules (then
  `com.apple.security.cs.disable-library-validation` on Python only). The app isn't sandboxed (it runs QEMU and
  Python as child processes and writes the library anywhere), which is fine outside the Mac App Store.
- Notarization with `notarytool` (an App Store Connect API key), then staple the DMG.
- Decided: an Apple Developer account comes later. Until then builds are ad-hoc signed, and users must allow the app
  in System Settings (or right-click → Open) the first time. The signing steps are scripted so that a Developer ID
  certificate only has to be plugged in.
- Distribution: a DMG on GitHub Releases. Decided: auto-updates (Tauri's updater plugin) later.

## CI (GitHub Actions) — later

Decided: no CI for now. The plan for when it comes: the repository is private, so macOS runner minutes count 10×
against the plan's quota.

1. **Build** (every push to main and every PR): on `macos-14` (arm64), check out with the submodule; build QEMU
   (release configure, ccache keyed on the submodule commit), the frontend (`npm ci && npm run build`) and the app
   (`cargo build --release`); run `python -m compileall pipeline` and a pyflakes pass. ~10 min with a warm cache.
2. **Package** (tags, and on demand): the build plus the bundling scripts above, Python standalone, signing and
   notarization (certificate and API key as repository secrets), the DMG as a release asset.
3. **Boot test** (nightly and on demand, the long one): for 2.1.1, 2.2 and 4.0, download the IPSW from Apple
   (actions/cache keeps them; they don't change), `skeuo restore` without a bootrom, then `skeuo run --headless` and
   check that the device comes up. The check must not be a screenshot: headless screens go dark (see the
   bootrom-free notes). Proposed checks, in order of strength: the restore's status 0; the kernel's "BSD root" on the
   serial log; lockdownd answering a QueryType over the pipeline's own usbmux code (needs no libimobiledevice), which
   means userland is up; a suspend + resume that answers lockdownd again. About 3 min per version.
   3.0 can't be tested in CI: Apple never published its IPSW, and we can't host it.

`hdiutil` works on GitHub's macOS runners, so restore and prepare run there as they do here.

## Windows and Linux (phase 2)

Mostly straightforward, except one blocker:

- **Blocker: `prepare` needs macOS** (`hfs.py` mounts the HFS+ partitions with `hdiutil`). Options: (a) a pure-Python
  HFS+ writer for the few changes prepare makes (the SpringBoard plist, activation records, Lockdown files, owners);
  the catalog B-tree insert/update is the work; (b) make the changes inside the guest instead, e.g. from the restore
  ramdisk after restored finishes; (c) Linux's hfsplus driver (needs root to mount, so no). Proposed: (a), scoped to
  exactly the operations prepare uses. It's the biggest item in this plan.
- QEMU: Windows through MSYS2 (mingw-w64-ucrt; slirp, glib, pixman, faad2, mpg123 are all packaged there), Linux on an
  old-ish glibc (or as an AppImage/Flatpak with its runtime). VNC display, so no SDL or GTK needed.
- App: WebView2 on Windows (the installer bootstraps it), WebKitGTK on Linux. The RFB client and the device window
  are untested in both (open question in app-plan.md).
- Python standalone has builds for both; `download.py` and `trash.py` already know the Windows/Linux paths.
- Packages: an MSI or NSIS installer on Windows (Tauri builds both; Authenticode signing is another certificate),
  an AppImage and/or a .deb on Linux.

## Licensing

- QEMU is GPLv2, and faad2 is GPL too: shipping the binary means offering its source. The submodule commit on a
  public qemu-ios branch, linked from the app's About box and the release notes, covers it, once qemu-ios `skeuo` is
  pushed with the release's commit.
- Python (PSF), glib, pixman and mpg123 (LGPL, dynamically linked, so fine as dylibs), libslirp (BSD), Tauri (MIT/Apache).
- Skeuo itself is GPL-3.0-or-later (LICENSE). It runs QEMU as a separate program, so the two licenses don't mix;
  GPLv3 also accepts the Apache-2.0 crates the Rust app links, which GPLv2 wouldn't. Whether the repository goes
  public is still open.
- The emulator contains the per-firmware image keys (the GID key table, community-published). Not Apple's code, but
  worth a conscious decision before going public.

## Order of work

1. App: resource-relative paths for the pipeline, Python and QEMU (small; testable with a hand-assembled bundle).
2. Release QEMU configure + the dylib bundling script (`packaging/macos/bundle-qemu.sh`), checked with `otool -L`
   and a boot of 2.1.1 from the bundled binary.
3. Python standalone in the bundle, `tauri build` with `bundle.active` and the resources: an unsigned .app/.dmg that
   runs on a clean Mac (or a fresh user account without Homebrew on the PATH).
4. A packaging script (`packaging/macos/`) that produces the ad-hoc signed DMG in one command, with the signing
   step ready for a Developer ID.
5. Later: signing and notarization (with the developer account), CI, auto-updates.
6. Phase 2: the HFS+ writer, then Windows and Linux.
