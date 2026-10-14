<script>
  let { x, y, items, onclose } = $props();
  let width = $state(0);
  let height = $state(0);
  // kept inside the window
  const left = $derived(Math.max(4, Math.min(x, innerWidth - width - 4)));
  const top = $derived(Math.max(4, Math.min(y, innerHeight - height - 4)));

  function choose(item) {
    onclose();
    item.run();
  }
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onclose()} onblur={onclose} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="backdrop" onclick={onclose} oncontextmenu={(e) => { e.preventDefault(); onclose(); }}></div>
<div class="menu" role="menu" bind:clientWidth={width} bind:clientHeight={height} style:left="{left}px" style:top="{top}px">
  {#each items as item}
    {#if item.separator}
      <hr />
    {:else}
      <button role="menuitem" disabled={item.disabled} onclick={() => choose(item)}>{item.label}</button>
    {/if}
  {/each}
</div>

<style>
  .backdrop { position: fixed; inset: 0; }
  .menu {
    position: fixed; min-width: 190px; padding: 5px; border-radius: 9px;
    background: color-mix(in srgb, var(--surface) 92%, transparent); backdrop-filter: blur(20px);
    border: 1px solid var(--line); box-shadow: 0 8px 30px rgba(0, 0, 0, 0.2);
    display: grid;
  }
  button {
    text-align: left; border: none; background: none; border-radius: 5px; padding: 4px 10px;
  }
  button:hover:not(:disabled) { background: var(--accent); color: var(--accent-fg); }
  hr { border: none; border-top: 1px solid var(--line); margin: 4px 6px; }
</style>
