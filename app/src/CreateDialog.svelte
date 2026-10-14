<script>
  import { invoke } from "@tauri-apps/api/core";
  import { call, create } from "./lib/daemon.svelte.js";

  let { onclose } = $props();

  let types = $state([]);
  let product = $state("");
  let name = $state("");
  let version = $state("");
  let ipsw = $state(null);            // a local IPSW instead of a download
  let activation = $state("skeuo");   // or "certificate"
  let certificate = $state(null);
  let settings = $state({ wifi: true, audio: true, usbmuxd: true });
  let norImages = $state(null);
  let advanced = $state(false);
  let error = $state(null);

  const type = $derived(types.find((t) => t.product === product));
  // newest first
  const versions = $derived(type ? [...type.versions].reverse() : []);
  const selected = $derived(versions.find((v) => v.version === version));
  const osName = (v) => (Number(v.split(".")[0]) >= 4 ? "iOS " : "iPhone OS ") + v;
  const defaultName = $derived(type && version ? `${type.name.replace(/ \(.*\)$/, "")} (${osName(version)})` : "");
  // a version Apple doesn't serve needs a local IPSW
  const needsFile = $derived(selected && !selected.cached && !selected.downloadable);
  const ready = $derived(
    !!selected && (!needsFile || ipsw) && (activation === "skeuo" || certificate)
  );

  function source(v) {
    if (v.cached) return "downloaded";
    if (v.downloadable) return `download ${Math.round(v.size / 1e6)} MB from Apple`;
    return "needs an IPSW file";
  }

  call("device_types").then((result) => {
    types = result.device_types;
    product = types[0]?.product ?? "";
    const firstUsable = [...(types[0]?.versions ?? [])].reverse().find((v) => v.cached || v.downloadable);
    version = firstUsable?.version ?? "";
  }).catch((e) => (error = e.message || String(e)));

  async function pick(kind) {
    return invoke("pick_path", { kind });
  }

  function submit(e) {
    e.preventDefault();
    if (!ready) return;
    const params = { product, name: name.trim() || defaultName, version, settings: { ...settings } };
    if (ipsw) params.ipsw = ipsw;
    if (activation === "certificate") params.device_certificate = certificate;
    if (norImages) params.nor_images = norImages;
    create(params); // the card shows the progress
    onclose();
  }

  const base = (path) => path?.split(/[\\/]/).pop();
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onclose()} />

<div class="backdrop">
  <form class="dialog" onsubmit={submit} aria-labelledby="create-title">
    <h2 id="create-title">New Device</h2>

    <label>
      <span>Device</span>
      <select bind:value={product}>
        {#each types as t}
          <option value={t.product}>{t.name}</option>
        {/each}
      </select>
    </label>

    <label>
      <span>Name</span>
      <input bind:value={name} placeholder={defaultName} spellcheck="false" />
    </label>

    <label>
      <span>Version</span>
      <select bind:value={version} onchange={() => (ipsw = null)}>
        {#each versions as v}
          <option value={v.version}>{osName(v.version)} ({v.build}), {source(v)}</option>
        {/each}
      </select>
    </label>

    {#if needsFile || ipsw}
      <div class="row">
        <span>IPSW</span>
        <div class="file">
          <button type="button" onclick={async () => (ipsw = (await pick("ipsw")) ?? ipsw)}>Choose…</button>
          <span class="muted">{ipsw ? base(ipsw) : `Apple doesn't offer ${osName(version)} for download any more`}</span>
        </div>
      </div>
    {/if}

    <fieldset>
      <legend>Activation</legend>
      <label class="check">
        <input type="radio" bind:group={activation} value="skeuo" />
        <span>Skeuo's own <span class="muted">(recommended)</span></span>
      </label>
      <label class="check">
        <input type="radio" bind:group={activation} value="certificate" />
        <span>A device certificate from Apple</span>
      </label>
      {#if activation === "certificate"}
        <div class="file indent">
          <button type="button" onclick={async () => (certificate = (await pick("certificate")) ?? certificate)}>Choose…</button>
          <span class="muted">{certificate ? base(certificate) : "a PEM certificate, or a device's pod_record.plist"}</span>
        </div>
      {/if}
    </fieldset>

    <details bind:open={advanced}>
      <summary>Advanced</summary>
      <div class="advanced">
        <label class="check"><input type="checkbox" bind:checked={settings.wifi} /> Wi-Fi</label>
        <label class="check"><input type="checkbox" bind:checked={settings.audio} /> Audio</label>
        <label class="check"><input type="checkbox" bind:checked={settings.usbmuxd} /> Access with libimobiledevice</label>
        <div class="file">
          <button type="button" onclick={async () => (ipsw = (await pick("ipsw")) ?? ipsw)}>Use an IPSW File…</button>
          {#if ipsw}<span class="muted">{base(ipsw)}</span>{/if}
        </div>
        <div class="file">
          <button type="button" onclick={async () => (norImages = (await pick("folder")) ?? norImages)}>NOR Images…</button>
          <span class="muted">{norImages ? base(norImages) : "only for extracted IPSWs without all_flash"}</span>
        </div>
      </div>
    </details>

    {#if error}<p class="error">{error}</p>{/if}

    <div class="buttons">
      <button type="button" onclick={onclose}>Cancel</button>
      <button type="submit" class="primary" disabled={!ready}>Create</button>
    </div>
  </form>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.25); display: grid; place-items: center; z-index: 10; }
  .dialog {
    width: min(460px, calc(100% - 32px)); max-height: calc(100% - 32px); overflow: auto;
    padding: 20px 22px; border-radius: var(--radius); background: var(--surface);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3); display: grid; gap: 12px;
  }
  h2 { font-size: 15px; margin: 0 0 4px; }
  label, .row { display: grid; grid-template-columns: 76px 1fr; align-items: center; gap: 10px; }
  label > span:first-child, .row > span:first-child { color: var(--muted); text-align: right; }
  input:not([type]), select {
    font: inherit; color: var(--fg); background: var(--bg); border: 1px solid var(--line);
    border-radius: 6px; padding: 5px 8px; min-width: 0;
  }
  fieldset { border: none; margin: 0; padding: 0 0 0 86px; display: grid; gap: 6px; }
  legend { float: left; margin-left: -86px; width: 76px; text-align: right; color: var(--muted); padding: 0; }
  .check { display: flex; gap: 8px; align-items: center; grid-template-columns: none; }
  .file { display: flex; gap: 10px; align-items: center; min-width: 0; }
  .file .muted { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
  .indent { padding-left: 24px; }
  details { padding-left: 86px; }
  summary { color: var(--muted); }
  .advanced { display: grid; gap: 8px; padding-top: 8px; }
  .error { color: var(--danger); }
  .buttons { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>
