<script>
  import { invoke } from "@tauri-apps/api/core";

  let { onimported } = $props();
  let error = $state(null);
  let busy = $state(false);
  let over = $state(false);
  let input;

  async function use(file) {
    if (!file) return;
    error = null;
    busy = true;
    try {
      const bytes = Array.from(new Uint8Array(await file.arrayBuffer()));
      onimported(await invoke("import_bootrom", { bytes }));
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  function drop(e) {
    e.preventDefault();
    over = false;
    use(e.dataTransfer.files[0]);
  }
</script>

<main>
  <div class="intro">
    <h1>Welcome to Skeuo</h1>
    <p class="muted">
      Skeuo runs classic iPhone OS on an emulated iPod touch (2nd generation). The emulator starts from the
      device's boot ROM, which is Apple's code, so Skeuo can't include it. Choose your copy of the S5L8720 bootrom
      (SecureROM, iBoot-240.4, 64 KB) to continue. Skeuo checks it and keeps a copy.
    </p>
  </div>

  <div
    class="drop"
    class:over
    role="button"
    tabindex="0"
    ondragover={(e) => { e.preventDefault(); over = true; }}
    ondragleave={() => (over = false)}
    ondrop={drop}
    onclick={() => input.click()}
    onkeydown={(e) => e.key === "Enter" && input.click()}
  >
    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
      <rect x="5" y="3" width="14" height="18" rx="2" />
      <path d="M9 8h6M9 11h6M9 14h3" />
    </svg>
    <p>{busy ? "Checking…" : "Drop the bootrom here, or click to choose it"}</p>
  </div>
  <input bind:this={input} type="file" hidden onchange={(e) => use(e.target.files[0])} />

  {#if error}
    <p class="error">{error}</p>
  {/if}
</main>

<style>
  main { max-width: 520px; margin: 0 auto; padding: 64px 24px; display: grid; gap: 24px; }
  .intro { display: grid; gap: 10px; }
  .drop {
    display: grid; justify-items: center; gap: 10px; padding: 40px 24px;
    border: 1.5px dashed color-mix(in srgb, var(--fg) 25%, transparent); border-radius: var(--radius); background: var(--surface);
    color: var(--muted); text-align: center;
  }
  .drop:hover, .drop.over { border-color: var(--accent); color: var(--fg); }
  .error { color: var(--danger); }
</style>
