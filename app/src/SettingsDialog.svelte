<script>
  import { invoke } from "@tauri-apps/api/core";
  import { library, call, refresh, downloadIPSW } from "./lib/daemon.svelte.js";

  let { status, onstatus, onclose } = $props();

  let ipsws = $state([]);
  let error = $state(null);
  let notice = $state(null);
  let busy = $state(false);
  let bootroms = $state([]);         // the device profiles' bootroms, one per chip
  let bootromInput;

  const fileManager = navigator.platform.startsWith("Mac") ? "Finder" : "File Manager";
  const osName = (v) => (Number(v.split(".")[0]) >= 4 ? "iOS " : "iPhone OS ") + v;
  const mb = (bytes) => `${Math.round(bytes / 1e6)} MB`;

  async function loadIPSWs() {
    try {
      ipsws = (await call("ipsws")).ipsws.reverse();
    } catch (e) {
      error = e.message || String(e);
    }
  }
  loadIPSWs();

  call("device_types").then((result) => {
    const seen = new Map();
    for (const t of result.device_types) if (t.bootrom && !seen.has(t.bootrom.soc)) seen.set(t.bootrom.soc, t.bootrom);
    bootroms = [...seen.values()];
  }).catch((e) => (error = e.message || String(e)));
  const bootromNames = $derived(bootroms.map((b) => `${b.soc} SecureROM (${b.version})`).join(" or ") || "the SecureROM");

  async function changeLibrary() {
    error = null;
    const path = await invoke("pick_path", { kind: "folder" });
    if (!path) return;
    busy = true;
    try {
      onstatus(await invoke("set_library", { path }));
      await refresh();
      notice = "Skeuo now uses this library.";
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  async function replaceBootrom(file) {
    if (!file) return;
    error = null;
    try {
      const bytes = Array.from(new Uint8Array(await file.arrayBuffer()));
      onstatus(await invoke("import_bootrom", { bytes }));
      notice = "Devices now start from this boot ROM.";
    } catch (e) {
      error = String(e);
    } finally {
      bootromInput.value = "";
    }
  }

  async function removeBootrom() {
    error = null;
    try {
      onstatus(await invoke("remove_bootrom"));
      notice = "Devices now start their firmware directly.";
    } catch (e) {
      error = String(e);
    }
  }

  async function download(version) {
    error = null;
    await downloadIPSW(version);
    await loadIPSWs();
  }

  async function cancel(version) {
    const d = library.downloads[version];
    if (d?.request != null) await call("cancel", { request: d.request });
  }

  async function remove(version) {
    error = null;
    try {
      await call("delete_ipsw", { version });
    } catch (e) {
      error = e.message || String(e);
    }
    await loadIPSWs();
  }

  const running = $derived(!!library.running);
  const join = (...parts) => parts.join(status.data.includes("\\") ? "\\" : "/");
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onclose()} />

<div class="backdrop">
  <div class="dialog" role="dialog" aria-labelledby="settings-title">
    <h2 id="settings-title">Settings</h2>

    <section>
      <h3>Library</h3>
      <p class="muted">Where your devices are kept. Each device is a folder in it.</p>
      <div class="row">
        <code title={status.library}>{status.library}</code>
        <button onclick={() => invoke("reveal", { path: status.library })}>Show</button>
        <button onclick={changeLibrary} disabled={busy || running} title={running ? "Stop the running device first" : ""}>Change…</button>
      </div>
    </section>

    <section>
      <h3>Boot ROM <span class="muted small">(optional)</span></h3>
      <p class="muted">
        Devices start their firmware directly. If you have a copy of the {bootromNames}, they can start
        from it instead, like the real device. It takes effect the next time a device boots.
      </p>
      <div class="row">
        <span class="ok" class:muted={!status.bootrom}>{status.bootrom ? "Devices start from your boot ROM" : "Not used"}</span>
        <button onclick={() => bootromInput.click()} disabled={running} title={running ? "Stop the running device first" : ""}>{status.bootrom ? "Replace…" : "Choose…"}</button>
        {#if status.bootrom}
          <button onclick={removeBootrom} disabled={running} title={running ? "Stop the running device first" : ""}>Remove</button>
        {/if}
        <input bind:this={bootromInput} type="file" hidden onchange={(e) => replaceBootrom(e.target.files[0])} />
      </div>
    </section>

    <section>
      <h3>Firmware</h3>
      <p class="muted">Restore images downloaded from Apple. Devices don't need them after they are created.</p>
      <ul>
        {#each ipsws as v (v.version)}
          {@const d = library.downloads[v.version]}
          <li>
            <span class="name">{osName(v.version)} <span class="muted">({v.build})</span></span>
            {#if d}
              <span class="progress"><span style:width="{d.fraction * 100}%"></span></span>
              <span class="muted small">{Math.round(d.fraction * 100)}%</span>
              <button onclick={() => cancel(v.version)}>Cancel</button>
            {:else if v.cached}
              <span class="muted small">Downloaded, {mb(v.size)}</span>
              <button onclick={() => remove(v.version)}>Delete</button>
            {:else if v.downloadable}
              <span class="muted small">{v.partial ? `${mb(v.partial)} of ${mb(v.size)}` : mb(v.size)}</span>
              <button onclick={() => download(v.version)}>{v.partial ? "Resume" : "Download"}</button>
            {:else}
              <span class="muted small">Not offered by Apple; use your own IPSW</span>
            {/if}
          </li>
        {/each}
      </ul>
      <div class="row end">
        <button onclick={() => invoke("reveal", { path: join(status.data, "ipsw") })}>Show in {fileManager}</button>
      </div>
    </section>

    {#if error}<p class="error">{error}</p>{:else if notice}<p class="notice">{notice}</p>{/if}

    <div class="buttons">
      <button class="primary" onclick={onclose}>Done</button>
    </div>
  </div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.25); display: grid; place-items: center; z-index: 10; }
  .dialog {
    width: min(520px, calc(100% - 32px)); max-height: calc(100% - 32px); overflow: auto;
    padding: 20px 22px; border-radius: var(--radius); background: var(--surface);
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3); display: grid; gap: 16px;
  }
  h2 { font-size: 15px; margin: 0; }
  h3 { font-size: 13px; margin: 0 0 2px; }
  section { display: grid; gap: 6px; }
  section > p { font-size: 12px; }
  .row { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .row.end { justify-content: flex-end; }
  code {
    flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    font: 12px ui-monospace, monospace; padding: 5px 8px; border-radius: 6px; background: var(--bg);
  }
  .ok { flex: 1; }
  ul { list-style: none; margin: 0; padding: 0; border: 1px solid var(--line); border-radius: 8px; }
  li { display: flex; align-items: center; gap: 10px; padding: 7px 10px; min-height: 40px; }
  li + li { border-top: 1px solid var(--line); }
  .name { flex: 1; }
  .small { font-size: 12px; }
  li button { padding: 3px 10px; font-size: 12px; }
  .progress { width: 90px; height: 4px; border-radius: 2px; background: var(--surface-2); overflow: hidden; }
  .progress span { display: block; height: 100%; background: var(--accent); }
  .error { color: var(--danger); }
  .notice { color: var(--running); }
  .buttons { display: flex; justify-content: flex-end; }
</style>
