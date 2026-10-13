"""
Skeuo: classic iPhone OS in an emulator.

  python3 -m skeuo restore <ipsw> <bundle>    create a device from an IPSW (.ipsw file or extracted directory)
  python3 -m skeuo run <bundle>               start a device, or resume it if it was suspended
  python3 -m skeuo power-off <bundle>         discard a suspended device's saved state

The emulator needs the S5L8720 bootrom, which Skeuo does not ship: pass --bootrom or set SKEUO_BOOTROM. QEMU is
found through --qemu, SKEUO_QEMU, or the emulator submodule's build directory.
"""
import argparse
import datetime
import os
import shutil
import signal
import sys
import tempfile
import threading
import time

from .activation import ActivationError, load_device_certificate
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
    if args.device_certificate and args.lockdown:
        parser.error("--device-certificate and --lockdown exclude each other")
    device_certificate = load_device_certificate(args.device_certificate) if args.device_certificate else None
    workdir = tempfile.mkdtemp(prefix="skeuo-ipsw.")
    try:
        ipsw = IPSW(args.ipsw, workdir, nor_images=args.nor_images)
        bundle = restore(ipsw, args.bundle, args.qemu, args.bootrom, lockdown=args.lockdown,
                         device_certificate=device_certificate, log=log)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    log("%s is ready; start it with: python3 -m skeuo run %s" % (bundle, args.bundle))
    return 0


def check_suspended(bundle, fingerprint):
    """Raises if the bundle's saved state belongs to a different emulator or command."""
    saved = bundle.suspended["fingerprint"]
    if saved == fingerprint:
        return
    what = "QEMU build" if saved["qemu"] != fingerprint["qemu"] else "emulator arguments"
    raise BundleError("%s was suspended on %s with different %s, so its saved state can't be loaded. Run it with the "
                      "same ones, or discard the state with --cold-boot or `python3 -m skeuo power-off %s`"
                      % (bundle.path, bundle.suspended["saved"], what, bundle.path))


def cmd_run(parser, args):
    check_emulator_arguments(parser, args)
    bundle = Bundle.open(args.bundle)
    bundle.lock()
    os.makedirs(bundle.logs, exist_ok=True)
    if args.cold_boot:
        bundle.discard_suspended(log=log)
    resume = bundle.suspended
    if not resume:
        bundle.fold(log=log)  # left behind by a run that did not end cleanly
    clock = bundle.resume_clock() if resume else bundle.clock_date
    if any(arg.startswith("-rtc") for arg in args.qemu_args):
        clock = None
    emu = Emulator(args.qemu, args.bootrom, bundle.disk, bundle.overlay, bundle.nor, bundle.logs, bundle.nand_epoch,
                   display=not args.headless, wifi_mac=bundle.info["identity"]["wifi_mac"],
                   boot_args=bundle.boot_args, extra_args=args.qemu_args, incoming=bool(resume), clock=clock)
    started = time.time()
    try:
        emu.control()  # from the start, to see a closed window (SHUTDOWN)
        if resume:
            check_suspended(bundle, emu.fingerprint)
            log("resuming %s, suspended at %s (logs in %s)" % (bundle, resume["saved"], bundle.logs))
            emu.resume(bundle.state)
            bundle.consume_suspended()
        else:
            log("running %s (logs in %s)" % (bundle, bundle.logs))
    except BaseException:
        emu.stop()
        raise
    if clock:
        log("the device's clock %s at %s, within the validity of its device certificate"
            % ("continues" if resume else "starts", clock))
    if args.usbmuxd:
        start_bridge(args.usbmuxd, port=emu.port, pair_records=args.pair_records)
        log("for libimobiledevice: export USBMUXD_SOCKET_ADDRESS=%s" % args.usbmuxd)

    def stop_on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    signal.signal(signal.SIGINT, signal.default_int_handler)  # also when started in the background
    exited = threading.Event()
    threading.Thread(target=lambda: (emu.wait(), exited.set()), daemon=True).start()
    try:
        # the window was closed, or QEMU got a signal: it paused the machine (see emulator.py)
        while not (exited.is_set() or emu.shutdown_requested.is_set()):
            exited.wait(0.2)
    except KeyboardInterrupt:
        pass
    # from here on, a second Ctrl-C must not interrupt the save
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if exited.is_set():
        log("QEMU exited with %s; see %s" % (emu.proc.returncode, os.path.join(bundle.logs, "qemu.log")))
        emu.stop()
        bundle.fold(log=log)
        return 1
    if not args.power_off:
        log("suspending")
        try:
            emu.suspend(bundle.state)
        except EmulatorError as e:
            log("could not save the state (%s); powering off instead" % e)
        else:
            device_clock = None
            if clock:
                base = datetime.datetime.fromisoformat(clock)
                device_clock = (base + datetime.timedelta(seconds=time.time() - started)).isoformat(timespec="seconds")
            bundle.record_suspended(emu.fingerprint, device_clock)
            log("suspended; `run` resumes it, `power-off` discards the state")
            return 0
    emu.stop()
    bundle.fold(log=log)
    return 0


def cmd_power_off(parser, args):
    bundle = Bundle.open(args.bundle)
    bundle.lock()
    if not bundle.suspended:
        log("%s is not suspended" % bundle)
    bundle.discard_suspended(log=log)
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
    p.add_argument("--device-certificate", metavar="FILE",
                   help="a device certificate Apple issued (PEM, or a device's activation record "
                        "pod_record.plist) to activate with; needed from iPhone OS 3.0 on. The device's clock is "
                        "kept within its validity")
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
    p.add_argument("--cold-boot", action="store_true", help="discard the saved state of a suspended device and boot")
    p.add_argument("--power-off", action="store_true",
                   help="when the run stops, power the device off instead of suspending it")
    p.add_argument("qemu_args", nargs="*", help="extra QEMU arguments, after --")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("power-off", help="discard a suspended device's saved state")
    p.add_argument("bundle")
    p.set_defaults(func=cmd_power_off)

    args = parser.parse_args()
    try:
        return args.func(parser, args)
    except (ActivationError, BundleError, EmulatorError, HFSError, IPSWError, NANDError) as e:
        print("skeuo: %s" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
