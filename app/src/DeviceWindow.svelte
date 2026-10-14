<script>
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { call } from "./lib/daemon.svelte.js";
  import { RFB } from "./lib/rfb.js";

  let { id, websocket } = $props();

  // the device's buttons: X keysym and PC scancode of the key the emulator maps to them (ipod_touch_2g.c), and the
  // physical key that presses them
  const BUTTONS = {
    home:    { keysym: 0x68, scancode: 0x23, code: "KeyH", label: "Home" },
    power:   { keysym: 0x70, scancode: 0x19, code: "KeyP", label: "Sleep/Wake" },
    voldown: { keysym: 0x2d, scancode: 0x0c, code: "Minus", label: "Volume Down" },
    volup:   { keysym: 0x3d, scancode: 0x0d, code: "Equal", label: "Volume Up" },
    rotate:  { keysym: 0x72, scancode: 0x13, code: "KeyR", label: "Rotate" },
  };
  const BY_CODE = Object.fromEntries(Object.entries(BUTTONS).map(([name, b]) => [b.code, name]));
  // iOS reads the buttons on an interrupt; a press released at once can be over before it looks
  const MIN_PRESS = 100;
  const THUMBNAIL_EVERY = 10000;

  let canvas;
  let rfb;
  let status = $state("Connecting…");
  let closing = $state(false);
  const pressedAt = {};
  const held = new Set();
  const win = getCurrentWindow();

  function press(name, down) {
    const b = BUTTONS[name];
    if (down) {
      pressedAt[name] = performance.now();
      rfb?.key(b.keysym, b.scancode, true);
    } else {
      const wait = MIN_PRESS - (performance.now() - (pressedAt[name] || 0));
      setTimeout(() => rfb?.key(b.keysym, b.scancode, false), Math.max(0, wait));
    }
  }

  function keydown(e) {
    const name = BY_CODE[e.code];
    if (!name || e.metaKey || e.ctrlKey || e.altKey) return;
    e.preventDefault();
    if (held.has(name)) return;
    held.add(name);
    press(name, true);
  }

  function keyup(e) {
    const name = BY_CODE[e.code];
    if (name && held.delete(name)) press(name, false);
  }

  // touch: the canvas in framebuffer pixels
  function at(e) {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * rfb.width / r.width, (e.clientY - r.top) * rfb.height / r.height];
  }

  // the gallery thumbnail: the last frame with the screen lit, uploaded when it changes and when the window closes
  const probe = document.createElement("canvas");
  probe.width = 16;
  probe.height = 24;
  let lastSample = "";
  let lastLit = null;

  function sampleLit() {
    const ctx = probe.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(canvas, 0, 0, probe.width, probe.height);
    const px = ctx.getImageData(0, 0, probe.width, probe.height).data;
    let sum = 0;
    for (let i = 0; i < px.length; i += 4) sum += px[i] + px[i + 1] + px[i + 2];
    return { lit: sum / (px.length / 4) / 3 > 12, sample: Array.from(px.filter((_, i) => i % 16 === 0)).join() };
  }

  async function captureThumbnail() {
    if (!rfb?.width) return;
    const { lit, sample } = sampleLit();
    if (!lit || sample === lastSample) return;
    lastSample = sample;
    lastLit = canvas.toDataURL("image/png").split(",")[1];
    try {
      await call("set_thumbnail", { device: id, png: lastLit });
    } catch {}
  }

  onMount(() => {
    rfb = new RFB(`ws://127.0.0.1:${websocket}`, canvas);
    rfb.addEventListener("connect", () => (status = null));
    rfb.addEventListener("disconnect", () => { if (!closing) status = "The device's screen disconnected."; });
    rfb.addEventListener("error", () => (status = "Can't reach the device's screen."));

    call("list").then(({ devices }) => {
      const device = devices.find((d) => d.id === id);
      if (device) win.setTitle(device.name);
    });

    const timer = setInterval(captureThumbnail, THUMBNAIL_EVERY);

    // closing the window suspends the device, as closing a laptop does
    const unlisten = win.onCloseRequested(async (event) => {
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
      unlisten.then((f) => f());
      rfb.close();
    };
  });
</script>

<svelte:window onkeydown={keydown} onkeyup={keyup} />

<div class="window">
  <div class="stage">
    <canvas
      bind:this={canvas}
      width="320"
      height="480"
      onpointerdown={(e) => { canvas.setPointerCapture(e.pointerId); rfb.pointer(...at(e), 1); }}
      onpointermove={(e) => { if (rfb.buttons) rfb.pointer(...at(e), 1); }}
      onpointerup={(e) => rfb.pointer(...at(e), 0)}
      onpointercancel={(e) => rfb.pointer(...at(e), 0)}
    ></canvas>
    {#if status}
      <div class="status">{status}</div>
    {/if}
  </div>

  <nav>
    {#each Object.entries(BUTTONS) as [name, b]}
      <button
        title="{b.label} ({b.code.replace('Key', '').replace('Minus', '−').replace('Equal', '=')})"
        aria-label={b.label}
        disabled={closing}
        onpointerdown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); press(name, true); }}
        onpointerup={() => press(name, false)}
        onpointercancel={() => press(name, false)}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          {#if name === "home"}<rect x="6" y="6" width="12" height="12" rx="3.5" />
          {:else if name === "power"}<path d="M12 3v8M7.5 6.5a7 7 0 1 0 9 0" />
          {:else if name === "voldown"}<path d="M4 10h3l4-3v10l-4-3H4zM15 12h5" />
          {:else if name === "volup"}<path d="M4 10h3l4-3v10l-4-3H4zM15 12h5M17.5 9.5v5" />
          {:else}<path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4" />{/if}
        </svg>
      </button>
    {/each}
  </nav>
</div>

<style>
  :global(body) { background: #0b0b0c; }
  .window { height: 100%; display: flex; flex-direction: column; }
  .stage { flex: 1; min-height: 0; display: grid; place-items: center; position: relative; padding: 12px; }
  canvas {
    max-width: 100%; max-height: 100%; aspect-ratio: 2 / 3; height: 100%; object-fit: contain;
    background: #000; border-radius: 3px; touch-action: none; image-rendering: auto;
    box-shadow: 0 0 0 1px #2a2a2c;
  }
  .status {
    position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
    padding: 8px 14px; border-radius: 8px; background: rgba(30, 30, 32, 0.85); color: #eee; font-size: 13px;
  }
  nav { display: flex; justify-content: center; gap: 6px; padding: 8px 12px 12px; }
  nav button {
    width: 40px; height: 32px; padding: 0; display: grid; place-items: center;
    background: #1f1f22; color: #ddd; border-color: #333;
  }
  nav button:hover:not(:disabled) { background: #2c2c30; }
  nav button:active { background: #3a3a3e; }
</style>
