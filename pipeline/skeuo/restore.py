"""
Restores a device bundle from an IPSW, the way iTunes restores a new device: the emulator starts iBSS (or, given the
bootrom, the bootrom takes iBSS over DFU), iBSS loads iBEC, iBEC boots the restore ramdisk, and restored on the ramdisk partitions the NAND, writes the root
filesystem it receives through asr and flashes the NOR images. The bundle starts out as a factory-new device: an
empty disk (which the emulator presents as a formatted, empty NAND) and a NOR with only the factory data.
"""
import os
import shutil
import struct
import tempfile
import time

from . import activation, identity, nor, prepare
from .bundle import Bundle
from .emulator import Emulator, EmulatorError, wait_for
from .restored import ASRServer, KernelCacheServer, NORServer, RestoreError, run_restore
from .usb.dfu import DFU_PID, RECOVERY_PID, command, dfu_upload, enumerate_device, set_configuration, upload
from .usb.link import USBError, USBNoDevice, USBTimeout
from .usb.mux import MuxError

RESTORED_TIMEOUT = 120


class Steps:
    def __init__(self, log):
        self.log = log

    def __call__(self, name, fn):
        start = time.monotonic()
        result = fn()
        self.log("ok    %-36s %.2f s" % (name, time.monotonic() - start))
        return result


def boot_ramdisk(emu, link, ipsw, step, dfu):
    """dfu: upload iBSS to the bootrom's DFU mode; otherwise the emulator started it."""
    ibec = ipsw.dfu_image("iBEC")
    device_tree = ipsw.device_tree()
    ramdisk = ipsw.restore_ramdisk()
    kernel = ipsw.kernelcache()

    def to_recovery():
        if dfu:
            enumerate_device(link, DFU_PID)
            dfu_upload(link, ipsw.dfu_image("iBSS"))
        wait_for(lambda: "Entering recovery mode" in emu.serial(), 20, "iBSS to enter recovery mode")

    def ibss_loads_ibec():
        enumerate_device(link, RECOVERY_PID)
        set_configuration(link)
        upload(link, ibec)
        try:
            command(link, "go")
        except (USBNoDevice, USBTimeout):
            pass
        wait_for(lambda: "iBEC for" in emu.serial(), 20, "iBEC to start")

    def ibec_ready():
        enumerate_device(link, RECOVERY_PID)
        set_configuration(link)
        # iBEC 3.0's devicetree command reads its first argument even when it has none, from the argument array the
        # previous command filled in. iTunes sends "setenv auto-boot false" first; without an earlier command with
        # arguments that slot is still stack fill ('stak'), which iBEC dereferences. Unlike iTunes this doesn't
        # saveenv: restored sets auto-boot back to true, but the kernel only writes NVRAM to the NOR when it reboots.
        command(link, "setenv auto-boot false")

    def load_device_tree():
        upload(link, device_tree)
        command(link, "devicetree", timeout=30)

    def load_ramdisk():
        upload(link, ramdisk)
        command(link, "ramdisk", timeout=30)

    def boot():
        try:
            command(link, "bootx", timeout=30)
        except (USBNoDevice, USBTimeout):
            pass

    step("DFU upload of iBSS" if dfu else "iBSS starts", to_recovery)
    step("iBSS loads iBEC", ibss_loads_ibec)
    step("iBEC enumerates", ibec_ready)
    step("upload device tree", load_device_tree)
    step("upload restore ramdisk", load_ramdisk)
    step("upload kernelcache", lambda: upload(link, kernel))
    step("bootx", boot)


def run_restored(emu, ipsw, log):
    link = emu.connect()
    start = time.monotonic()
    desc = link.wait_for_device(timeout=RESTORED_TIMEOUT)
    log("ok    restore ramdisk on USB, %04x:%04x         %.2f s"
        % (*struct.unpack_from("<HH", desc, 8), time.monotonic() - start))
    handlers = {
        "SystemImageData": ASRServer(ipsw.system_image(), log=log),
        "NORData": NORServer(*ipsw.nor_images(), log=log),
        "KernelCache": KernelCacheServer(ipsw.system_kernelcache(), log=log),
    }
    try:
        status, udid = run_restore(link, handlers, log=log)
    except (RestoreError, MuxError) as e:
        raise EmulatorError("restore: %s" % e)
    if status != 0:
        raise EmulatorError("restore failed with status %s" % status)
    return udid


def restore(ipsw, bundle_path, qemu, bootrom=None, lockdown=None, device_certificate=None, name=None, settings=None,
            log=print):
    """Creates a device bundle at bundle_path, restored with ipsw (an IPSW object). device_certificate: a PEM device
    certificate from Apple to activate with (see activation.py). name and settings: see bundle.py. bootrom: a dump
    of the device profile's bootrom to start iBSS through its DFU mode, None to let the emulator start it."""
    profile = ipsw.profile
    if profile.restore != "restored":
        raise EmulatorError("Skeuo can't restore the %s yet (%s)" % (profile.name, profile.restore))
    device = identity.generate()
    bundle = Bundle.create(bundle_path, ipsw, device, name=name, settings=settings)
    if device_certificate:
        # run keeps the device's clock within the certificate's validity
        bundle.info["device_certificate"] = {
            key: date.isoformat() for key, date in
            zip(("not_before", "not_after"), activation.certificate_validity(device_certificate))}
        bundle.save()
    step = Steps(log)
    try:
        open(bundle.disk, "wb").close()
        with open(bundle.nor, "wb") as f:
            f.write(nor.factory_nor(identity.syscfg(device), identity.nvram_env(device)))

        log("restoring %s as serial number %s" % (ipsw, device["serial_number"]))
        ibss = None
        if not bootrom:
            ibss = os.path.join(bundle.path, "iBSS.img3")
            with open(ibss, "wb") as f:
                f.write(ipsw.dfu_image("iBSS"))
        try:
            emu = Emulator(qemu, profile, bootrom, bundle.disk, bundle.overlay, bundle.nor, bundle.logs,
                           bundle.nand_epoch, dfu=bool(bootrom), boot_image=ibss,
                           wifi_mac=device["wifi_mac"] if "wifi" in profile.capabilities else None)
            try:
                link = emu.connect()
                try:
                    boot_ramdisk(emu, link, ipsw, step, dfu=bool(bootrom))
                finally:
                    link.close()
                device["udid"] = run_restored(emu, ipsw, log)
                bundle.save()
            except USBError as e:
                raise EmulatorError("USB: %s" % e)
            finally:
                emu.stop()
        finally:
            if ibss:
                os.remove(ibss)
        bundle.fold(log=log)

        work = tempfile.mkdtemp(prefix="prepare.", dir=bundle.path)
        try:
            prepare.prepare(bundle.disk, work, device, profile, ipsw.build, lockdown=lockdown,
                            device_certificate=device_certificate, log=log)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        bundle.mark_ready()
    except BaseException:
        log("restore failed; the logs are in %s" % bundle.logs)
        raise
    return bundle
