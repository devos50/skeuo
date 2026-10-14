<script module>
  // The frame in screen pixels (the screen is 320×480): a plain dark slab with a speaker slot, a round home
  // button and three side buttons. Our own drawing, not Apple's. The buttons stick out by EDGE.
  export const EDGE = 4;
  export const BODY = { width: 368, height: 652, radius: 52 };
  export const SCREEN = { x: 24, y: 86, width: 320, height: 480 };
  export const FRAME = { width: BODY.width + 2 * EDGE, height: BODY.height + 2 * EDGE };
</script>

<script>
  // press(name, down) for the hardware buttons; canvas is bound for the RFB client and touch
  let { canvas = $bindable(), press, pixelated = false, disabled = false } = $props();

  function button(name) {
    return {
      onpointerdown: (e) => {
        if (disabled) return;
        try { e.currentTarget.setPointerCapture(e.pointerId); } catch {}
        press(name, true);
      },
      onpointerup: () => !disabled && press(name, false),
      onpointercancel: () => !disabled && press(name, false),
    };
  }
</script>

<div class="frame" style:width="{FRAME.width}px" style:height="{FRAME.height}px">
  <!-- side buttons first, so that the body covers their inner half -->
  <button class="side sleep" style:left="{EDGE + 262}px" aria-label="Sleep/Wake" title="Sleep/Wake (⌘L)" {...button("power")}></button>
  <button class="side volume" style:top="{EDGE + 132}px" aria-label="Volume Up" title="Volume Up (⌘↑)" {...button("volup")}></button>
  <button class="side volume" style:top="{EDGE + 196}px" aria-label="Volume Down" title="Volume Down (⌘↓)" {...button("voldown")}></button>

  <div class="body" style:inset="{EDGE}px" style:border-radius="{BODY.radius}px">
    <span class="speaker"></span>
    <div
      class="glass"
      style:left="{SCREEN.x - 2}px"
      style:top="{SCREEN.y - 2}px"
      style:width="{SCREEN.width + 4}px"
      style:height="{SCREEN.height + 4}px"
    >
      <canvas bind:this={canvas} width={SCREEN.width} height={SCREEN.height} class:pixelated></canvas>
    </div>
    <button
      class="home"
      style:top="{SCREEN.y + SCREEN.height + 18}px"
      aria-label="Home"
      title="Home (⇧⌘H)"
      {...button("home")}
    ><span></span></button>
  </div>
</div>

<style>
  .frame { position: relative; }
  .body {
    position: absolute;
    background: linear-gradient(160deg, #303034, #141416 55%, #0c0c0d);
    box-shadow: inset 0 0 0 1.5px #3c3c40, inset 0 0 0 4px #0b0b0c, 0 10px 40px rgba(0, 0, 0, 0.45);
  }
  .speaker {
    position: absolute; left: 50%; top: 40px; width: 56px; height: 7px; margin-left: -28px;
    border-radius: 4px; background: #050505; box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.06);
  }
  .glass { position: absolute; padding: 2px; background: #000; border-radius: 3px; }
  canvas { display: block; width: 100%; height: 100%; background: #000; touch-action: none; cursor: default; }
  canvas.pixelated { image-rendering: pixelated; }
  button { position: absolute; padding: 0; border: none; font: inherit; }
  .home {
    left: 50%; width: 50px; height: 50px; margin-left: -25px; border-radius: 50%;
    background: radial-gradient(circle at 50% 35%, #232326, #111113);
    box-shadow: inset 0 0 0 1.5px #2e2e32, inset 0 1px 2px rgba(255, 255, 255, 0.05);
    display: grid; place-items: center;
  }
  .home span { width: 15px; height: 15px; border: 1.5px solid #4a4a4e; border-radius: 4px; }
  .home:active { background: #2a2a2e; }
  .side { background: linear-gradient(#4a4a4f, #2c2c30); }
  .side:active { filter: brightness(1.3); }
  .sleep { top: 0; width: 60px; height: 12px; border-radius: 4px 4px 0 0; }
  .volume { left: 0; width: 12px; height: 52px; border-radius: 4px 0 0 4px; }
</style>
