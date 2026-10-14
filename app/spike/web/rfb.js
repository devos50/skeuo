// A small RFB (VNC) client for QEMU's VNC server over its WebSocket: no authentication (the server only listens on
// 127.0.0.1), raw and CopyRect encodings, QEMU's absolute pointer and its extended key events (scancodes, so the
// host's keyboard layout doesn't matter). At 320x480 raw updates are at most 600 KB, which is nothing on loopback.

const ENC_RAW = 0;
const ENC_COPYRECT = 1;
const ENC_DESKTOP_SIZE = -223;
const ENC_QEMU_POINTER_MOTION = -257;
const ENC_QEMU_EXT_KEY = -258;

export class RFB extends EventTarget {
  constructor(url, canvas) {
    super();
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.width = 0;
    this.height = 0;
    this.extKeys = false;
    this.absolute = true;
    this.buttons = 0;
    this.stats = { updates: 0, rects: 0, bytes: 0, lastLatency: 0, requestedAt: 0 };
    this.chunks = [];
    this.have = 0;
    this.parser = this.protocol();
    this.need = this.parser.next().value;
    this.ws = new WebSocket(url, ["binary"]);
    this.ws.binaryType = "arraybuffer";
    this.ws.onmessage = (e) => this.receive(new Uint8Array(e.data));
    this.ws.onclose = (e) => this.dispatchEvent(new CustomEvent("disconnect", { detail: e }));
    this.ws.onerror = () => this.dispatchEvent(new CustomEvent("error", { detail: "WebSocket error" }));
  }

  close() {
    this.ws.close();
  }

  // incoming bytes go to the protocol generator, which yields how many it needs next
  receive(data) {
    this.stats.bytes += data.length;
    this.chunks.push(data);
    this.have += data.length;
    while (this.need !== undefined && this.have >= this.need) {
      const bytes = this.take(this.need);
      const step = this.parser.next(bytes);
      this.need = step.done ? undefined : step.value;
    }
  }

  take(n) {
    const out = new Uint8Array(n);
    let off = 0;
    while (off < n) {
      const chunk = this.chunks[0];
      const len = Math.min(chunk.length, n - off);
      out.set(chunk.subarray(0, len), off);
      off += len;
      if (len === chunk.length) this.chunks.shift();
      else this.chunks[0] = chunk.subarray(len);
    }
    this.have -= n;
    return out;
  }

  send(bytes) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(bytes);
  }

  *protocol() {
    const version = new TextDecoder().decode(yield 12);
    if (!version.startsWith("RFB 003.")) throw new Error("not an RFB server: " + version);
    this.send(new TextEncoder().encode("RFB 003.008\n"));
    const count = (yield 1)[0];
    if (count === 0) {
      const len = view(yield 4).getUint32(0);
      throw new Error("server refused: " + new TextDecoder().decode(yield len));
    }
    const types = yield count;
    if (!types.includes(1)) throw new Error("the server wants authentication: " + Array.from(types));
    this.send(Uint8Array.of(1));
    if (view(yield 4).getUint32(0) !== 0) throw new Error("security handshake failed");
    this.send(Uint8Array.of(1)); // shared
    const init = view(yield 24);
    this.resize(init.getUint16(0), init.getUint16(2));
    const name = new TextDecoder().decode(yield init.getUint32(20));
    this.sendPixelFormat();
    this.sendEncodings([ENC_COPYRECT, ENC_RAW, ENC_DESKTOP_SIZE, ENC_QEMU_POINTER_MOTION, ENC_QEMU_EXT_KEY]);
    this.requestUpdate(false);
    this.dispatchEvent(new CustomEvent("connect", { detail: { name, width: this.width, height: this.height } }));

    for (;;) {
      const type = (yield 1)[0];
      if (type === 0) {
        const header = view(yield 3);
        const rects = header.getUint16(1);
        let dirty = null;
        for (let i = 0; i < rects; i++) {
          const r = view(yield 12);
          const x = r.getUint16(0), y = r.getUint16(2), w = r.getUint16(4), h = r.getUint16(6);
          const enc = r.getInt32(8);
          if (enc === ENC_RAW) {
            const px = yield w * h * 4;
            for (let j = 3; j < px.length; j += 4) px[j] = 255;
            this.ctx.putImageData(new ImageData(new Uint8ClampedArray(px.buffer), w, h), x, y);
          } else if (enc === ENC_COPYRECT) {
            const src = view(yield 4);
            this.ctx.drawImage(this.canvas, src.getUint16(0), src.getUint16(2), w, h, x, y, w, h);
          } else if (enc === ENC_DESKTOP_SIZE) {
            this.resize(w, h);
          } else if (enc === ENC_QEMU_POINTER_MOTION) {
            this.absolute = x === 1;
          } else if (enc === ENC_QEMU_EXT_KEY) {
            this.extKeys = true;
          } else {
            throw new Error("unexpected encoding " + enc);
          }
          this.stats.rects++;
        }
        this.stats.updates++;
        this.stats.lastLatency = performance.now() - this.stats.requestedAt;
        this.dispatchEvent(new CustomEvent("update"));
        this.requestUpdate(true);
      } else if (type === 1) {
        const h = view(yield 5);
        yield h.getUint16(3) * 6; // colour map: not used with true colour
      } else if (type === 2) {
        // bell
      } else if (type === 3) {
        const h = view(yield 7);
        yield h.getUint32(3); // clipboard text
      } else {
        throw new Error("unexpected server message " + type);
      }
    }
  }

  resize(w, h) {
    this.width = w;
    this.height = h;
    this.canvas.width = w;
    this.canvas.height = h;
    this.dispatchEvent(new CustomEvent("resize", { detail: { width: w, height: h } }));
  }

  sendPixelFormat() {
    // 32 bpp true colour, red in the lowest byte: the bytes are R, G, B, X, as ImageData wants them
    const m = new DataView(new ArrayBuffer(20));
    m.setUint8(0, 0);
    m.setUint8(4, 32); m.setUint8(5, 24); m.setUint8(6, 0); m.setUint8(7, 1);
    m.setUint16(8, 255); m.setUint16(10, 255); m.setUint16(12, 255);
    m.setUint8(14, 0); m.setUint8(15, 8); m.setUint8(16, 16);
    this.send(m.buffer);
  }

  sendEncodings(list) {
    const m = new DataView(new ArrayBuffer(4 + 4 * list.length));
    m.setUint8(0, 2);
    m.setUint16(2, list.length);
    list.forEach((e, i) => m.setInt32(4 + 4 * i, e));
    this.send(m.buffer);
  }

  requestUpdate(incremental) {
    const m = new DataView(new ArrayBuffer(10));
    m.setUint8(0, 3);
    m.setUint8(1, incremental ? 1 : 0);
    m.setUint16(6, this.width);
    m.setUint16(8, this.height);
    this.stats.requestedAt = performance.now();
    this.send(m.buffer);
  }

  // x, y in framebuffer pixels; buttons: bit 0 = touching
  pointer(x, y, buttons) {
    this.buttons = buttons;
    const m = new DataView(new ArrayBuffer(6));
    m.setUint8(0, 5);
    m.setUint8(1, buttons);
    m.setUint16(2, Math.max(0, Math.min(this.width - 1, Math.round(x))));
    m.setUint16(4, Math.max(0, Math.min(this.height - 1, Math.round(y))));
    this.send(m.buffer);
  }

  // keysym: X11 keysym; scancode: PC XT scancode (QEMU's extended key event), used when the server supports it
  key(keysym, scancode, down) {
    if (this.extKeys && scancode) {
      const m = new DataView(new ArrayBuffer(12));
      m.setUint8(0, 255);
      m.setUint8(1, 0);
      m.setUint16(2, down ? 1 : 0);
      m.setUint32(4, keysym);
      m.setUint32(8, scancode);
      this.send(m.buffer);
    } else {
      const m = new DataView(new ArrayBuffer(8));
      m.setUint8(0, 4);
      m.setUint8(1, down ? 1 : 0);
      m.setUint32(4, keysym);
      this.send(m.buffer);
    }
  }
}

function view(bytes) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
}
