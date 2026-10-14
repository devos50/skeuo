// The display/input spike in a Tauri 2 webview: starts `skeuo serve`, runs a device and shows the spike page
// (../web) for it. Closing the window closes the daemon's stdin, which suspends the device.
//
//   SKEUO_QEMU=... SKEUO_BOOTROM=... cargo run -- ipod-2.1.1

use std::io::{BufRead, BufReader, Write};
use std::process::{Command, Stdio};
use std::sync::Mutex;

use tauri::{RunEvent, WebviewUrl, WebviewWindowBuilder};

fn main() {
    let device = std::env::args().nth(1).unwrap_or_else(|| "ipod-2.1.1".into());
    let pipeline = concat!(env!("CARGO_MANIFEST_DIR"), "/../../../pipeline");
    let mut daemon = Command::new("python3")
        .args(["-m", "skeuo", "serve"])
        .current_dir(pipeline)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .expect("could not start skeuo serve");
    let mut stdin = daemon.stdin.take().unwrap();
    let mut lines = BufReader::new(daemon.stdout.take().unwrap()).lines();
    let request = serde_json::json!({"id": 1, "method": "run", "params": {"device": device}});
    writeln!(stdin, "{request}").unwrap();

    let mut websocket = None;
    for line in lines.by_ref() {
        let message: serde_json::Value = serde_json::from_str(&line.unwrap()).unwrap();
        if message["id"] == 1 {
            if let Some(error) = message.get("error") {
                eprintln!("run failed: {error}");
                std::process::exit(1);
            }
            websocket = message["result"]["vnc"]["websocket"].as_u64();
            break;
        }
    }
    let websocket = websocket.expect("the daemon went away");
    std::thread::spawn(move || {
        for line in lines.map_while(Result::ok) {
            if !line.contains(r#""event":"log""#) {
                eprintln!("{line}");
            }
        }
    });

    let stdin = Mutex::new(Some(stdin));
    let daemon = Mutex::new(daemon);
    tauri::Builder::default()
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Skeuo spike")
                .inner_size(640.0, 620.0)
                .initialization_script(&format!("window.SKEUO_WS = {websocket};"))
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("could not build the Tauri app")
        .run(move |_app, event| {
            if let RunEvent::Exit = event {
                drop(stdin.lock().unwrap().take()); // the daemon suspends the device and exits
                let _ = daemon.lock().unwrap().wait();
            }
        });
}
