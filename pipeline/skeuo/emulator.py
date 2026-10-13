"""
Runs QEMU for a device bundle, with the USB link on a free local port and the serial port logged to a file.
"""
import os
import socket
import subprocess
import time

from .usb.link import USBLink


class EmulatorError(Exception):
    pass


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


class Emulator:
    """dfu: hold the force-DFU GPIO so the bootrom enters DFU mode.
    display: show the QEMU window instead of running headless.
    boot_args: the kernel arguments iBoot passes on a normal boot, None for the emulator's default."""

    def __init__(self, qemu, bootrom, disk, overlay, nor, logdir, nand_epoch, dfu=False, display=False, wifi_mac=None,
                 boot_args=None, extra_args=()):
        if not os.path.exists(qemu):
            raise EmulatorError("QEMU not found at %s" % qemu)
        if not os.path.exists(bootrom):
            raise EmulatorError("bootrom not found at %s" % bootrom)
        self.port = free_port()
        self.serial_log = os.path.join(logdir, "serial.log")
        machine = "iPod-Touch,bootrom=%s,nand-disk=%s,nand-overlay=%s,nand-epoch=%d,nor=%s,usb-chardev=usb" % (
            bootrom, disk, overlay, nand_epoch, nor)
        if dfu:
            machine += ",dfu=on"
        if boot_args:
            # QEMU's option parser takes a doubled comma as a literal one
            machine += ",boot-args=" + boot_args.replace(",", ",,")
        cmd = [
            qemu, "-M", machine, "-cpu", "max", "-m", "2G", "-monitor", "none",
            "-serial", "file:" + self.serial_log,
            "-chardev", "socket,id=usb,host=127.0.0.1,port=%d,server=on,wait=off,nodelay=on" % self.port,
        ]
        if wifi_mac:
            # the BCM4325 model reports the NIC's address as its own
            cmd += ["-nic", "user,model=bcm4325,mac=%s" % wifi_mac.lower()]
        if not display:
            cmd += ["-display", "none"]
        cmd += list(extra_args)
        self.log = open(os.path.join(logdir, "qemu.log"), "w")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT)

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

    def wait(self):
        return self.proc.wait()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.log.close()
