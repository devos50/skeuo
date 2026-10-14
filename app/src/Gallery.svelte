<script>
  import { invoke } from "@tauri-apps/api/core";
  import { library, connect, start, act } from "./lib/daemon.svelte.js";
  import DeviceCard from "./DeviceCard.svelte";
  import Menu from "./Menu.svelte";
  import Confirm from "./Confirm.svelte";

  let { library: path } = $props();
  let menu = $state(null);     // {x, y, items}
  let confirm = $state(null);  // {title, message, action, run}
  let selected = $state(null);

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

  function showMenu(e, device) {
    e.preventDefault();
    selected = device.id;
    const running = RUNNING.includes(device.state);
    const items = [];
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
    items.push({ label: `Show in ${fileManager}`, run: () => invoke("reveal", { path: device.path }) });
    menu = { x: e.clientX, y: e.clientY, items };
  }
</script>

<div class="window">
  <header>
    <div>
      <h1>Skeuo</h1>
      <p class="muted">{library.devices.length} {library.devices.length === 1 ? "device" : "devices"} in {path}</p>
    </div>
    {#if library.usb}
      <p class="usb" title="libimobiledevice tools reach the running device with USBMUXD_SOCKET_ADDRESS={library.usb.usbmuxd}">
        Connected to libimobiledevice
      </p>
    {/if}
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
        onselect={() => (selected = device.id)}
        onopen={() => open(device)}
        onmenu={(e) => showMenu(e, device)}
      />
    {:else}
      <div class="empty">
        <p>No devices yet.</p>
        <p class="muted">Create one with <code>python3 -m skeuo restore</code> for now; creating devices in the app comes next.</p>
      </div>
    {/each}
  </main>
</div>

{#if menu}
  <Menu {...menu} onclose={() => (menu = null)} />
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
  .banner {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    margin: 12px 24px 0; padding: 8px 8px 8px 14px; border-radius: 8px;
    background: color-mix(in srgb, var(--danger) 12%, var(--surface)); color: var(--fg);
  }
  main {
    flex: 1; overflow: auto; padding: 24px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 24px; align-content: start;
  }
  .empty { grid-column: 1 / -1; display: grid; gap: 6px; justify-items: center; padding: 64px 0; text-align: center; }
  code { font: 12px ui-monospace, monospace; }
</style>
