# SSH assets for iPod1,1 1.1.5 (4B1)

Restore installs these assets automatically for this product/build. Other profiles retain their existing
preparation. The assets are source-built free software: Dropbear 2026.94 and Dash 0.5.13.5, plus our small
ARMv6 startup/compatibility layer. No Apple library, firmware, SDK, startup object or device image is shipped.
The executables dynamically load the device's own libSystem 94 and libgcc_s.

The runtime payloads and SHA-256 manifest live in `pipeline/skeuo/ssh1g_assets/`; packaging copies that directory
with the pipeline. Licenses and the complete corresponding source kit accompany the payloads. `sources/` here
contains the build inputs. Dropbear's archive is the upstream release; Dash's archive is `make dist` from its
upstream v0.5.13.5 tag, with generated configure files (no target source changes).

Upstream sources:

- https://github.com/mkj/dropbear/releases/tag/DROPBEAR_2026.94
- https://dropbear.nl/mirror/releases/dropbear-2026.94.tar.bz2
- https://git.kernel.org/pub/scm/utils/dash/dash.git/tag/?h=v0.5.13.5
  (`037bbdfd330017c368caf6242f977974123239b5`)
- https://github.com/tpoechtrager/cctools-port
  (`904de2a71d4da6a9b30d2efaf912a10ddc7d9ddb`, cctools 1030.6.3 / ld64 956.6)

The source archive SHA-256 values are checked by `build.py`. The prototype and clean recipe build use Apple
Clang 21.0.0, the macOS 13.3 SDK's C headers, and cctools-port's linker. Apple binaries used for linking come
only from the user's 4B1 IPSW and remain in the ignored scratch directory.

## Build

Requires macOS, Python 3.12+ (tarfile's data filter), Xcode command-line tools, `make`, and `vfdecrypt`.
Build cctools-port in a scratch directory first; it needs no TAPI support for these real Mach-O libraries:

```sh
git clone https://github.com/tpoechtrager/cctools-port.git build/ssh-toolchain
git -C build/ssh-toolchain checkout 904de2a71d4da6a9b30d2efaf912a10ddc7d9ddb
cd build/ssh-toolchain/cctools
./configure --target=arm-apple-darwin --disable-tapi-support --disable-xar-support
make -j6
cd ../../..
python3 packaging/ssh1g/build.py \
  --ipsw /path/to/iPod1,1_1.1.5_4B1_Restore.ipsw \
  --dropbear-source packaging/ssh1g/sources/dropbear-2026.94.tar.bz2 \
  --dash-source packaging/ssh1g/sources/dash-0.5.13.5.tar.gz \
  --ld build/ssh-toolchain/cctools/ld64/src/ld/ld \
  --sdk /Library/Developer/CommandLineTools/SDKs/MacOSX13.3.sdk \
  --work build/ssh-assets
```

The work directory must be new. The script does not download anything or install host tools globally. Its
output defaults to the pipeline's asset directory; use `--output` to build a comparison copy. Libraries and
decrypted firmware in the work directory must never be copied into the source kit or runtime asset directory.

## Compatibility choices

- Reserve `r9` (`-ffixed-r9`): libSystem 94 uses it for the thread runtime. Letting the modern compiler allocate
  it as a general register caused the server to crash during signal setup.
- Use the legacy inode/stat ABI and pre-UNIX2003 symbol names, ARM instructions and a non-PIE executable.
- `crt.S` implements the classic lazy-binding calling convention and process argument globals. `compat.c`
  invokes the device libSystem's Mach/thread and delayed module initialization hooks. Both are our own source;
  no Apple crt object or extracted firmware instructions are incorporated.
- Supply `stpncpy` and the modern SDK's fd-set bounds check locally. Dash's F_DUPFD_CLOEXEC use is disabled because
  its presence in the host SDK does not imply support in the 1.x kernel.
- Disable unavailable login accounting and Dropbear's setresgid-based pre-auth privilege separation. The server
  uses its traditional privileged model, with public-key authentication, Ed25519 host keys and curve25519 KEX.
  Password authentication, agent/TCP forwarding, RSA/ECDSA and post-quantum KEX are disabled in this small build.
- The shell provides POSIX builtins and job control. This checkpoint does not install coreutils, SCP or SFTP.

Changes to these assets need an actual 1.1.5 USB login test, including an interactive PTY and a second cold boot.
