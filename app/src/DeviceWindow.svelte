<script>
  import { onMount } from "svelte";
  import { invoke } from "@tauri-apps/api/core";
  import { listen } from "@tauri-apps/api/event";
  import { getCurrentWindow, LogicalSize } from "@tauri-apps/api/window";
  import { call } from "./lib/daemon.svelte.js";
  import { RFB } from "./lib/rfb.js";
  import DeviceFrame, { FRAME, SCREEN } from "./DeviceFrame.svelte";
  import Menu from "./Menu.svelte";
  import Confirm from "./Confirm.svelte";

  let { id, websocket } = $props();

  // the device's buttons: X keysym and PC scancode of the key the emulator maps to them (ipod_touch_2g.c)
  const BUTTONS = {
    home:    { keysym: 0x68, scancode: 0x23 },
    power:   { keysym: 0x70, scancode: 0x19 },
    voldown: { keysym: 0x2d, scancode: 0x0c },
    volup:   { keysym: 0x3d, scancode: 0x0d },
  };
  // plain keys hold a button as long as they are down (hold P for "slide to power off")
  const HOLD_KEYS = { KeyH: "home", KeyP: "power", Minus: "voldown", Equal: "volup" };
  // iOS reads the buttons on an interrupt; a press released at once can be over before it looks
  const MIN_PRESS = 100;
  const THUMBNAIL_EVERY = 5000;
  // how the device is held, in quarter turns counter-clockwise from portrait (the accelerometer's order), and how
  // far that turns the drawing (CSS degrees, clockwise)
  const ORIENTATIONS = ["portrait", "landscape-right", "portrait-upside-down", "landscape-left"];
  const ANGLES = { flat: 0, portrait: 0, "landscape-right": -90, "portrait-upside-down": 180, "landscape-left": 90 };
  const PAD = 16;       // around the frame
  const TOOLBAR = 44;

  let canvas = $state();
  let rfb;
  let name = $state("");
  let status = $state("Connecting…");
  let toast = $state(null);
  let closing = $state(false);
  let orientation = $state("portrait");
  let scale = $state(readScale());   // "fit", 1 or 2
  let stageWidth = $state(0);
  let stageHeight = $state(0);
  let usb = $state(false);
  let menu = $state(null);
  let confirm = $state(null);
  const pressedAt = {};
  const held = new Set();
  const win = getCurrentWindow();

  const angle = $derived(ANGLES[orientation] ?? 0);
  const landscape = $derived(Math.abs(angle) === 90);
  const boxWidth = $derived(landscape ? FRAME.height : FRAME.width);
  const boxHeight = $derived(landscape ? FRAME.width : FRAME.height);
  const factor = $derived(
    scale === "fit"
      ? Math.max(0.1, Math.min((stageWidth - 2 * PAD) / boxWidth, (stageHeight - 2 * PAD) / boxHeight))
      : scale
  );

  function readScale() {
    try {
      const s = localStorage.getItem("scale");
      return s === "1" ? 1 : s === "2" ? 2 : "fit";
    } catch {
      return "fit";
    }
  }

  // 1x and 2x size the window to the device; fit keeps the window's size but follows a rotation
  async function sizeWindow(rotated = false) {
    let w, h;
    if (scale === "fit") {
      if (!rotated) return;
      w = stageHeight;
      h = stageWidth;
    } else {
      w = boxWidth * scale + 2 * PAD;
      h = boxHeight * scale + 2 * PAD;
    }
    await win.setSize(new LogicalSize(Math.round(w), Math.round(h + TOOLBAR)));
  }

  async function setScale(value) {
    scale = value;
    try { localStorage.setItem("scale", String(value)); } catch {}
    await sizeWindow();
  }

  function press(button, down) {
    const b = BUTTONS[button];
    if (down) {
      pressedAt[button] = performance.now();
      rfb?.key(b.keysym, b.scancode, true);
    } else {
      const wait = MIN_PRESS - (performance.now() - (pressedAt[button] || 0));
      setTimeout(() => rfb?.key(b.keysym, b.scancode, false), Math.max(0, wait));
    }
  }

  function tap(button) {
    press(button, true);
    press(button, false);
  }

  async function rotate(direction) {
    // direction 1: a quarter turn counter-clockwise (rotate left), -1: clockwise
    const i = Math.max(0, ORIENTATIONS.indexOf(orientation));
    const next = ORIENTATIONS[(i + direction + 4) % 4];
    try {
      const result = await call("orientation", { device: id, orientation: next });
      const wasLandscape = landscape;
      orientation = result.orientation;
      if (landscape !== wasLandscape) await sizeWindow(true);
    } catch (e) {
      flash(e.message || String(e));
    }
  }

  function flash(text) {
    toast = text;
    setTimeout(() => { if (toast === text) toast = null; }, 2500);
  }

  async function screenshot() {
    if (!rfb?.width) return;
    // the screen as the user sees it, turned with the device
    const shot = document.createElement("canvas");
    shot.width = landscape ? SCREEN.height : SCREEN.width;
    shot.height = landscape ? SCREEN.width : SCREEN.height;
    const ctx = shot.getContext("2d");
    ctx.translate(shot.width / 2, shot.height / 2);
    ctx.rotate((angle * Math.PI) / 180);
    ctx.drawImage(canvas, -SCREEN.width / 2, -SCREEN.height / 2);
    const blob = await new Promise((resolve) => shot.toBlob(resolve, "image/png"));
    const d = new Date();
    const two = (n) => String(n).padStart(2, "0");
    const file = `${name || "Skeuo"} ${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} at ` +
      `${two(d.getHours())}.${two(d.getMinutes())}.${two(d.getSeconds())}`;
    try {
      await invoke("save_screenshot", new Uint8Array(await blob.arrayBuffer()), {
        headers: { "x-name": encodeURIComponent(file) },
      });
      flash("Screenshot saved to the Desktop");
    } catch (e) {
      flash(`Couldn't save the screenshot: ${e}`);
    }
  }

  function keydown(e) {
    const cmd = e.metaKey || e.ctrlKey;
    if (cmd) {
      // Simulator-style shortcuts; macOS doesn't send keyup while ⌘ is down, so these tap
      const k = e.key.toLowerCase();
      const action =
        e.shiftKey && k === "h" ? () => tap("home") :
        k === "l" ? () => tap("power") :
        e.key === "ArrowUp" ? () => tap("volup") :
        e.key === "ArrowDown" ? () => tap("voldown") :
        e.key === "ArrowLeft" ? () => rotate(1) :
        e.key === "ArrowRight" ? () => rotate(-1) :
        k === "s" ? screenshot :
        k === "1" ? () => setScale(1) :
        k === "2" ? () => setScale(2) :
        k === "3" ? () => setScale("fit") :
        null;
      if (action) {
        e.preventDefault();
        if (!e.repeat) action();
      }
      return;
    }
    if (e.altKey) return;
    const button = HOLD_KEYS[e.code];
    if (!button) return;
    e.preventDefault();
    if (held.has(button)) return;
    held.add(button);
    press(button, true);
  }

  function keyup(e) {
    const button = HOLD_KEYS[e.code];
    if (button && held.delete(button)) press(button, false);
  }

  // touch: from the window to framebuffer pixels, undoing the frame's scale and rotation
  function at(e) {
    const r = canvas.getBoundingClientRect();
    const dx = (e.clientX - (r.left + r.width / 2)) / factor;
    const dy = (e.clientY - (r.top + r.height / 2)) / factor;
    const t = (angle * Math.PI) / 180;
    const x = dx * Math.cos(t) + dy * Math.sin(t);
    const y = -dx * Math.sin(t) + dy * Math.cos(t);
    return [x * SCREEN.width / canvas.offsetWidth + SCREEN.width / 2, y * SCREEN.height / canvas.offsetHeight + SCREEN.height / 2];
  }

  // the gallery thumbnail: the last frame with the screen lit, sent when it changes and when the window closes
  const probe = document.createElement("canvas");
  probe.width = 16;
  probe.height = 24;
  let lastSample = "";

  async function captureThumbnail() {
    if (!rfb?.width) return;
    const ctx = probe.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(canvas, 0, 0, probe.width, probe.height);
    const px = ctx.getImageData(0, 0, probe.width, probe.height).data;
    let sum = 0;
    for (let i = 0; i < px.length; i += 4) sum += px[i] + px[i + 1] + px[i + 2];
    const sample = Array.from(px.filter((_, i) => i % 16 === 0)).join();
    if (sum / (px.length / 4) / 3 <= 12 || sample === lastSample) return;
    lastSample = sample;
    try {
      await call("set_thumbnail", { device: id, png: canvas.toDataURL("image/png").split(",")[1] });
    } catch {}
  }

  function showMenu(e) {
    const r = e.currentTarget.getBoundingClientRect();
    menu = {
      x: r.left,
      y: r.bottom + 4,
      items: [
        { label: "Take Screenshot", run: screenshot },
        { separator: true },
        { label: "Restart", run: () => askRestart() },
        { label: "Power Off…", run: () => askPowerOff() },
      ],
    };
  }

  function askPowerOff() {
    confirm = {
      title: `Power off “${name}”?`,
      message: "It shuts down at once, like pulling the battery. Apps lose what they didn't save. Closing the window suspends it instead.",
      action: "Power Off",
      run: async () => {
        closing = true;
        status = "Powering off…";
        await call("power_off", { device: id }).catch(() => {});
        await win.destroy();
      },
    };
  }

  function askRestart() {
    confirm = {
      title: `Restart “${name}”?`,
      message: "It powers off and boots again. Apps lose what they didn't save.",
      action: "Restart",
      run: () => {
        closing = true;
        status = "Restarting…";
        invoke("restart_device", { id }).catch((e) => { closing = false; status = null; flash(e.message || String(e)); });
      },
    };
  }

  onMount(() => {
    rfb = new RFB(`ws://127.0.0.1:${websocket}`, canvas);
    rfb.addEventListener("connect", () => (status = null));
    rfb.addEventListener("disconnect", () => { if (!closing) status = "The device's screen disconnected."; });
    rfb.addEventListener("error", () => (status = "Can't reach the device's screen."));

    call("list").then(({ devices }) => {
      const device = devices.find((d) => d.id === id);
      if (device) {
        name = device.name;
        win.setTitle(device.name);
      }
    });
    call("orientation", { device: id }).then(async (result) => {
      orientation = result.orientation;
      if (landscape) await sizeWindow(true);
      else if (scale !== "fit") await sizeWindow();
    }).catch(() => {});

    const unlistenDaemon = listen("daemon", ({ payload }) => {
      if (payload.event === "usb") usb = payload.attached;
      if (payload.event === "device" && payload.device.id === id) name = payload.device.name;
    });

    const timer = setInterval(captureThumbnail, THUMBNAIL_EVERY);

    // closing the window suspends the device, as closing a laptop does
    const unlistenClose = win.onCloseRequested(async (event) => {
      event.preventDefault();
      if (closing) return;
      closing = true;
      status = "Suspending…";
      await captureThumbnail();
      try {
        await call("suspend", { device: id });
      } catch {}
      await win.destroy();
    });

    return () => {
      clearInterval(timer);
      unlistenDaemon.then((f) => f());
      unlistenClose.then((f) => f());
      rfb.close();
    };
  });
</script>

<svelte:window onkeydown={keydown} onkeyup={keyup} />

<div class="window">
  <div class="stage" bind:clientWidth={stageWidth} bind:clientHeight={stageHeight}>
    <div
      class="device"
      style:transform="translate(-50%, -50%) rotate({angle}deg) scale({factor})"
      onpointerdown={(e) => {
        if (e.target !== canvas || closing) return;
        try { canvas.setPointerCapture(e.pointerId); } catch {}
        rfb.pointer(...at(e), 1);
      }}
      onpointermove={(e) => { if (e.target === canvas && rfb?.buttons) rfb.pointer(...at(e), 1); }}
      onpointerup={(e) => { if (e.target === canvas) rfb.pointer(...at(e), 0); }}
      onpointercancel={(e) => { if (e.target === canvas) rfb.pointer(...at(e), 0); }}
      role="presentation"
    >
      <DeviceFrame bind:canvas {press} pixelated={scale !== "fit"} disabled={closing} />
    </div>
    {#if status}
      <div class="status">{status}</div>
    {/if}
    {#if toast}
      <div class="toast">{toast}</div>
    {/if}
  </div>

  <nav>
    <div class="group">
      {#if usb}
        <span class="usb" title="libimobiledevice reaches this device">
          <span class="dot"></span> USB
        </span>
      {/if}
    </div>
    <div class="group">
      <button title="Rotate Left (⌘←)" aria-label="Rotate Left" disabled={closing} onclick={() => rotate(1)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12a8 8 0 1 0 2.3-5.6M4 4v4h4" /></svg>
      </button>
      <button title="Rotate Right (⌘→)" aria-label="Rotate Right" disabled={closing} onclick={() => rotate(-1)}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4" /></svg>
      </button>
      <button title="Take Screenshot (⌘S)" aria-label="Take Screenshot" disabled={closing} onclick={screenshot}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 8h3l2-2.5h6L17 8h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></svg>
      </button>
    </div>
    <div class="group">
      <div class="segmented" role="group" aria-label="Size">
        <button class:on={scale === "fit"} title="Fit to Window (⌘3)" onclick={() => setScale("fit")}>Fit</button>
        <button class:on={scale === 1} title="Actual Size (⌘1)" onclick={() => setScale(1)}>1×</button>
        <button class:on={scale === 2} title="Double Size (⌘2)" onclick={() => setScale(2)}>2×</button>
      </div>
      <button title="More" aria-label="More" disabled={closing} onclick={showMenu}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="6" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="18" cy="12" r="1.6" /></svg>
      </button>
    </div>
  </nav>
</div>

{#if menu}
  <Menu {...menu} onclose={() => (menu = null)} />
{/if}
{#if confirm}
  <Confirm {...confirm} onclose={() => (confirm = null)} />
{/if}

<style>
  :global(body) { background: #101012; color-scheme: dark; }
  .window { height: 100%; display: flex; flex-direction: column; }
  .stage { flex: 1; min-height: 0; position: relative; overflow: hidden; }
  .device { position: absolute; left: 50%; top: 50%; transition: transform 0.35s cubic-bezier(0.3, 0.7, 0.2, 1); }
  .status, .toast {
    position: absolute; left: 50%; transform: translateX(-50%); white-space: nowrap;
    padding: 7px 14px; border-radius: 8px; background: rgba(36, 36, 40, 0.9); color: #eee; font-size: 12px;
    pointer-events: none;
  }
  .status { top: 50%; }
  .toast { bottom: 12px; }
  nav {
    height: 44px; flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 0 10px; border-top: 1px solid #222225; background: #18181b; color: #ddd;
  }
  .group { display: flex; align-items: center; gap: 4px; min-width: 0; }
  .group:first-child { flex: 1; }
  .group:last-child { flex: 1; justify-content: flex-end; }
  nav button {
    height: 26px; min-width: 30px; padding: 0 8px; display: grid; place-items: center;
    background: none; border: none; color: #ccc; border-radius: 6px; font-size: 12px;
  }
  nav button:hover:not(:disabled) { background: #2a2a2e; }
  .segmented { display: flex; background: #232326; border-radius: 7px; padding: 2px; }
  .segmented button { height: 22px; min-width: 32px; padding: 0 6px; }
  .segmented button.on { background: #3a3a3f; color: #fff; }
  .usb { display: flex; align-items: center; gap: 5px; font-size: 11px; color: #9a9aa0; white-space: nowrap; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: #30d158; }
</style>
