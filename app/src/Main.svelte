<script>
  import { invoke } from "@tauri-apps/api/core";
  import FirstRun from "./FirstRun.svelte";
  import Gallery from "./Gallery.svelte";

  let status = $state(null);

  async function load() {
    status = await invoke("status");
  }
  load();
</script>

{#if !status}
  <!-- loading -->
{:else if !status.bootrom}
  <FirstRun onimported={(s) => (status = s)} />
{:else if !status.daemon}
  <div class="problem">
    <h1>Skeuo can't start</h1>
    <p class="muted">{status.error || "The Skeuo daemon isn't running."}</p>
  </div>
{:else}
  <Gallery library={status.library} />
{/if}

<style>
  .problem { padding: 48px; display: grid; gap: 8px; }
</style>
