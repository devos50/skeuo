# Continue the iPod touch 1G work on another machine

As of 2026-10-16, USB checkpoints 1, 2 and 3 are complete. The current state and evidence are in
[multi-device-plan.md](multi-device-plan.md), especially “IPSW restore on the 1G” and “SSH over USB on the 1G”.
The USB kickoff prompt is preserved as historical context; its descriptions of missing functionality predate
these checkpoints. Automatic SSH installation for the 2G is a possible next task, not implemented yet.

From an existing Skeuo checkout on the other Mac:

```sh
git pull --ff-only origin main
git submodule update --init --recursive
packaging/macos/build-qemu.sh
```

The submodule update checks out the emulator commit pinned by Skeuo. Build prerequisites are documented in
[the macOS packaging README](../packaging/macos/README.md). A 1G restore also needs `vfdecrypt` on PATH;
`ssh-keygen` generates the per-bundle SSH identities, and `iproxy` forwards the USB connection.

The source-built ARMv6 SSH binaries, their source kit and licenses are committed; rebuilding those guest
binaries is optional. Their recipe is in [packaging/ssh1g](../packaging/ssh1g/README.md).

With the user's 1.1.5 IPSW available locally, restore a new bundle:

```sh
PYTHONPATH=pipeline python3 -m skeuo restore /path/to/iPod1,1_1.1.5_4B1_Restore.ipsw \
  /path/to/new-bundle --qemu packaging/macos/build/qemu/qemu-system-arm
PYTHONPATH=pipeline python3 -m skeuo run /path/to/new-bundle --power-off \
  --qemu packaging/macos/build/qemu/qemu-system-arm
```

NOR programming takes about six minutes. Restore installs the SSH server, shell and per-bundle keys
automatically. See [USB SSH instructions](../pipeline/README.md#usb-ssh-on-the-ipod-touch-1g) for connecting.

Generated device storage, firmware, logs, host build products and private keys are excluded from Git. To use
the exact device state tested here instead of restoring anew, privately copy the entire powered-off bundle:

- `build/usb-1g/checkpoint3-final-verified` — fresh restore with automatic SSH, verified across two cold boots.
- `build/usb-1g/checkpoint2-final-verified` — earlier restored bundle, subsequently upgraded with SSH.

Keep the bundle's `ssh/` directory with it: it contains the client private key and the stable host identity.
Both test devices were stopped after verification. Do not commit device storage or private keys.
