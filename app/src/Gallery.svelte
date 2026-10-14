<script>
  import { invoke } from "@tauri-apps/api/core";
  import { library, connect, start, act, cancelCreate } from "./lib/daemon.svelte.js";
  import CreateDialog from "./CreateDialog.svelte";
  import EditDialog from "./EditDialog.svelte";
  import SettingsDialog from "./SettingsDialog.svelte";
  import DeviceCard from "./DeviceCard.svelte";
  import Menu from "./Menu.svelte";
  import Confirm from "./Confirm.svelte";

  let { status, onstatus } = $props();
  const path = $derived(status.library);
  let menu = $state(null);     // {x, y, items}
  let confirm = $state(null);  // {title, message, action, run}
  let selected = $state(null);
  let creating = $state(false);
  let editing = $state(null);   // the id of the device in the Edit dialog
  let settingsOpen = $state(false);
  const editingDevice = $derived(library.devices.find((d) => d.id === editing));

  connect().catch((e) => (library.error = e.message || String(e)));

  const RUNNING = ["starting", "running", "suspending", "stopping"];
  const fileManager = navigator.platform.startsWith("Mac") ? "Finder" : "File Manager";

  function canStart(device) {
    return ["off", "suspended"].includes(device.state) && !library.running && !device.in_use;
  }

  function open(device) {
    if (RUNNING.includes(device.state)) start(device.id); // brings its window forward
    else if (canStart(device)) start(device.id);
  }

  function powerOff(device) {
    confirm = {
      title: `Power off “${device.name}”?`,
      message: device.state === "suspended"
        ? "Its suspended state is discarded, like holding the power button on a device. Apps that were open lose what they didn't save."
        : "It shuts down at once, like pulling the battery. Apps lose what they didn't save.",
      action: "Power Off",
      run: () => act("power_off", device.id),
    };
  }

  function remove(device) {
    confirm = {
      title: `Remove “${device.name}”?`,
      message: "The device and everything on it move to the Trash. You can put it back from there.",
      action: "Move to Trash",
      run: () => act("remove", device.id),
    };
  }

  function showMenu(e, device) {
    e.preventDefault();
    selected = device.id;
    const running = RUNNING.includes(device.state);
    const items = [];
    if (device.state === "creating") {
      const downloading = library.progress[device.id]?.phase === "download";
      items.push({ label: "Cancel Download", disabled: !downloading, run: () => cancelCreate(device.id) });
      menu = { x: e.clientX, y: e.clientY, items };
      return;
    }
    if (device.state === "incomplete") {
      items.push({ label: "Move to Trash…", run: () => remove(device) });
      items.push({ separator: true });
      items.push({ label: `Show in ${fileManager}`, run: () => invoke("reveal", { path: device.path }) });
      menu = { x: e.clientX, y: e.clientY, items };
      return;
    }
    if (running) items.push({ label: "Show Window", run: () => start(device.id) });
    else items.push({
      label: device.state === "suspended" ? "Resume" : "Start",
      disabled: !canStart(device),
      run: () => start(device.id),
    });
    if (device.state === "suspended") {
      items.push({ label: "Restart (Cold Boot)", disabled: !canStart(device), run: () => start(device.id, true) });
    }
    if (running) items.push({ label: "Suspend", disabled: device.state !== "running", run: () => act("suspend", device.id) });
    items.push({
      label: "Power Off…",
      disabled: !(device.state === "running" || device.state === "suspended") || device.in_use,
      run: () => powerOff(device),
    });
    items.push({ separator: true });
    items.push({ label: "Edit…", run: () => (editing = device.id) });
    items.push({ label: `Show in ${fileManager}`, run: () => invoke("reveal", { path: device.path }) });
    items.push({ label: "Move to Trash…", disabled: running || device.in_use, run: () => remove(device) });
    menu = { x: e.clientX, y: e.clientY, items };
  }
</script>

<div class="window">
  <header>
    <div>
      <h1>Skeuo</h1>
      <p class="muted">{library.devices.length} {library.devices.length === 1 ? "device" : "devices"} in {path}</p>
    </div>
    <div class="tools">
    {#if library.usb}
      <p class="usb" title="libimobiledevice tools reach the running device with USBMUXD_SOCKET_ADDRESS={library.usb.usbmuxd}">
        Connected to libimobiledevice
      </p>
    {/if}
    <button class="add" title="Settings" aria-label="Settings" onclick={() => (settingsOpen = true)}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>
    </button>
    <button class="add" title="New Device" aria-label="New Device" onclick={() => (creating = true)}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
    </button>
    </div>
  </header>

  {#if library.error}
    <div class="banner" role="alert">
      <span>{library.error}</span>
      <button onclick={() => (library.error = null)}>Dismiss</button>
    </div>
  {/if}

  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
  <main onclick={() => (selected = null)}>
    {#each library.devices as device (device.id)}
      <DeviceCard
        {device}
        selected={selected === device.id}
        blocked={!RUNNING.includes(device.state) && !canStart(device)}
        thumbnailVersion={library.thumbnails[device.id] || 0}
        progress={library.progress[device.id]}
        onselect={() => (selected = device.id)}
        onopen={() => open(device)}
        onmenu={(e) => showMenu(e, device)}
      />
    {/each}
    <button class="new" onclick={(e) => { e.stopPropagation(); creating = true; }}>
      <span class="plus" aria-hidden="true">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
      </span>
      <span>New Device</span>
    </button>
  </main>
</div>

{#if menu}
  <Menu {...menu} onclose={() => (menu = null)} />
{/if}
{#if editingDevice}
  <EditDialog device={editingDevice} onclose={() => (editing = null)} />
{/if}
{#if settingsOpen}
  <SettingsDialog {status} {onstatus} onclose={() => (settingsOpen = false)} />
{/if}
{#if creating}
  <CreateDialog onclose={() => (creating = false)} />
{/if}
{#if confirm}
  <Confirm {...confirm} onclose={() => (confirm = null)} />
{/if}

<style>
  .window { height: 100%; display: flex; flex-direction: column; }
  header {
    display: flex; align-items: flex-end; justify-content: space-between; gap: 16px;
    padding: 20px 24px 12px; border-bottom: 1px solid var(--line);
  }
  header p { font-size: 12px; }
  .usb { color: var(--running); }
  .tools { display: flex; align-items: center; gap: 14px; }
  .add { width: 30px; height: 26px; padding: 0; display: grid; place-items: center; }
  .new {
    display: grid; justify-items: center; align-content: start; gap: 10px; padding: 0;
    background: none; border: none; color: var(--muted);
  }
  .new:hover:not(:disabled) { background: none; color: var(--accent); }
  .plus {
    width: 120px; aspect-ratio: 2 / 3; margin-top: 9px; display: grid; place-items: center;
    border: 1.5px dashed color-mix(in srgb, var(--fg) 25%, transparent); border-radius: 14px;
  }
  .new:hover .plus { border-color: var(--accent); }
  .banner {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    margin: 12px 24px 0; padding: 8px 8px 8px 14px; border-radius: 8px;
    background: color-mix(in srgb, var(--danger) 12%, var(--surface)); color: var(--fg);
  }
  main {
    flex: 1; min-height: 0; overflow: auto; padding: 24px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 24px; align-content: start;
  }
</style>
