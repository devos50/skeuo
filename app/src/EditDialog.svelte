<script>
  import { invoke } from "@tauri-apps/api/core";
  import { call } from "./lib/daemon.svelte.js";

  let { device, onclose } = $props();

  const RUNNING = ["starting", "running", "suspending", "stopping"];
  // settings that change the emulator's command line (MACHINE_SETTINGS in bundle.py)
  const MACHINE = ["wifi", "audio"];
  // the settings, and the capability of the device's profile each needs (SETTING_CAPABILITIES in bundle.py)
  const SETTINGS = [
    { key: "wifi", capability: "wifi", label: "Wi-Fi" },
    { key: "audio", capability: "audio", label: "Audio" },
    { key: "usbmuxd", capability: "usbmux", label: "Access with libimobiledevice" },
  ];

  // svelte-ignore state_referenced_locally
  let name = $state(device.name);
  // svelte-ignore state_referenced_locally
  let settings = $state({ ...device.settings });
  let thumbnail = $state(null);      // what the preview shows
  let newThumbnail = $state(undefined); // undefined: unchanged, null: remove, else base64 PNG
  let error = $state(null);
  let ask = $state(null);            // the "discards the suspended state" question
  let saving = $state(false);
  let type = $state(null);           // the device's profile, from device_types
  let fileInput;

  // svelte-ignore state_referenced_locally
  call("device_types").then((result) => {
    type = result.device_types.find((t) => t.product === device.product) ?? null;
  }).catch((e) => (error = e.message || String(e)));

  const running = $derived(RUNNING.includes(device.state));
  const machineChanged = $derived(MACHINE.some((k) => settings[k] !== device.settings[k]));
  const shown = $derived(type ? SETTINGS.filter((s) => type.capabilities.includes(s.capability)) : []);
  // the shown settings that change the emulator's command line, for the notes: "Wi-Fi or audio"
  const machineNames = $derived(
    shown.filter((s) => MACHINE.includes(s.key)).map((s, i) => (i ? s.label.toLowerCase() : s.label)).join(" or ")
  );
  const fileManager = navigator.platform.startsWith("Mac") ? "Finder" : "File Manager";

  // the thumbnail as it was when the dialog opened
  // svelte-ignore state_referenced_locally
  invoke("thumbnail", { id: device.id }).then((bytes) => {
    if (bytes && bytes.byteLength) thumbnail = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
  });

  // any picture becomes a 320×480 PNG, cropped to fill like the screen
  async function chooseImage(file) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      const c = document.createElement("canvas");
      c.width = 320;
      c.height = 480;
      const s = Math.max(320 / img.naturalWidth, 480 / img.naturalHeight);
      const w = img.naturalWidth * s, h = img.naturalHeight * s;
      c.getContext("2d").drawImage(img, (320 - w) / 2, (480 - h) / 2, w, h);
      const data = c.toDataURL("image/png");
      newThumbnail = data.split(",")[1];
      thumbnail = data;
    } catch {
      error = "That file isn't a picture Skeuo can read.";
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function resetThumbnail() {
    newThumbnail = null;
    thumbnail = null;
  }

  async function save(discardState = false) {
    error = null;
    saving = true;
    try {
      const trimmed = name.trim();
      if (!trimmed) throw new Error("A device needs a name.");
      if (trimmed !== device.name) await call("rename", { device: device.id, name: trimmed });
      if (newThumbnail !== undefined) await call("set_thumbnail", { device: device.id, png: newThumbnail });
      const changes = Object.fromEntries(Object.entries(settings).filter(([k, v]) => v !== device.settings[k]));
      if (Object.keys(changes).length) {
        try {
          await call("update_settings", { device: device.id, settings: changes, discard_state: discardState });
        } catch (e) {
          if (e.code === "suspended") {
            ask = true;
            return;
          }
          throw e;
        }
      }
      onclose();
    } catch (e) {
      error = e.message || String(e);
    } finally {
      saving = false;
    }
  }

  const osName = (v) => (Number(v.split(".")[0]) >= 4 ? "iOS " : "iPhone OS ") + v;
  const date = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–");
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onclose()} />

<div class="backdrop">
  <form class="dialog" onsubmit={(e) => { e.preventDefault(); save(); }} aria-labelledby="edit-title">
    <h2 id="edit-title">Edit “{device.name}”</h2>

    <div class="top">
      <div class="thumb">
        <div class="screen">
          {#if thumbnail}<img src={thumbnail} alt="" />{:else}<span class="time">9:41</span>{/if}
        </div>
        <div class="thumb-buttons">
          <button type="button" onclick={() => fileInput.click()}>Choose…</button>
          <button type="button" onclick={resetThumbnail} disabled={!thumbnail}>Reset</button>
        </div>
        <input bind:this={fileInput} type="file" accept="image/*" hidden onchange={(e) => chooseImage(e.target.files[0])} />
      </div>

      <div class="fields">
        <label>
          <span>Name</span>
          <input bind:value={name} spellcheck="false" />
        </label>

        <div class="group">
          <span class="label">Settings</span>
          <div class="checks">
            {#each shown as s (s.key)}
              <label class="check">
                <input type="checkbox" bind:checked={settings[s.key]} disabled={running && MACHINE.includes(s.key)} /> {s.label}
              </label>
            {/each}
            {#if running && machineNames}
              <p class="note">Power the device off to change {machineNames}.</p>
            {:else if machineChanged && device.state === "suspended"}
              <p class="note">Changing {machineNames} discards the device's suspended state.</p>
            {/if}
          </div>
        </div>

        <dl>
          <dt>Device</dt><dd>{type?.name ?? device.product ?? "–"}{type && type.support !== "supported" ? " (experimental)" : ""}</dd>
          <dt>Version</dt><dd>{osName(device.version)} ({device.build})</dd>
          <dt>Activation</dt><dd>{device.activation === "device_certificate" ? "Device certificate from Apple" : "Skeuo"}</dd>
          <dt>Serial</dt><dd class="mono">{device.serial_number || "–"}</dd>
          <dt>UDID</dt><dd class="mono" title={device.udid}>{device.udid || "–"}</dd>
          <dt>Created</dt><dd>{date(device.created)}</dd>
          <dt>Location</dt>
          <dd><button type="button" class="link" onclick={() => invoke("reveal", { path: device.path })}>Show in {fileManager}</button></dd>
        </dl>
      </div>
    </div>

    {#if error}<p class="error">{error}</p>{/if}

    <div class="buttons">
      <button type="button" onclick={onclose}>Cancel</button>
      <button type="submit" class="primary" disabled={saving}>Save</button>
    </div>
  </form>
</div>

{#if ask}
  <div class="backdrop">
    <div class="dialog small" role="alertdialog">
      <h2>Discard the suspended state?</h2>
      <p class="muted">“{device.name}” is suspended. Changing {machineNames} means it can't resume: it boots fresh next time, and apps lose what they didn't save.</p>
      <div class="buttons">
        <button onclick={() => (ask = null)}>Cancel</button>
        <button class="primary" onclick={() => { ask = null; save(true); }}>Discard and Save</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.25); display: grid; place-items: center; z-index: 10; }
  .dialog {
    width: min(540px, calc(100% - 32px)); max-height: calc(100% - 32px); overflow: auto;
    padding: 20px 22px; border-radius: var(--radius); background: var(--surface);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3); display: grid; gap: 14px;
  }
  .dialog.small { width: min(380px, calc(100% - 32px)); gap: 10px; }
  h2 { font-size: 15px; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .top { display: flex; gap: 22px; align-items: flex-start; }
  .thumb { display: grid; gap: 10px; justify-items: center; flex: none; }
  .screen {
    width: 100px; aspect-ratio: 2 / 3; border-radius: 5px; overflow: hidden; display: grid; place-items: start center;
    background: radial-gradient(circle at 50% 30%, #3b5f8f, #10192a 70%); color: #fff;
    box-shadow: 0 0 0 6px #1a1a1c, 0 0 0 7px #3a3a3c; margin: 7px 0 4px;
  }
  .screen img { width: 100%; height: 100%; display: block; }
  .time { font-size: 22px; font-weight: 200; padding-top: 14px; }
  .thumb-buttons { display: flex; gap: 6px; }
  .thumb-buttons button { padding: 3px 8px; font-size: 12px; }
  .fields { flex: 1; min-width: 0; display: grid; gap: 12px; }
  label:not(.check) { display: grid; grid-template-columns: 70px 1fr; align-items: center; gap: 10px; }
  label > span, .label, dt { color: var(--muted); text-align: right; }
  input:not([type]) {
    font: inherit; color: var(--fg); background: var(--bg); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 8px; min-width: 0;
  }
  .group { display: grid; grid-template-columns: 70px 1fr; gap: 10px; }
  .checks { display: grid; gap: 5px; }
  .check { display: flex; gap: 8px; align-items: center; }
  .note { font-size: 12px; color: var(--muted); }
  dl { display: grid; grid-template-columns: 70px 1fr; gap: 4px 10px; margin: 0; font-size: 12px; }
  dd { margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mono { font-family: ui-monospace, monospace; font-size: 11px; }
  .link { border: none; background: none; padding: 0; color: var(--accent); font-size: 12px; }
  .link:hover:not(:disabled) { background: none; text-decoration: underline; }
  .error { color: var(--danger); }
  .buttons { display: flex; justify-content: flex-end; gap: 8px; }
</style>
