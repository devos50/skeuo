// The app's view of the pipeline daemon: the devices and what runs, kept up to date from its events
// (pipeline/skeuo/serve.py describes them). Everything else goes through call().

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export const library = $state({
  devices: [],        // as serve.py's describe(), sorted by name
  running: null,      // the id of the running device
  usb: null,          // the running device's usbmuxd info while libimobiledevice sees it
  error: null,        // the last failed action, shown in the gallery
  thumbnails: {},     // id -> a counter that changes when the thumbnail does
  progress: {},       // id -> {phase: "download" | "restore", fraction, request} while a device is being created
});

export async function call(method, params = {}) {
  return invoke("rpc", { method, params });
}

function sort() {
  library.devices.sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

function upsert(device) {
  const i = library.devices.findIndex((d) => d.id === device.id);
  if (i >= 0) library.devices[i] = { ...library.devices[i], ...device };
  else library.devices.push(device);
  sort();
}

export async function refresh() {
  const result = await call("list");
  library.devices = result.devices;
  library.running = result.running;
  sort();
}

let listening = false;

export async function connect() {
  if (!listening) {
    listening = true;
    await listen("daemon", ({ payload: event }) => {
      switch (event.event) {
        case "state": {
          const device = library.devices.find((d) => d.id === event.device);
          if (device) device.state = event.state;
          if (["starting", "running", "suspending", "stopping"].includes(event.state)) library.running = event.device;
          else if (library.running === event.device) {
            library.running = null;
            library.usb = null;
          }
          if (event.reason === "crashed") library.error = "The device stopped unexpectedly. Its logs are in the bundle.";
          break;
        }
        case "progress":
          if (event.device) library.progress[event.device] = { phase: event.phase, fraction: event.fraction, request: event.request };
          break;
        case "device":
          if (event.device.state !== "creating") delete library.progress[event.device.id];
          if (event.device.thumbnail) library.thumbnails[event.device.id] = (library.thumbnails[event.device.id] || 0) + 1;
          upsert(event.device);
          break;
        case "removed":
          delete library.progress[event.device];
          library.devices = library.devices.filter((d) => d.id !== event.device);
          break;
        case "usb":
          library.usb = event.attached ? event : null;
          break;
        case "exited":
          library.error = "The Skeuo daemon stopped. Restart Skeuo.";
          break;
      }
    });
  }
  await refresh();
}

/** Runs a device and opens its window (or brings it forward). */
export async function start(id, coldBoot = false) {
  library.error = null;
  try {
    await invoke("start_device", { id, coldBoot });
  } catch (e) {
    library.error = e.message || String(e);
  }
}

export async function act(method, id) {
  library.error = null;
  try {
    await call(method, { device: id });
  } catch (e) {
    library.error = e.message || String(e);
  }
}

/** Creates a device (see create in serve.py). The card shows up at once through the daemon's events; this resolves
 * when the restore is done. */
export async function create(params) {
  library.error = null;
  try {
    await call("create", params);
  } catch (e) {
    if (e.code !== "cancelled") library.error = `Couldn't create “${params.name || "the device"}”: ${e.message || e}`;
  }
}

/** Stops the download of a device being created (the restore itself can't be stopped). */
export async function cancelCreate(id) {
  const progress = library.progress[id];
  if (progress) await call("cancel", { request: progress.request });
}
