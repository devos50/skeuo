# iPod touch 2G SSH payloads

`dropbear` (2026.94) and `dash` (0.5.13.5) are source-built ARMv6 Mach-O executables for iPhone OS 2.1.1 and
later, tested on 2.1.1, 2.2 and 4.0. They carry an ad-hoc SHA-1 code signature. `manifest.json` records their
SHA-256 hashes. The clean build recipe reproduces both binaries byte for byte. They dynamically use the user's
restored libSystem/libgcc; neither Apple library is included here.

Licenses are in `licenses/`. `sources.tar.xz` contains the complete corresponding free-software sources,
configuration, our startup/compatibility code, the signer and build scripts. Extract it into a separate folder to
inspect or rebuild; the build needs a restored 2.1.1 bundle and the local SDK/toolchain. The same readable recipe
and provenance are in `packaging/ssh1g/README.md` in the repository.

These files contain no device keys. Preparation generates separate client/host identities per device bundle.
