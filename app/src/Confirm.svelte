<script>
  let { title, message, action, run, onclose } = $props();
</script>

<svelte:window onkeydown={(e) => e.key === "Escape" && onclose()} />

<div class="backdrop">
  <div class="dialog" role="alertdialog" aria-labelledby="confirm-title">
    <h2 id="confirm-title">{title}</h2>
    <p class="muted">{message}</p>
    <div class="buttons">
      <button onclick={onclose}>Cancel</button>
      <button class="primary" onclick={() => { onclose(); run(); }}>{action}</button>
    </div>
  </div>
</div>

<style>
  .backdrop { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.25); display: grid; place-items: center; }
  .dialog {
    width: min(380px, calc(100% - 32px)); padding: 20px; border-radius: var(--radius);
    background: var(--surface); box-shadow: 0 12px 40px rgba(0, 0, 0, 0.3); display: grid; gap: 10px;
  }
  h2 { font-size: 15px; margin: 0; }
  .buttons { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
</style>
