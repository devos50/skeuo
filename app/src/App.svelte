<script>
  import Main from "./Main.svelte";
  import DeviceWindow from "./DeviceWindow.svelte";

  // device windows open index.html?device=<id>&ws=<port> (see open_device_window in lib.rs)
  const params = new URLSearchParams(location.search);
  const device = params.get("device");
</script>

{#if device}
  <DeviceWindow id={device} websocket={Number(params.get("ws"))} />
{:else}
  <Main />
{/if}
