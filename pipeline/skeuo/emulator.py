"""
Runs QEMU for a device bundle, with the USB link on a free local port and the serial port logged to a file.

QEMU is controlled over QMP on another local TCP port (a UNIX socket path in a bundle can exceed macOS's 104 bytes).
suspend() saves the machine to a file and quits, resume() loads such a file into a QEMU started with incoming=True.
The NAND is not part of the saved state: the state file is only valid with the disk image and overlay exactly as they
were when it was saved. QEMU must also be started with the same command, apart from its host-side details
(the fingerprint).

Closing the window or quitting QEMU from its menu pauses the machine instead of quitting (-action shutdown=pause,
which the emulator's SDL and Cocoa windows honour) and sets shutdown_requested, so the run can still suspend it.
A signal to QEMU still makes it quit. The guest never requests a shutdown itself. Because a machine paused like that is in QEMU's "shutdown" run state, which can't be continued
after loading, the run state is not saved (store-global-state=off): a loaded machine starts running.
"""
import hashlib
import json
import os
import queue
import socket
import subprocess
import threading
import time

from .usb.link import USBLink


class EmulatorError(Exception):
    pass


_running = set()  # every QEMU this process started and hasn't stopped


def kill_all():
    """Kills the QEMUs that are still running, before the process exits (they run in their own session)."""
    for emu in list(_running):
        emu.stop()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout, what):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise EmulatorError("timed out waiting for %s" % what)


def file_digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class QMP:
    """A QMP connection. execute() runs a command and returns its result; events go to on_event, called from the
    reader thread."""

    def __init__(self, port, on_event=None):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.sock.settimeout(None)
        self.file = self.sock.makefile("rwb")
        self.on_event = on_event
        self.replies = queue.Queue()
        self.lock = threading.Lock()
        greeting = json.loads(self.file.readline())
        if "QMP" not in greeting:
            raise EmulatorError("unexpected QMP greeting %r" % greeting)
        threading.Thread(target=self._read, daemon=True).start()
        self.execute("qmp_capabilities")

    def _read(self):
        try:
            for line in self.file:
                message = json.loads(line)
                if "event" in message:
                    if self.on_event:
                        self.on_event(message)
                else:
                    self.replies.put(message)
        except (OSError, ValueError):
            pass
        self.replies.put(None)  # QEMU went away

    def execute(self, command, timeout=30, **arguments):
        request = {"execute": command}
        if arguments:
            request["arguments"] = arguments
        with self.lock:
            try:
                self.file.write(json.dumps(request).encode() + b"\n")
                self.file.flush()
                reply = self.replies.get(timeout=timeout)
            except (OSError, queue.Empty) as e:
                raise EmulatorError("QMP %s: %s" % (command, e or "timed out"))
        if reply is None:
            raise EmulatorError("QMP %s: QEMU closed the connection" % command)
        if "error" in reply:
            raise EmulatorError("QMP %s: %s" % (command, reply["error"].get("desc", reply["error"])))
        return reply.get("return")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Emulator:
    """profile: the device's profile (devices/), which names the machine.
    bootrom: a dump of the profile's bootrom, or None: the emulator then starts LLB from the NOR (or boot_image)
    itself.
    dfu: hold the force-DFU GPIO so the bootrom enters DFU mode (needs the bootrom).
    boot_image: an IMG3 image to start instead of LLB from the NOR, without a bootrom: iBSS for a restore.
    display: show the QEMU window instead of running headless.
    vnc: serve the screen and take input over VNC on 127.0.0.1 instead, also as a WebSocket, both on free ports
    (vnc_port, websocket_port). The app draws the screen itself this way.
    wifi_mac: the Wi-Fi chip's address, for a device with the "wifi" capability; None leaves the Wi-Fi off.
    audio: play the device's audio on the host; False gives it a silent audio backend.
    boot_args: the kernel arguments iBoot passes on a normal boot, None for the emulator's default.
    incoming: wait for resume() to load a saved state instead of booting.
    clock: the -rtc base= date (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS), None for the host's.

    fingerprint is what a saved state belongs to: QEMU's digest and its arguments without the host-side details
    (file paths, ports, the window or VNC server, the clock), which may differ between saving and loading."""

    def __init__(self, qemu, profile, bootrom, disk, overlay, nor, logdir, nand_epoch, dfu=False, boot_image=None,
                 display=False, vnc=False, wifi_mac=None, audio=True, boot_args=None, extra_args=(), incoming=False,
                 clock=None):
        if not os.path.exists(qemu):
            raise EmulatorError("QEMU not found at %s" % qemu)
        if bootrom and not os.path.exists(bootrom):
            raise EmulatorError("bootrom not found at %s" % bootrom)
        if dfu and not bootrom:
            raise EmulatorError("DFU mode needs the bootrom")
        if wifi_mac and "wifi" not in profile.capabilities:
            raise EmulatorError("the %s has no Wi-Fi" % profile.name)
        self.port = free_port()
        self.qmp_port = free_port()
        self.vnc_port = self.websocket_port = None
        self.serial_log = os.path.join(logdir, "serial.log")

        def command(host):
            machine = "%s,nand-disk=%s,nand-overlay=%s,nand-epoch=%d,nor=%s,usb-chardev=usb" % (
                profile.machine, host["disk"], host["overlay"], nand_epoch, host["nor"])
            # only used at a reset, so it's not part of the fingerprint: a state saved with it loads without it
            if host.get("bootrom"):
                machine += ",bootrom=" + host["bootrom"]
            if dfu:
                machine += ",dfu=on"
            if boot_image:
                machine += ",boot-image=" + host["boot_image"]
            if boot_args:
                # QEMU's option parser takes a doubled comma as a literal one
                machine += ",boot-args=" + boot_args.replace(",", ",,")
            cmd = [
                "-M", machine, "-cpu", "max", "-m", "2G", "-monitor", "none",
                "-serial", "file:" + host["serial"],
                "-chardev", "socket,id=usb,host=127.0.0.1,port=%s,server=on,wait=off,nodelay=on" % host["port"],
                "-qmp", "tcp:127.0.0.1:%s,server=on,wait=off" % host["qmp_port"],
                "-action", "shutdown=pause", "-global", "migration.store-global-state=off",
            ]
            if wifi_mac:
                # the Wi-Fi chip's model reports the NIC's address as its own
                cmd += ["-nic", "user,model=%s,mac=%s" % (profile.wifi_nic, wifi_mac.lower())]
            if not audio:
                cmd += ["-audio", "none"]
            return cmd + list(extra_args)

        host = {"disk": disk, "overlay": overlay, "nor": nor, "boot_image": boot_image, "serial": self.serial_log,
                "port": self.port, "qmp_port": self.qmp_port}
        self.fingerprint = {"qemu": file_digest(qemu), "args": command({k: "<%s>" % k for k in host})}
        host["bootrom"] = bootrom
        cmd = [qemu] + command(host)
        if not display:
            cmd += ["-display", "none"]
        if vnc:
            # -vnc takes a display number, the port minus 5900; ephemeral ports are far above that
            self.vnc_port = free_port()
            self.websocket_port = free_port()
            cmd += ["-vnc", "127.0.0.1:%d,websocket=127.0.0.1:%d" % (self.vnc_port - 5900, self.websocket_port)]
        if clock:
            cmd += ["-rtc", "base=" + clock]
        if incoming:
            cmd += ["-incoming", "defer"]
        self.shutdown_requested = threading.Event()
        self.qmp = None
        self.log = open(os.path.join(logdir, "qemu.log"), "w")
        # in its own session, so that a Ctrl-C in the terminal reaches only the pipeline, which suspends
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        _running.add(self)

    def serial(self):
        try:
            with open(self.serial_log, errors="replace") as f:
                return f.read()
        except FileNotFoundError:
            return ""

    def check_running(self):
        if self.proc.poll() is not None:
            raise EmulatorError("QEMU exited with %d" % self.proc.returncode)

    def connect(self):
        link = None

        def try_connect():
            nonlocal link
            self.check_running()
            try:
                link = USBLink("127.0.0.1", self.port)
                return True
            except ConnectionRefusedError:
                return False

        wait_for(try_connect, 10, "the USB link socket")
        return link

    def control(self):
        """The QMP connection, opened on first use."""
        if self.qmp is None:
            qmp = None

            def try_connect():
                nonlocal qmp
                self.check_running()
                try:
                    qmp = QMP(self.qmp_port, on_event=self._event)
                    return True
                except ConnectionRefusedError:
                    return False

            wait_for(try_connect, 10, "QMP")
            self.qmp = qmp
        return self.qmp

    def _event(self, message):
        if message["event"] == "SHUTDOWN":
            self.shutdown_requested.set()

    def _wait_migration(self, timeout, what):
        status = {}

        def done():
            self.check_running()
            status.update(self.control().execute("query-migrate"))
            return status.get("status") in ("completed", "failed", "cancelled")

        wait_for(done, timeout, what)
        if status["status"] != "completed":
            raise EmulatorError("%s %s: %s" % (what, status["status"], status.get("error-desc", "no details")))

    def suspend(self, state):
        """Stops the machine, saves it to state and quits QEMU."""
        qmp = self.control()
        qmp.execute("stop")
        qmp.execute("migrate", uri="file:" + state)
        self._wait_migration(120, "saving the state")
        self.quit()

    def resume(self, state):
        """Loads state into a QEMU started with incoming=True and runs it."""
        qmp = self.control()
        qmp.execute("migrate-incoming", uri="file:" + state)

        def loaded():
            self.check_running()
            return qmp.execute("query-status")["status"] != "inmigrate"

        wait_for(loaded, 120, "the state to load")
        status = qmp.execute("query-status")["status"]
        if status not in ("running", "paused", "postmigrate"):
            raise EmulatorError("loading the state left the machine %s" % status)
        if status != "running":
            qmp.execute("cont")

    def screendump(self, path):
        """Writes the screen as it is now (also while the backlight is off) to path as a PNG."""
        self.control().execute("screendump", filename=path, format="png")

    def orientation(self, value=None):
        """How the device is held: "flat" or portrait, landscape-right (home button right), portrait-upside-down,
        landscape-left. Sets it first if value is given."""
        qmp = self.control()
        if value is not None:
            qmp.execute("qom-set", path="/machine/accelerometer", property="orientation", value=value)
        return qmp.execute("qom-get", path="/machine/accelerometer", property="orientation")

    def quit(self):
        try:
            self.control().execute("quit")
        except EmulatorError:
            pass
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            pass
        self.stop()

    def wait(self):
        return self.proc.wait()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        _running.discard(self)
        if self.qmp:
            self.qmp.close()
        self.log.close()
