# iPod touch 1G SSH payloads

`dropbear` (2026.94) and `dash` (0.5.13.5) are source-built ARMv6 Mach-O executables for iPhone OS 1.1.5.
`manifest.json` records their SHA-256 hashes. The clean build recipe reproduces both binaries byte for byte.
They dynamically use the user's restored libSystem/libgcc; neither Apple library is included here.

Licenses are in `licenses/`. `sources.tar.xz` contains the complete corresponding free-software sources,
configuration, our startup/compatibility code and build scripts. Extract it into a separate folder to inspect
or rebuild; the build needs the user's IPSW and local SDK/toolchain. The same readable recipe and provenance
are in `packaging/ssh1g/README.md` in the repository.

These files contain no device keys. Preparation generates separate client/host identities per device bundle.
