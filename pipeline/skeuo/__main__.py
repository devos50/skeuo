"""
Skeuo: classic iPhone OS in an emulator.

  python3 -m skeuo restore <ipsw> <bundle>    create a device from an IPSW (.ipsw file or extracted directory)
  python3 -m skeuo run <bundle>               start a device, or resume it if it was suspended
  python3 -m skeuo power-off <bundle>         discard a suspended device's saved state
  python3 -m skeuo download <version>         download a restore IPSW from Apple into the cache
  python3 -m skeuo serve                      the daemon for the Skeuo app: JSON lines over stdio (see serve.py)

The emulator starts the firmware itself; the chip's bootrom is optional (--bootrom or SKEUO_BOOTROM), for comparing
with the real boot path. What differs between the devices Skeuo emulates is in their profiles (skeuo/devices/). QEMU is found through --qemu, SKEUO_QEMU, or the emulator submodule's build
directory.
"""
import argparse
import os
import shutil
import signal
import sys
import tempfile

from .activation import ActivationError, load_device_certificate
from . import devices
from . import download as downloads
from .bundle import Bundle, BundleError
from .emulator import EmulatorError
from .hfs import HFSError
from .ipsw import IPSW, IPSWError
from .nand import NANDError
from .restore import restore
from .session import Session
from .usb.muxd import DEFAULT_PAIR_RECORDS, start_bridge

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_QEMU = os.path.join(REPO, "emulator", "build", "qemu-system-arm")


def log(text):
    print(text, flush=True)


def bootrom_names():
    return ", ".join(sorted({"%s %s" % (p.soc, p.bootrom.version) for p in devices.profiles() if p.bootrom}))


def versions():
    return "; ".join("%s: %s" % (p.product, ", ".join(p.firmwares)) for p in devices.profiles())


def add_emulator_arguments(parser):
    parser.add_argument("--qemu", default=os.environ.get("SKEUO_QEMU", DEFAULT_QEMU),
                        help="qemu-system-arm with the device's machine (default: %(default)s)")
    parser.add_argument("--bootrom", default=os.environ.get("SKEUO_BOOTROM"),
                        help="optional dump of the device's bootrom (%s) to boot through, instead of starting the "
                             "firmware directly (default: $SKEUO_BOOTROM)" % bootrom_names())


def cmd_restore(parser, args):
    if args.device_certificate and args.lockdown:
        parser.error("--device-certificate and --lockdown exclude each other")
    device_certificate = load_device_certificate(args.device_certificate) if args.device_certificate else None
    workdir = tempfile.mkdtemp(prefix="skeuo-ipsw.")
    try:
        ipsw = IPSW(args.ipsw, workdir, nor_images=args.nor_images)
        bundle = restore(ipsw, args.bundle, args.qemu, args.bootrom, lockdown=args.lockdown,
                         device_certificate=device_certificate, name=args.name, log=log)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    log("%s is ready; start it with: python3 -m skeuo run %s" % (bundle, args.bundle))
    return 0


def cmd_run(parser, args):
    bundle = Bundle.open(args.bundle)
    session = Session(bundle, args.qemu, args.bootrom, display=not args.headless, extra_args=args.qemu_args,
                      cold_boot=args.cold_boot, log=log)
    session.start()
    if args.usbmuxd and bundle.settings["usbmuxd"]:
        start_bridge(args.usbmuxd, port=session.emu.port, pair_records=args.pair_records)
        log("for libimobiledevice: export USBMUXD_SOCKET_ADDRESS=%s" % args.usbmuxd)

    def stop_on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    signal.signal(signal.SIGINT, signal.default_int_handler)  # also when started in the background
    try:
        # the window was closed, or QEMU got a signal: it paused the machine (see emulator.py)
        while not (session.exited.is_set() or session.emu.shutdown_requested.is_set()):
            session.exited.wait(0.2)
    except KeyboardInterrupt:
        pass
    # from here on, a second Ctrl-C must not interrupt the save
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    result = session.stop(power_off=args.power_off)
    if result == "suspended":
        log("`run` resumes it, `power-off` discards the state")
    return 1 if result == "crashed" else 0


def cmd_power_off(parser, args):
    bundle = Bundle.open(args.bundle)
    bundle.lock()
    if not bundle.suspended:
        log("%s is not suspended" % bundle)
    bundle.discard_suspended(log=log)
    return 0


def cmd_download(parser, args):
    if args.list:
        for fw in downloads.available(args.cache):
            if fw["cached"]:
                where = fw["cached"]
            elif fw["downloadable"]:
                where = "downloadable, %d MB" % (fw["size"] >> 20)
                if fw["partial"]:
                    where += " (%d MB downloaded)" % (fw["partial"] >> 20)
            else:
                where = "not on Apple's servers; restore from a local IPSW"
            log("%-8s %-6s %-6s %s" % (fw["product"], fw["version"], fw["build"], where))
        return 0
    if not args.version:
        parser.error("name a version (%s), or pass --list" % versions())
    profile = devices.for_version(args.version, args.product)
    last = [-1]

    def progress(done, total):
        percent = done * 100 // total
        if percent != last[0]:
            last[0] = percent
            print("\r%3d%%  %d of %d MB" % (percent, done >> 20, total >> 20), end="", flush=True)

    try:
        path = downloads.download(profile, args.version, args.cache, progress=progress)
    finally:
        if last[0] >= 0:
            print()
    log(path)
    return 0


def cmd_serve(parser, args):
    from . import serve
    return serve.main(args)


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
    p.add_argument("--device-certificate", metavar="FILE",
                   help="a device certificate Apple issued (PEM, or a device's activation record "
                        "pod_record.plist) to activate with; needed from iPhone OS 3.0 on. The device's clock is "
                        "kept within its validity")
    p.add_argument("--nor-images", help="NOR images (llb.img3, iboot.img3, ...) for IPSW extractions without "
                                        "Firmware/all_flash")
    p.add_argument("--name", help="the device's name in the app (default: iPod touch (<version>))")
    p.set_defaults(func=cmd_restore)

    p = sub.add_parser("run", help="start a device")
    p.add_argument("bundle")
    add_emulator_arguments(p)
    p.add_argument("--headless", action="store_true", help="run without a window")
    p.add_argument("--usbmuxd", default="127.0.0.1:27015", metavar="HOST:PORT",
                   help="serve the device to libimobiledevice here (default %(default)s, empty to disable)")
    p.add_argument("--pair-records", default=DEFAULT_PAIR_RECORDS)
    p.add_argument("--cold-boot", action="store_true", help="discard the saved state of a suspended device and boot")
    p.add_argument("--power-off", action="store_true",
                   help="when the run stops, power the device off instead of suspending it")
    p.add_argument("qemu_args", nargs="*", help="extra QEMU arguments, after --")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("power-off", help="discard a suspended device's saved state")
    p.add_argument("bundle")
    p.set_defaults(func=cmd_power_off)

    p = sub.add_parser("download", help="download a restore IPSW from Apple")
    p.add_argument("version", nargs="?", help=versions())
    p.add_argument("--product", help="the device the firmware is for, when several have that version")
    p.add_argument("--list", action="store_true", help="list the versions and what is in the cache")
    p.add_argument("--cache", default=downloads.default_cache(), help="the IPSW cache (default: %(default)s)")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("serve", help="the daemon for the Skeuo app (JSON lines over stdio)")
    p.add_argument("--library", default=os.environ.get("SKEUO_LIBRARY", "~/Skeuo"),
                   help="the directory with the device bundles (default: %(default)s)")
    add_emulator_arguments(p)
    p.add_argument("--ipsw-cache", default=downloads.default_cache(), help="default: %(default)s")
    p.add_argument("--usbmuxd", default="127.0.0.1:27015", metavar="HOST:PORT",
                   help="serve the running device to libimobiledevice here (default %(default)s, empty to disable)")
    p.add_argument("--pair-records", default=DEFAULT_PAIR_RECORDS)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    try:
        return args.func(parser, args)
    except (ActivationError, BundleError, devices.DeviceError, EmulatorError, HFSError, IPSWError, NANDError,
            downloads.DownloadError) as e:
        print("skeuo: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
