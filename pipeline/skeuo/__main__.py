"""
Skeuo: classic iPhone OS in an emulator.

  python3 -m skeuo restore <ipsw> <bundle>    create a device from an IPSW (.ipsw file or extracted directory)
  python3 -m skeuo run <bundle>               start a device

The emulator needs the S5L8720 bootrom, which Skeuo does not ship: pass --bootrom or set SKEUO_BOOTROM. QEMU is
found through --qemu, SKEUO_QEMU, or the emulator submodule's build directory.
"""
import argparse
import os
import shutil
import signal
import sys
import tempfile
import threading

from .bundle import Bundle, BundleError
from .emulator import Emulator, EmulatorError
from .hfs import HFSError
from .ipsw import IPSW, IPSWError
from .nand import NANDError
from .restore import restore
from .usb.muxd import DEFAULT_PAIR_RECORDS, start_bridge

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_QEMU = os.path.join(REPO, "emulator", "build", "qemu-system-arm")


def log(text):
    print(text, flush=True)


def add_emulator_arguments(parser):
    parser.add_argument("--qemu", default=os.environ.get("SKEUO_QEMU", DEFAULT_QEMU),
                        help="qemu-system-arm with the iPod Touch machine (default: %(default)s)")
    parser.add_argument("--bootrom", default=os.environ.get("SKEUO_BOOTROM"),
                        help="S5L8720 bootrom dump (default: $SKEUO_BOOTROM)")


def check_emulator_arguments(parser, args):
    if not args.bootrom:
        parser.error("the bootrom is needed: pass --bootrom or set SKEUO_BOOTROM")


def cmd_restore(parser, args):
    check_emulator_arguments(parser, args)
    workdir = tempfile.mkdtemp(prefix="skeuo-ipsw.")
    try:
        ipsw = IPSW(args.ipsw, workdir, nor_images=args.nor_images)
        bundle = restore(ipsw, args.bundle, args.qemu, args.bootrom, lockdown=args.lockdown, log=log)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    log("%s is ready; start it with: python3 -m skeuo run %s" % (bundle, args.bundle))
    return 0


def cmd_run(parser, args):
    check_emulator_arguments(parser, args)
    bundle = Bundle.open(args.bundle)
    os.makedirs(bundle.logs, exist_ok=True)
    bundle.fold(log=log)  # left behind by a run that did not end cleanly
    emu = Emulator(args.qemu, args.bootrom, bundle.disk, bundle.overlay, bundle.nor, bundle.logs, bundle.nand_epoch,
                   display=not args.headless, wifi_mac=bundle.info["identity"]["wifi_mac"],
                   extra_args=args.qemu_args)
    log("running %s (logs in %s)" % (bundle, bundle.logs))
    if args.usbmuxd:
        start_bridge(args.usbmuxd, port=emu.port, pair_records=args.pair_records)
        log("for libimobiledevice: export USBMUXD_SOCKET_ADDRESS=%s" % args.usbmuxd)

    def stop_on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    done = threading.Event()
    threading.Thread(target=lambda: (emu.wait(), done.set()), daemon=True).start()
    try:
        done.wait()
    except KeyboardInterrupt:
        pass
    finally:
        emu.stop()
        bundle.fold(log=log)
    return 0


def main():
    parser = argparse.ArgumentParser(prog="skeuo", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("restore", help="create a device from an IPSW")
    p.add_argument("ipsw", help=".ipsw file or extracted IPSW directory")
    p.add_argument("bundle", help="directory for the new device")
    add_emulator_arguments(p)
    p.add_argument("--lockdown", help="instead of Skeuo's own activation: the Lockdown directory of a device Apple "
                                      "activated, or a filesystem image with it (only valid for that device)")
    p.add_argument("--nor-images", help="NOR images (llb.img3, iboot.img3, ...) for IPSW extractions without "
                                        "Firmware/all_flash")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("run", help="start a device")
    p.add_argument("bundle")
    add_emulator_arguments(p)
    p.add_argument("--headless", action="store_true", help="run without a window")
    p.add_argument("--usbmuxd", default="127.0.0.1:27015", metavar="HOST:PORT",
                   help="serve the device to libimobiledevice here (default %(default)s, empty to disable)")
    p.add_argument("--pair-records", default=DEFAULT_PAIR_RECORDS)
    p.add_argument("qemu_args", nargs="*", help="extra QEMU arguments, after --")
    p.set_defaults(func=cmd_run)

    args = parser.parse_args()
    try:
        return args.func(parser, args)
    except (BundleError, EmulatorError, HFSError, IPSWError, NANDError) as e:
        print("skeuo: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
