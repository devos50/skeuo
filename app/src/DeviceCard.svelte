<script>
  import { invoke } from "@tauri-apps/api/core";

  let { device, selected, blocked, thumbnailVersion, onselect, onopen, onmenu } = $props();
  let thumbnail = $state(null);

  const BADGES = {
    running: "Running", starting: "Starting…", suspending: "Suspending…", stopping: "Powering off…",
    suspended: "Suspended", off: null, creating: "Creating…", incomplete: "Incomplete",
  };

  // the thumbnail comes from the bundle through Rust; reload it when the daemon reports a new one
  $effect(() => {
    thumbnailVersion;
    let url = null;
    let cancelled = false;
    invoke("thumbnail", { id: device.id }).then((bytes) => {
      if (cancelled || !bytes || !bytes.byteLength) return;
      url = URL.createObjectURL(new Blob([bytes], { type: "image/png" }));
      thumbnail = url;
    });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  });

  const label = $derived(
    `${device.build ? (Number(device.version.split(".")[0]) >= 4 ? "iOS " : "iPhone OS ") : ""}${device.version || ""}`
  );
</script>

<div class="card"
  role="button"
  aria-label={device.name}
  class:selected
  class:blocked
  tabindex="0"
  title={device.in_use ? "In use by another Skeuo process" : blocked ? "Another device is running" : ""}
  onclick={(e) => { e.stopPropagation(); onselect(); }}
  ondblclick={onopen}
  onkeydown={(e) => e.key === "Enter" && onopen()}
  oncontextmenu={onmenu}
>
  <div class="screen">
    {#if thumbnail}
      <img src={thumbnail} alt="" draggable="false" />
    {:else}
      <!-- until the app has shown the device once: a plain lock screen of our own -->
      <div class="placeholder">
        <span class="time">9:41</span>
        <span class="slider">slide to unlock</span>
      </div>
    {/if}
    {#if BADGES[device.state]}
      <span class="badge {device.state}">{BADGES[device.state]}</span>
    {/if}
  </div>
  <div class="caption">
    <p class="name">{device.name}</p>
    <p class="muted">{label}</p>
  </div>
</div>

<style>
  .card { display: grid; gap: 10px; justify-items: center; outline: none; }
  .screen {
    position: relative; width: 120px; aspect-ratio: 2 / 3; border-radius: 6px; overflow: hidden;
    background: #000; box-shadow: 0 0 0 8px #1a1a1c, 0 0 0 9px #3a3a3c, var(--shadow);
    margin: 9px 0 0;
  }
  .selected .screen { box-shadow: 0 0 0 8px #1a1a1c, 0 0 0 9px #3a3a3c, 0 0 0 12px var(--accent), var(--shadow); }
  .blocked .screen { opacity: 0.55; }
  img { width: 100%; height: 100%; display: block; image-rendering: auto; }
  .placeholder {
    height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: space-between;
    padding: 18px 8px 14px; color: #fff;
    background: radial-gradient(circle at 50% 30%, #3b5f8f, #10192a 70%);
  }
  .time { font-size: 26px; font-weight: 200; }
  .slider { font-size: 8px; padding: 3px 8px; border-radius: 4px; background: rgba(0, 0, 0, 0.5); color: #ccc; }
  .badge {
    position: absolute; left: 50%; bottom: 8px; transform: translateX(-50%); white-space: nowrap;
    font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 999px;
    background: rgba(0, 0, 0, 0.7); color: #fff;
  }
  .badge.running { background: var(--running); color: #fff; }
  .badge.suspended { background: var(--suspended); color: #fff; }
  .badge.incomplete { background: var(--danger); }
  .caption { text-align: center; max-width: 100%; }
  .name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .caption .muted { font-size: 12px; }
  .selected .name { color: var(--accent); }
</style>
