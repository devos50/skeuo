"""
`skeuo serve`: the pipeline as a daemon for the Skeuo app, speaking JSON lines over stdin/stdout.

The app sends requests, one JSON object per line:

  {"id": 1, "method": "run", "params": {"device": "ipod-2.1.1"}}

and gets one response per request, with the same id, once the request is done:

  {"id": 1, "result": {...}}
  {"id": 1, "error": {"code": "busy", "message": "..."}}

Requests run concurrently, so responses can come in any order. Between them come events, which have no id:

  {"event": "ready", "protocol": 1, "library": ..., "bootrom": true}       once, at startup
  {"event": "state", "device": id, "state": "running", "vnc": {...}}         see STATES
  {"event": "device", "device": {...}}                                       a device was added or changed
  {"event": "removed", "device": id}
  {"event": "progress", "request": 1, "device": id, "phase": "download" | "restore", "fraction": 0.42, "message": ...}
  {"event": "usb", "device": id, "attached": true, "serial": ...}         seen by libimobiledevice, or gone
  {"event": "log", "device": id, "message": ...}                             the pipeline's log lines
  {"event": "warning", "message": ...}

A device is a bundle directory in the library, and its id is the directory's name, which stays the same when the
device is renamed. Only one device runs at a time; the daemon refuses to run a second one. The running device's
screen and input are on QEMU's VNC server, as a WebSocket on 127.0.0.1 (the "vnc" of its "running" state). QMP has
one client, which is the daemon, so screenshots go through it too.

When stdin closes (the app quit) or the daemon gets SIGTERM/SIGINT, it suspends the running device and exits.

Requests (params, then result):
  list           {}                                     {"devices": [device, ...], "running": id or null}
  device_types   {}                                     {"device_types": [{"product", "name", "versions"}]}: what
                                                        create can make, with each type's versions (as ipsws)
  ipsws          {}                                     {"ipsws": [...]}: the versions, cached or downloadable
  download_ipsw  {"version"}                            {"path"}; progress events; cancel stops it
  create         {"product", "name", "version" | "ipsw", "device_certificate", "lockdown", "nor_images", "settings"}
                                                        {"device"}; the device event comes first, then progress
  run            {"device", "cold_boot"}                {"device", "vnc": {"port", "websocket"}, "resumed"}
  suspend        {"device"}                             {"state": "suspended"}
  power_off      {"device"}                             {"state": "off"}: stops it, or discards a saved state
  rename         {"device", "name"}                     {"device"}
  update_settings {"device", "settings", "discard_state"}  {"device"}; settings that change the emulator's
                                                        command line need discard_state on a suspended device
  remove         {"device"}                             {}: moves the bundle to the trash
  set_thumbnail  {"device", "png": base64}              {"device"}
  screenshot     {"device"}                             {"png": base64}: the running device's screen
  orientation    {"device", "orientation"}              {"orientation"}: how the running device is held ("flat",
                                                        "portrait", "landscape-right", "portrait-upside-down",
                                                        "landscape-left"); sets it when given
  cancel         {"request": id}                        {}: cancels a running download_ipsw or create download
  shutdown       {}                                     {}: suspends the running device and exits
"""
import base64
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import traceback

from . import download as downloads
from .activation import ActivationError, load_device_certificate
from .bundle import MACHINE_SETTINGS, Bundle, BundleError
from .emulator import EmulatorError, kill_all
from .hfs import HFSError
from .ipsw import DEVICE_TYPES, IPSW, IPSWError
from .nand import NANDError
from .restore import restore
from .session import Session
from .trash import TrashError, trash
from .usb.muxd import start_bridge

PROTOCOL = 1
# A device's states: "creating" (being restored), "incomplete" (a restore that didn't finish), "off", "suspended",
# and while it runs "starting", "running", "suspending" and "stopping" (powering off).
STATES = ("creating", "incomplete", "off", "suspended", "starting", "running", "suspending", "stopping")

ERRORS = (ActivationError, BundleError, EmulatorError, HFSError, IPSWError, NANDError, downloads.DownloadError,
          TrashError)


class RequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# How far a restore is, from its log lines: (pattern, fraction), weighted by how long the steps take (2.1.1: about
# 10 s to boot the ramdisk, 15 s of asr, 20 s more of restored, then the prepare step). asr's percentage maps onto
# ASR_RANGE.
RESTORE_PROGRESS = [
    (re.compile(r"^restoring "), 0.0),
    (re.compile(r"^ok +DFU upload of iBSS"), 0.01),
    (re.compile(r"^ok +iBSS loads iBEC"), 0.02),
    (re.compile(r"^ok +bootx"), 0.05),
    (re.compile(r"^ok +restore ramdisk on USB"), 0.06),
    (re.compile(r"data request: SystemImageData"), 0.15),
    (re.compile(r"^nor: "), 0.50),
    (re.compile(r"^kernelcache: "), 0.52),
    (re.compile(r"status: "), 0.65),
    (re.compile(r"^writing the changed pages"), 0.66),
    (re.compile(r"^letting SpringBoard"), 0.68),
    (re.compile(r"^writing the changed partitions"), 0.95),
]
ASR = re.compile(r"^asr: +(\d+)%")
ASR_RANGE = (0.16, 0.45)


def restore_fraction(message):
    match = ASR.match(message)
    if match:
        return round(ASR_RANGE[0] + (ASR_RANGE[1] - ASR_RANGE[0]) * int(match.group(1)) / 100, 3)
    for pattern, fraction in RESTORE_PROGRESS:
        if pattern.search(message):
            return fraction
    return None


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:40] or "device"


class Daemon:
    def __init__(self, library, qemu, bootrom, cache, usbmuxd, pair_records, out):
        self.library = library
        self.qemu = qemu
        self.bootrom = bootrom
        self.cache = cache
        self.usbmuxd = usbmuxd
        self.pair_records = pair_records
        self.out = out
        self.out_lock = threading.Lock()
        self.lock = threading.RLock()
        self.session = None        # the running device's Session
        self.running = None        # its id
        self.run_state = None      # its state: starting, running, suspending, stopping
        self.creating = {}         # id -> what to list for a device being created, until its bundle has a device.json
        self.cancels = {}          # request id -> threading.Event
        self.bridge = None
        self.bridge_failed = False
        self.stopped = threading.Event()
        self.closing = False

    # output

    def send(self, message):
        line = json.dumps(message, separators=(",", ":"))
        with self.out_lock:
            if self.out is None:
                return
            try:
                self.out.write(line + "\n")
                self.out.flush()
            except (OSError, ValueError):
                # the app is gone; carry on, so that the running device still gets suspended
                self.out = None

    def event(self, name, **fields):
        self.send(dict(event=name, **fields))

    def logger(self, device):
        def log(message):
            for line in str(message).splitlines():
                self.event("log", device=device, message=line)
        return log

    # devices

    def path(self, device_id):
        if not isinstance(device_id, str) or not device_id or device_id != os.path.basename(device_id) \
                or device_id.startswith("."):
            raise RequestError("bad_request", "not a device id: %r" % (device_id,))
        return os.path.join(self.library, device_id)

    def bundle(self, device_id):
        """The running device's own Bundle (so that changes reach its session), or the bundle as it is on disk."""
        with self.lock:
            if self.session and device_id == self.running:
                return self.session.bundle
        path = self.path(device_id)
        if not os.path.exists(os.path.join(path, "device.json")):
            raise RequestError("not_found", "there is no device %s" % device_id)
        return Bundle.read(path)

    def open_bundle(self, device_id):
        """A complete bundle, for running it."""
        path = self.path(device_id)
        if not os.path.exists(os.path.join(path, "device.json")):
            raise RequestError("not_found", "there is no device %s" % device_id)
        return Bundle.open(path)

    def state(self, device_id, bundle):
        with self.lock:
            if device_id == self.running:
                return self.run_state
            if device_id in self.creating:
                return "creating"
        if not bundle.ready:
            return "incomplete"
        return "suspended" if bundle.suspended else "off"

    def describe(self, device_id, bundle=None):
        bundle = bundle or self.bundle(device_id)
        info = bundle.info
        state = self.state(device_id, bundle)
        result = {
            "id": device_id,
            "path": bundle.path,
            "name": bundle.name,
            "product": info.get("product"),
            "version": info["firmware"]["version"],
            "build": info["firmware"]["build"],
            "created": info.get("created"),
            "state": state,
            "settings": bundle.settings,
            "activation": "device_certificate" if info.get("device_certificate") else "skeuo",
            "thumbnail": bundle.thumbnail if os.path.exists(bundle.thumbnail) else None,
            "suspended_at": (bundle.suspended or {}).get("saved"),
            # run from somewhere else, e.g. `skeuo run` in a terminal
            "in_use": state in ("off", "suspended", "incomplete") and bundle.in_use(),
        }
        if state in ("running", "suspending", "stopping") and self.session:
            result["vnc"] = self.vnc()
        return result

    def vnc(self):
        emu = self.session.emu
        return {"host": "127.0.0.1", "port": emu.vnc_port, "websocket": emu.websocket_port}

    def device_ids(self):
        if not os.path.isdir(self.library):
            return []
        return sorted(name for name in os.listdir(self.library)
                      if not name.startswith(".") and os.path.isfile(os.path.join(self.library, name, "device.json")))

    def set_run_state(self, device_id, state, **fields):
        with self.lock:
            if state in ("off", "suspended"):
                self.running = self.run_state = self.session = None
            else:
                self.running, self.run_state = device_id, state
        if state in ("running",):
            fields["vnc"] = self.vnc()
        self.event("state", device=device_id, state=state, **fields)

    def changed(self, device_id, bundle=None):
        info = self.describe(device_id, bundle)
        self.event("device", device=info)
        return info

    def check_editable(self, device_id, bundle):
        if bundle.in_use() and device_id != self.running:
            raise RequestError("in_use", "%s is in use by another Skeuo process" % bundle.name)

    # requests

    def do_list(self, params):
        devices = []
        ids = self.device_ids()
        for device_id in ids:
            try:
                devices.append(self.describe(device_id))
            except (BundleError, KeyError) as e:
                self.event("warning", message="skipping %s: %s" % (device_id, e))
        with self.lock:
            devices += [info for device_id, info in self.creating.items() if device_id not in ids]
        return {"devices": devices, "running": self.running}

    def do_ipsws(self, params):
        return {"ipsws": downloads.available(self.cache)}

    def do_device_types(self, params):
        versions = downloads.available(self.cache)
        return {"device_types": [{"product": product, "name": name,
                                  "versions": [v for v in versions if v["product"] == product]}
                                 for product, name in DEVICE_TYPES.items()]}

    def _download(self, request_id, version, device_id=None):
        cancel = self.cancels[request_id] = threading.Event()
        last = [-1]

        def progress(done, total):
            percent = done * 1000 // total
            if percent != last[0]:
                last[0] = percent
                self.event("progress", request=request_id, device=device_id, phase="download",
                           fraction=round(done / total, 4), done=done, total=total)

        try:
            return downloads.download(version, self.cache, progress=progress, cancel=cancel)
        except downloads.Cancelled:
            raise RequestError("cancelled", "the download was cancelled")
        finally:
            self.cancels.pop(request_id, None)

    def do_download_ipsw(self, params, request_id):
        return {"path": self._download(request_id, params.get("version"))}

    def do_cancel(self, params):
        cancel = self.cancels.get(params.get("request"))
        if cancel:
            cancel.set()
        return {}

    def do_create(self, params, request_id):
        if not self.bootrom or not os.path.exists(self.bootrom):
            raise RequestError("no_bootrom", "the S5L8720 bootrom is needed to create a device")
        name = (params.get("name") or "").strip()
        product = params.get("product") or "iPod2,1"
        if product not in DEVICE_TYPES:
            raise RequestError("bad_request", "Skeuo can't emulate %s yet" % product)
        version, ipsw_path = params.get("version"), params.get("ipsw")
        if not ipsw_path and not version:
            raise RequestError("bad_request", "create needs a version or an IPSW")
        if version and not ipsw_path and version not in downloads.FIRMWARES:
            raise RequestError("bad_request", "Skeuo supports %s, not %s" % (", ".join(downloads.FIRMWARES), version))
        if params.get("device_certificate") and params.get("lockdown"):
            raise RequestError("bad_request", "device_certificate and lockdown exclude each other")
        settings = params.get("settings") or {}
        with self.lock:
            if self.creating:
                raise RequestError("busy", "another device is being created")
            os.makedirs(self.library, exist_ok=True)
            base = slug(name or ("ipod-" + (version or "device")))
            device_id, n = base, 2
            while os.path.lexists(os.path.join(self.library, device_id)):
                device_id, n = "%s-%d" % (base, n), n + 1
            os.makedirs(os.path.join(self.library, device_id))
            placeholder = {"id": device_id, "path": os.path.join(self.library, device_id), "name": name or "iPod touch",
                           "version": version, "state": "creating", "settings": settings}
            self.creating[device_id] = placeholder
        log = self.logger(device_id)
        workdir = tempfile.mkdtemp(prefix="skeuo-ipsw.")
        try:
            # the card shows up before the download, as "creating"
            self.event("device", device=placeholder)
            if not ipsw_path:
                ipsw_path = downloads.cached(version, self.cache) or self._download(request_id, version, device_id)
            ipsw = IPSW(ipsw_path, workdir, nor_images=params.get("nor_images"))
            if ipsw.product != product:
                raise RequestError("bad_request", "%s is firmware for %s, not %s" % (ipsw_path, ipsw.product, product))
            if version and ipsw.version != version:
                raise RequestError("bad_request", "%s is %s, not %s" % (ipsw_path, ipsw.version, version))
            certificate = params.get("device_certificate")
            certificate = load_device_certificate(certificate) if certificate else None
            progress = [0.0]

            def restore_log(message):
                log(message)
                fraction = restore_fraction(str(message))
                if fraction is not None and fraction > progress[0]:
                    progress[0] = fraction
                    self.event("progress", request=request_id, device=device_id, phase="restore",
                               fraction=fraction, message=str(message))

            bundle = restore(ipsw, os.path.join(self.library, device_id), self.qemu, self.bootrom,
                             lockdown=params.get("lockdown"), device_certificate=certificate, name=name or None,
                             settings=settings, log=restore_log)
            self.event("progress", request=request_id, device=device_id, phase="restore", fraction=1.0,
                       message="ready")
        except BaseException:
            with self.lock:
                self.creating.pop(device_id, None)
            # a restore that failed leaves an incomplete bundle with its logs, which the app can remove
            path = os.path.join(self.library, device_id)
            if os.path.isfile(os.path.join(path, "device.json")):
                self.changed(device_id)
            else:
                shutil.rmtree(path, ignore_errors=True)
                self.event("removed", device=device_id)
            raise
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        with self.lock:
            self.creating.pop(device_id, None)
        return {"device": self.changed(device_id, bundle)}

    def do_run(self, params):
        device_id = params.get("device")
        if not self.bootrom or not os.path.exists(self.bootrom):
            raise RequestError("no_bootrom", "the S5L8720 bootrom is needed to run a device")
        bundle = self.open_bundle(device_id)
        with self.lock:
            if self.closing:
                raise RequestError("busy", "Skeuo is shutting down")
            if self.running:
                if self.running == device_id:
                    raise RequestError("busy", "%s is already running" % bundle.name)
                raise RequestError("busy", "%s is running; only one device can run at a time"
                                   % self.session.bundle.name)
            if device_id in self.creating:
                raise RequestError("busy", "%s is still being created" % bundle.name)
            session = Session(bundle, self.qemu, self.bootrom, vnc=True, cold_boot=bool(params.get("cold_boot")),
                              log=self.logger(device_id))
            self.session = session
            self.running, self.run_state = device_id, "starting"
        self.event("state", device=device_id, state="starting")
        try:
            session.start()
        except BaseException:
            self.set_run_state(device_id, "suspended" if bundle.suspended else "off")
            raise
        if bundle.settings["usbmuxd"]:
            self.attach_bridge(device_id, session.emu.port)
        self.set_run_state(device_id, "running", resumed=session.resumed)
        threading.Thread(target=self.watch, args=(device_id, session), daemon=True).start()
        return {"device": device_id, "vnc": self.vnc(), "resumed": session.resumed}

    def watch(self, device_id, session):
        """Ends the run when QEMU exits by itself."""
        session.exited.wait()
        with self.lock:
            if self.session is not session or self.run_state != "running":
                return  # being stopped
            self.run_state = "stopping"
        self.detach_bridge()
        result = session.stop()
        self.set_run_state(device_id, "off", reason=result)
        self.changed(device_id, session.bundle)

    def attach_bridge(self, device_id, port):
        if self.bridge is None and not self.bridge_failed and self.usbmuxd:
            def on_change(properties):
                with self.lock:
                    current = self.running
                if properties:
                    self.event("usb", device=current, attached=True, serial=properties["SerialNumber"],
                               usbmuxd=self.usbmuxd)
                else:
                    self.event("usb", device=current, attached=False)
            try:
                self.bridge = start_bridge(self.usbmuxd, port=None, pair_records=self.pair_records,
                                           on_change=on_change)
            except OSError as e:
                self.bridge_failed = True
                self.event("warning", message="libimobiledevice access is off: can't listen on %s (%s)"
                           % (self.usbmuxd, e))
        if self.bridge:
            self.bridge.port = port

    def detach_bridge(self):
        if self.bridge:
            self.bridge.port = None

    def stop_running(self, device_id, power_off):
        with self.lock:
            if self.running != device_id or self.run_state != "running":
                raise RequestError("not_running", "%s is not running" % device_id)
            session = self.session
            self.run_state = "stopping" if power_off else "suspending"
        self.event("state", device=device_id, state=self.run_state)
        self.detach_bridge()
        result = session.stop(power_off=power_off)
        state = "suspended" if result == "suspended" else "off"
        self.set_run_state(device_id, state, reason=result)
        self.changed(device_id, session.bundle)
        return {"state": state}

    def do_suspend(self, params):
        return self.stop_running(params.get("device"), power_off=False)

    def do_power_off(self, params):
        device_id = params.get("device")
        with self.lock:
            running = self.running == device_id
        if running:
            return self.stop_running(device_id, power_off=True)
        bundle = self.open_bundle(device_id)
        bundle.lock()
        try:
            bundle.discard_suspended(log=self.logger(device_id))
        finally:
            bundle.unlock()
        self.changed(device_id, bundle)
        return {"state": "off"}

    def editable(self, device_id):
        bundle = self.bundle(device_id)
        if device_id in self.creating:
            raise RequestError("busy", "%s is still being created" % device_id)
        self.check_editable(device_id, bundle)
        return bundle

    def do_rename(self, params):
        device_id = params.get("device")
        bundle = self.editable(device_id)
        bundle.rename(params.get("name") or "")
        return {"device": self.changed(device_id, bundle)}

    def do_update_settings(self, params):
        device_id = params.get("device")
        changes = params.get("settings") or {}
        bundle = self.editable(device_id)
        settings = bundle.settings
        machine = any(key in MACHINE_SETTINGS and settings.get(key) != bool(value) for key, value in changes.items())
        if machine:
            if device_id == self.running:
                raise RequestError("running", "%s is running; power it off to change %s"
                                   % (bundle.name, ", ".join(k for k in changes if k in MACHINE_SETTINGS)))
            if bundle.suspended:
                if not params.get("discard_state"):
                    raise RequestError("suspended", "%s is suspended, and changing this discards its saved state"
                                       % bundle.name)
                bundle.lock()
                try:
                    bundle.discard_suspended(log=self.logger(device_id))
                finally:
                    bundle.unlock()
        bundle.update_settings(changes)
        if device_id == self.running and "usbmuxd" in changes:
            if bundle.settings["usbmuxd"]:
                self.attach_bridge(device_id, self.session.emu.port)
            else:
                self.detach_bridge()
        return {"device": self.changed(device_id, bundle)}

    def do_remove(self, params):
        device_id = params.get("device")
        bundle = self.editable(device_id)
        if device_id == self.running:
            raise RequestError("running", "%s is running" % bundle.name)
        bundle.lock()  # also keeps other processes out while it moves
        try:
            trash(bundle.path)
        finally:
            bundle.unlock()
        self.event("removed", device=device_id)
        return {}

    def do_set_thumbnail(self, params):
        device_id = params.get("device")
        bundle = self.bundle(device_id)
        try:
            png = base64.b64decode(params.get("png") or "", validate=True)
        except ValueError:
            raise RequestError("bad_request", "png must be base64")
        bundle.set_thumbnail(png)
        return {"device": self.changed(device_id, bundle)}

    def do_screenshot(self, params):
        device_id = params.get("device")
        with self.lock:
            if self.running != device_id or self.run_state != "running":
                raise RequestError("not_running", "%s is not running" % device_id)
            emu = self.session.emu
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        try:
            emu.screendump(path)
            with open(path, "rb") as f:
                return {"png": base64.b64encode(f.read()).decode()}
        finally:
            os.remove(path)

    def do_orientation(self, params):
        device_id = params.get("device")
        with self.lock:
            if self.running != device_id or self.run_state != "running":
                raise RequestError("not_running", "%s is not running" % device_id)
            emu = self.session.emu
        return {"orientation": emu.orientation(params.get("orientation"))}

    def do_shutdown(self, params):
        threading.Thread(target=self.shutdown, daemon=True).start()
        return {}

    # the loop

    LONG = {"create", "download_ipsw"}  # these take the request id, for progress events

    def handle(self, request):
        request_id = request.get("id") if isinstance(request, dict) else None
        try:
            if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                raise RequestError("bad_request", "a request is an object with an id, a method and params")
            method = getattr(self, "do_" + request["method"], None)
            if method is None:
                raise RequestError("unknown_method", "no method %s" % request["method"])
            params = request.get("params") or {}
            result = method(params, request_id) if request["method"] in self.LONG else method(params)
            self.send({"id": request_id, "result": result})
        except RequestError as e:
            self.send({"id": request_id, "error": {"code": e.code, "message": str(e)}})
        except ERRORS as e:
            self.send({"id": request_id, "error": {"code": "failed", "message": str(e)}})
        except Exception as e:
            traceback.print_exc()
            self.send({"id": request_id, "error": {"code": "internal", "message": "%s: %s" % (type(e).__name__, e)}})

    def shutdown(self):
        """Suspends the running device and ends the daemon."""
        with self.lock:
            first, self.closing = not self.closing, True
        if not first:
            self.stopped.wait()
            return
        for cancel in list(self.cancels.values()):
            cancel.set()
        # a device that is starting or stopping settles first
        while True:
            with self.lock:
                device_id, state = self.running, self.run_state
            if state in (None, "running"):
                break
            threading.Event().wait(0.2)
        if device_id:
            try:
                self.stop_running(device_id, power_off=False)
            except Exception:
                traceback.print_exc()
        kill_all()  # a restore that is still going
        self.stopped.set()

    def serve(self, stdin):
        self.event("ready", protocol=PROTOCOL, library=self.library, cache=self.cache,
                   bootrom=bool(self.bootrom and os.path.exists(self.bootrom)), usbmuxd=self.usbmuxd)

        def read():
            for line in stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except ValueError:
                    self.send({"id": None, "error": {"code": "bad_request", "message": "not JSON: %s" % line[:80]}})
                    continue
                threading.Thread(target=self.handle, args=(request,), daemon=True).start()
            self.shutdown()  # the app went away

        threading.Thread(target=read, daemon=True).start()
        while not self.stopped.is_set():
            try:
                self.stopped.wait(0.5)
            except KeyboardInterrupt:
                break
        # a signal, or a shutdown that already suspended: make sure nothing is left running
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        self.shutdown()
        with self.out_lock:
            if self.out is not None:
                try:
                    self.out.close()
                except OSError:
                    pass
        return 0


def main(args):
    # stdout carries the protocol; anything else that prints goes to stderr
    out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    sys.stdout = sys.stderr

    def stop_on_sigterm(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_on_sigterm)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    daemon = Daemon(os.path.expanduser(args.library), args.qemu, args.bootrom, args.ipsw_cache, args.usbmuxd,
                    args.pair_records, out)
    return daemon.serve(sys.stdin)
