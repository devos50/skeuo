"""
DFU and recovery mode, the way irecovery talks to a real device: the bootrom
takes an image over DFU, iBSS and iBEC take uploads and iBoot commands.
"""
import struct

from .link import USBError

DFU_PID = 0x1227
RECOVERY_PID = 0x1281

DFU_DNLOAD = 1
DFU_GETSTATUS = 3
DFU_BLOCK_SIZE = 0x800

UPLOAD_EP = 0x04
UPLOAD_CHUNK = 0x8000


class DeviceError(USBError):
    pass


def enumerate_device(link, expected_pid, timeout=20):
    """Waits for the device to appear in the given mode and returns its serial number string."""
    desc = link.wait_for_device(timeout=timeout)
    pid = struct.unpack_from("<H", desc, 10)[0]
    if pid != expected_pid:
        raise DeviceError("expected product 0x%04x, got 0x%04x" % (expected_pid, pid))
    return link.get_string(desc[16])


def dfu_upload(link, data):
    """Sends an image to the bootrom in DFU mode, which then boots it."""
    blocks = [data[i:i + DFU_BLOCK_SIZE] for i in range(0, len(data), DFU_BLOCK_SIZE)]
    for block_num, block in enumerate(blocks):
        link.ctrl_transfer(0x21, DFU_DNLOAD, block_num, 0, block)
        status = link.ctrl_transfer(0xA1, DFU_GETSTATUS, 0, 0, 6)[0]
        if status != 0:
            raise DeviceError("DFU error %d after block %d" % (status, block_num))

    # A zero-length download plus a few status requests start the manifest
    # phase, and a bus reset then makes the bootrom boot the image.
    link.ctrl_transfer(0x21, DFU_DNLOAD, len(blocks), 0, b"")
    for _ in range(3):
        link.ctrl_transfer(0xA1, DFU_GETSTATUS, 0, 0, 6)
    link.reset()


def set_configuration(link):
    link.ctrl_transfer(0x00, 0x09, 1, 0)


def upload(link, data):
    """Uploads a file to iBSS/iBEC's load address."""
    link.ctrl_transfer(0x41, 0, 0, 0)
    for offset in range(0, len(data), UPLOAD_CHUNK):
        link.bulk_write(UPLOAD_EP, data[offset:offset + UPLOAD_CHUNK])


def command(link, text, timeout=5):
    """Runs an iBoot command. iBoot stalls the request when the command fails, and commands like "go" never finish
    it because the device leaves recovery mode."""
    link.ctrl_transfer(0x40, 0, 0, 0, text.encode() + b"\0", timeout=timeout)
