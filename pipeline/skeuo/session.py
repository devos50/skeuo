"""
One run of a device bundle: boots it, or resumes it if it was suspended, and suspends or powers it off when it stops.
`run` and `serve` both run devices through this.
"""
import datetime
import os
import threading
import time

from .bundle import BundleError
from .emulator import Emulator, EmulatorError


def check_suspended(bundle, fingerprint):
    """Raises if the bundle's saved state belongs to a different emulator or command."""
    saved = bundle.suspended["fingerprint"]
    if saved == fingerprint:
        return
    what = "QEMU build" if saved["qemu"] != fingerprint["qemu"] else "emulator arguments"
    raise BundleError("%s was suspended on %s with different %s, so its saved state can't be loaded. Run it with the "
                      "same ones, or discard the state with --cold-boot or `python3 -m skeuo power-off %s`"
                      % (bundle.path, bundle.suspended["saved"], what, bundle.path))


class Session:
    """display: QEMU's own window; vnc: the screen over VNC/WebSocket for the app (see Emulator).
    After start(), exited is set when QEMU exits by itself (a crash), and emu.shutdown_requested when its window
    was closed. stop() ends the run either way."""

    def __init__(self, bundle, qemu, bootrom, display=False, vnc=False, extra_args=(), cold_boot=False, log=print):
        self.bundle = bundle
        self.qemu = qemu
        self.bootrom = bootrom
        self.display = display
        self.vnc = vnc
        self.extra_args = list(extra_args)
        self.cold_boot = cold_boot
        self.log = log
        self.emu = None
        self.resumed = False
        self.exited = threading.Event()
        self.clock = None
        self.started = None

    def start(self):
        bundle = self.bundle
        bundle.lock()
        try:
            self._start()
        except BaseException:
            if self.emu:
                self.emu.stop()
            bundle.unlock()
            raise

    def _start(self):
        bundle, log = self.bundle, self.log
        os.makedirs(bundle.logs, exist_ok=True)
        if self.cold_boot:
            bundle.discard_suspended(log=log)
        resume = bundle.suspended
        if not resume:
            bundle.fold(log=log)  # left behind by a run that did not end cleanly
        clock = bundle.resume_clock() if resume else bundle.clock_date
        if any(arg.startswith("-rtc") for arg in self.extra_args):
            clock = None
        settings = bundle.settings
        self.emu = emu = Emulator(
            self.qemu, bundle.profile, self.bootrom, bundle.disk, bundle.overlay, bundle.nor, bundle.logs,
            bundle.nand_epoch, display=self.display, vnc=self.vnc,
            wifi_mac=bundle.info["identity"]["wifi_mac"] if settings["wifi"] else None, audio=settings["audio"],
            boot_args=bundle.boot_args, extra_args=self.extra_args, incoming=bool(resume), clock=clock)
        self.started = time.time()
        emu.control()  # from the start, to see a closed window (SHUTDOWN)
        if resume:
            check_suspended(bundle, emu.fingerprint)
            log("resuming %s, suspended at %s (logs in %s)" % (bundle, resume["saved"], bundle.logs))
            emu.resume(bundle.state)
            bundle.consume_suspended()
            self.resumed = True
        else:
            log("running %s (logs in %s)" % (bundle, bundle.logs))
        self.clock = clock
        if clock:
            log("the device's clock %s at %s, within the validity of its device certificate"
                % ("continues" if resume else "starts", clock))
        threading.Thread(target=lambda: (emu.wait(), self.exited.set()), daemon=True).start()

    def stop(self, power_off=False):
        """Suspends the device, or powers it off; returns "suspended" or "off". If QEMU exited by itself, the
        device is off and the result is "crashed"."""
        bundle, emu, log = self.bundle, self.emu, self.log
        try:
            if self.exited.is_set():
                log("QEMU exited with %s; see %s" % (emu.proc.returncode, os.path.join(bundle.logs, "qemu.log")))
                emu.stop()
                bundle.fold(log=log)
                return "crashed"
            if not power_off and "suspend" not in bundle.profile.capabilities:
                log("the %s can't suspend; powering off" % bundle.profile.name)
                power_off = True
            if not power_off:
                log("suspending")
                try:
                    emu.suspend(bundle.state)
                except EmulatorError as e:
                    log("could not save the state (%s); powering off instead" % e)
                else:
                    device_clock = None
                    if self.clock:
                        base = datetime.datetime.fromisoformat(self.clock)
                        device_clock = (base + datetime.timedelta(seconds=time.time() - self.started)).isoformat(
                            timespec="seconds")
                    bundle.record_suspended(emu.fingerprint, device_clock)
                    log("suspended")
                    return "suspended"
            emu.stop()
            bundle.fold(log=log)
            return "off"
        finally:
            bundle.unlock()
