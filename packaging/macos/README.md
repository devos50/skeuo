# Packaging Skeuo for macOS

```bash
packaging/macos/package.sh
```

builds `build/Skeuo-<version>-arm64.dmg` here (Apple silicon, macOS 13 and later in principle; see below). It needs
Xcode's command line tools, Node, Rust and Homebrew's glib, pixman, libslirp, faad2 and mpg123 on this Mac; the
app needs none of them. The plan behind it is `docs/packaging-plan.md`.

The app holds everything the pipeline needs in `Skeuo.app/Contents/Resources`:

```
pipeline/skeuo/...              the pipeline, with its bytecode
python/bin/python3              python-build-standalone's CPython 3.12, trimmed (fetch-python.sh)
python/lib/python3.12/...
qemu/qemu-system-arm            a release build of the emulator submodule (build-qemu.sh)
qemu/lib/*.dylib                its Homebrew dylibs, referenced as @loader_path/lib (bundle-qemu.sh)
```

A release build of the app runs its daemon from there (`app/src-tauri/src/lib.rs`, `runtime`);
`SKEUO_PYTHON`, `SKEUO_PIPELINE` and `SKEUO_QEMU` still override each part.

The steps, each usable on its own:

- `build-qemu.sh [dir]`: configures and builds the emulator into `build/qemu` (only rebuilds once configured).
- `bundle-qemu.sh <qemu-system-arm> <dir>`: copies QEMU and its non-system dylibs into `<dir>`, rewrites the
  references, checks with `otool` that nothing points into Homebrew, and prints the oldest macOS each file runs on.
- `fetch-python.sh <dir>`: downloads the pinned Python (cached in `build/cache`, checked by SHA-256) and trims it.
- `tauri.bundle.json`: the resources, merged into the app's Tauri config by `tauri build --config`, so that
  `npm run tauri dev` doesn't need them.
- `sign.sh <Skeuo.app>`: signs inside out with the hardened runtime; QEMU gets `qemu.entitlements` (JIT).

## Signing

Builds are signed ad hoc for now, so the first launch needs right-click → Open (or System Settings → Privacy &
Security → Open Anyway). The hardened runtime only loads libraries signed by the same team, and ad hoc signatures
have none, so ad hoc builds also give QEMU and Python `com.apple.security.cs.disable-library-validation`.

With a Developer ID certificate in the keychain:

```bash
xcrun notarytool store-credentials skeuo-notary     # once: an App Store Connect API key
SKEUO_SIGN_IDENTITY="Developer ID Application: … (TEAMID)" SKEUO_NOTARY_PROFILE=skeuo-notary packaging/macos/package.sh
```

signs with it (and a secure timestamp, without the library-validation exception), notarizes the DMG and staples
it. `package.sh --unsigned` skips signing altogether.

## Known limits

- Homebrew's bottles on this Mac are built for macOS 26, so the bundled dylibs (and so the emulator) only load on
  macOS 26 or later, whatever the app's `LSMinimumSystemVersion` says. Reaching macOS 13 means building those five
  libraries with `MACOSX_DEPLOYMENT_TARGET=13.0` (the plan's option 2) or on a macOS 13 machine.
- The package is about 26 MB as a DMG and 81 MB installed.
