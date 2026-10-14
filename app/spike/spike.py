"""
The display/input spike: runs a device through `skeuo serve` and serves the spike page for it.

  python3 spike.py ipod-2.1.1 [--cold-boot]    then open the URL it prints; Ctrl-C suspends the device

Needs SKEUO_QEMU and SKEUO_BOOTROM like the pipeline. Also measures QEMU's CPU use every 5 s.
"""
import functools
import signal
import http.server
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(HERE, "..", "..", "pipeline")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    device = args[0] if args else "ipod-2.1.1"
    cold_boot = "--cold-boot" in sys.argv
    daemon = subprocess.Popen([sys.executable, "-m", "skeuo", "serve"], cwd=PIPELINE, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True)
    replies = {}
    got = threading.Condition()

    def read():
        for line in daemon.stdout:
            message = json.loads(line)
            if "event" in message:
                if message["event"] != "log":
                    print("event:", json.dumps(message)[:200], flush=True)
            else:
                with got:
                    replies[message["id"]] = message
                    got.notify_all()

    threading.Thread(target=read, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt))
    daemon.stdin.write(json.dumps({"id": 1, "method": "run", "params": {"device": device, "cold_boot": cold_boot}}) + "\n")
    daemon.stdin.flush()
    with got:
        got.wait_for(lambda: 1 in replies, 60)
    reply = replies.get(1)
    if not reply or "error" in reply:
        print("run failed:", reply)
        daemon.stdin.close()
        return 1

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=os.path.join(HERE, "web"))
    handler.log_message = lambda *args: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("open http://127.0.0.1:%d/index.html?ws=%d" % (server.server_port, reply["result"]["vnc"]["websocket"]),
          flush=True)

    try:
        while daemon.poll() is None:
            out = subprocess.run(["ps", "-A", "-o", "%cpu=,command="], capture_output=True, text=True).stdout
            cpu = [line.split()[0] for line in out.splitlines() if "qemu-system-arm" in line and "nand-disk" in line]
            print("qemu cpu: %s%%" % ",".join(cpu), flush=True)
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    daemon.stdin.close()  # the daemon suspends the device and exits
    daemon.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
