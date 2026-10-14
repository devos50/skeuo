// Skeuo's Rust core: runs the pipeline daemon, keeps the app's settings and the bootrom, and opens a window per
// running device. The pipeline owns the device bundles; the UI asks it for everything through `rpc`.

mod daemon;

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder};

use daemon::{Daemon, RpcError};

/// The S5L8720 SecureROM (iBoot-240.4) that the emulator runs. Apple's code, so the user supplies it.
const BOOTROM_SHA256: &str = "55f4d8ea2791ba51dd89934168f38f0fb21ce8762ff614c1e742407c0d3ca054";
const BOOTROM_SIZE: usize = 65536;

#[derive(Serialize, Deserialize, Clone)]
struct Settings {
    /// The directory with the device bundles.
    library: PathBuf,
}

struct App {
    /// <data dir>/Skeuo: settings.json, bootrom.bin, and the pipeline's IPSW cache (ipsw/).
    data: PathBuf,
    settings: Mutex<Settings>,
    daemon: Mutex<Option<Arc<Daemon>>>,
    daemon_error: Mutex<Option<String>>,
}

impl App {
    fn bootrom(&self) -> PathBuf {
        self.data.join("bootrom.bin")
    }

    fn daemon(&self) -> Result<Arc<Daemon>, RpcError> {
        self.daemon.lock().unwrap().clone().ok_or_else(|| {
            let error = self.daemon_error.lock().unwrap().clone();
            RpcError::new("no_daemon", error.unwrap_or_else(|| "the Skeuo daemon isn't running".into()))
        })
    }
}

/// The pipeline directory: $SKEUO_PIPELINE, or the repository's pipeline/ next to app/ (development).
fn pipeline_dir() -> PathBuf {
    std::env::var_os("SKEUO_PIPELINE")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("../../pipeline"))
}

/// A window label for a device; labels only allow a few characters, and device ids can contain dots.
fn device_label(id: &str) -> String {
    format!("device-{}", id.bytes().map(|b| format!("{b:02x}")).collect::<String>())
}

fn start_daemon(app: &AppHandle) {
    let state = app.state::<App>();
    if state.daemon.lock().unwrap().is_some() || !state.bootrom().exists() {
        return;
    }
    let settings = state.settings.lock().unwrap().clone();
    let args = vec![
        "--library".into(),
        settings.library.to_string_lossy().into_owned(),
        "--bootrom".into(),
        state.bootrom().to_string_lossy().into_owned(),
        "--ipsw-cache".into(),
        state.data.join("ipsw").to_string_lossy().into_owned(),
    ];
    let python = std::env::var("SKEUO_PYTHON").unwrap_or_else(|_| "python3".into());
    let result = Daemon::start(app.clone(), &python, &pipeline_dir(), &args, on_daemon_event);
    match result {
        Ok(daemon) => {
            *state.daemon.lock().unwrap() = Some(daemon);
            *state.daemon_error.lock().unwrap() = None;
        }
        Err(e) => *state.daemon_error.lock().unwrap() = Some(format!("could not start the Skeuo daemon: {e}")),
    }
}

/// A device that stops running closes its window.
fn on_daemon_event(app: &AppHandle, event: &Value) {
    if event["event"] == "state" {
        let state = event["state"].as_str().unwrap_or("");
        if let (Some(id), true) = (event["device"].as_str(), state == "off" || state == "suspended") {
            if let Some(window) = app.get_webview_window(&device_label(id)) {
                let _ = window.destroy();
            }
        }
    }
}

#[derive(Serialize)]
struct Status {
    bootrom: bool,
    library: PathBuf,
    daemon: bool,
    error: Option<String>,
}

#[tauri::command]
fn status(state: State<App>) -> Status {
    Status {
        bootrom: state.bootrom().exists(),
        library: state.settings.lock().unwrap().library.clone(),
        daemon: state.daemon.lock().unwrap().is_some(),
        error: state.daemon_error.lock().unwrap().clone(),
    }
}

/// Checks the bootrom the user picked and keeps a copy in the app's data directory.
#[tauri::command]
fn import_bootrom(app: AppHandle, state: State<App>, bytes: Vec<u8>) -> Result<Status, String> {
    store_bootrom(&state, &bytes)?;
    start_daemon(&app);
    Ok(status(state))
}

fn store_bootrom(state: &App, bytes: &[u8]) -> Result<(), String> {
    if bytes.len() != BOOTROM_SIZE {
        return Err(format!(
            "This file is {} bytes; the S5L8720 bootrom is {BOOTROM_SIZE} bytes.",
            bytes.len()
        ));
    }
    let digest: String = Sha256::digest(bytes).iter().map(|b| format!("{b:02x}")).collect();
    if digest != BOOTROM_SHA256 {
        return Err("This isn't the S5L8720 bootrom Skeuo needs (SecureROM iBoot-240.4): its SHA-256 differs.".into());
    }
    std::fs::create_dir_all(&state.data).map_err(|e| e.to_string())?;
    let part = state.bootrom().with_extension("part");
    std::fs::write(&part, bytes).and_then(|_| std::fs::rename(&part, state.bootrom())).map_err(|e| e.to_string())
}

/// Without a bootrom yet, takes the one $SKEUO_BOOTROM names (as the pipeline does), so development skips the
/// first-run step. The same check applies; a wrong file leaves the first-run step to ask.
fn bootrom_from_environment(state: &App) {
    if state.bootrom().exists() {
        return;
    }
    if let Some(path) = std::env::var_os("SKEUO_BOOTROM") {
        let result = std::fs::read(&path).map_err(|e| e.to_string()).and_then(|bytes| store_bootrom(state, &bytes));
        if let Err(e) = result {
            eprintln!("skeuo: not using SKEUO_BOOTROM ({}): {e}", PathBuf::from(path).display());
        }
    }
}

/// A request to the pipeline daemon (see pipeline/skeuo/serve.py).
#[tauri::command]
async fn rpc(state: State<'_, App>, method: String, params: Option<Value>) -> Result<Value, RpcError> {
    let daemon = state.daemon()?;
    daemon.call(&method, params.unwrap_or_else(|| json!({}))).await
}

/// Runs (boots or resumes) a device and opens its window, or brings the window forward if it is running.
#[tauri::command]
async fn start_device(app: AppHandle, state: State<'_, App>, id: String, cold_boot: bool) -> Result<(), RpcError> {
    let label = device_label(&id);
    if let Some(window) = app.get_webview_window(&label) {
        let _ = window.set_focus();
        return Ok(());
    }
    let daemon = state.daemon()?;
    let result = daemon.call("run", json!({"device": id, "cold_boot": cold_boot})).await?;
    open_device_window(&app, &id, &result)
}

fn open_device_window(app: &AppHandle, id: &str, run: &Value) -> Result<(), RpcError> {
    let websocket = run["vnc"]["websocket"].as_u64().unwrap_or(0);
    let query: String = [("device", id.to_string()), ("ws", websocket.to_string())]
        .iter()
        .map(|(k, v)| format!("{k}={}", encode(v)))
        .collect::<Vec<_>>()
        .join("&");
    WebviewWindowBuilder::new(app, device_label(id), WebviewUrl::App(format!("index.html?{query}").into()))
        .title("Skeuo")
        // the device frame at 1x plus the toolbar (DeviceWindow.svelte)
        .inner_size(404.0, 744.0)
        .min_inner_size(220.0, 260.0)
        .build()
        .map_err(|e| RpcError::new("window", e.to_string()))?;
    Ok(())
}

/// Undoes encodeURIComponent.
fn decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(b) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(b);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn encode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'a'..=b'z' | b'A'..=b'Z' | b'0'..=b'9' | b'-' | b'_' | b'.' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

/// Powers a running device off and boots it again, in a new window.
#[tauri::command]
async fn restart_device(app: AppHandle, state: State<'_, App>, id: String) -> Result<(), RpcError> {
    let daemon = state.daemon()?;
    daemon.call("power_off", json!({"device": id})).await?;
    let result = daemon.call("run", json!({"device": id})).await?;
    open_device_window(&app, &id, &result)
}

/// Saves a screenshot to the Desktop: the PNG is the request body, the file name (without .png, percent-encoded)
/// the x-name header. Returns the path.
#[tauri::command]
fn save_screenshot(app: AppHandle, request: tauri::ipc::Request) -> Result<String, String> {
    let tauri::ipc::InvokeBody::Raw(png) = request.body() else {
        return Err("expected the PNG as the request body".into());
    };
    let name = request.headers().get("x-name").and_then(|v| v.to_str().ok()).map(decode).unwrap_or_default();
    let name = if name.is_empty() { "Skeuo Screenshot".to_string() } else { name };
    let name: String = name.chars().map(|c| if "/\\:".contains(c) { '-' } else { c }).collect();
    let desktop = app.path().desktop_dir().map_err(|e| e.to_string())?;
    let mut path = desktop.join(format!("{name}.png"));
    let mut n = 2;
    while path.exists() {
        path = desktop.join(format!("{name} {n}.png"));
        n += 1;
    }
    std::fs::write(&path, png).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}

/// The device's thumbnail.png, or nothing.
#[tauri::command]
fn thumbnail(state: State<App>, id: String) -> tauri::ipc::Response {
    let library = state.settings.lock().unwrap().library.clone();
    let bytes = if id.contains('/') || id.contains('\\') || id.starts_with('.') {
        Vec::new()
    } else {
        std::fs::read(library.join(&id).join("thumbnail.png")).unwrap_or_default()
    };
    tauri::ipc::Response::new(bytes)
}

/// Asks for a file or folder for the new-device dialog: "ipsw" (a restore IPSW), "certificate" (a device
/// certificate or activation record) or "folder" (NOR images). The pipeline needs paths, which a web page can't give.
#[tauri::command]
async fn pick_path(app: AppHandle, kind: String) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    let (sender, receiver) = tokio::sync::oneshot::channel();
    let dialog = app.dialog().file();
    let send = move |path: Option<tauri_plugin_dialog::FilePath>| {
        let _ = sender.send(path.map(|p| p.to_string()));
    };
    match kind.as_str() {
        "folder" => dialog.set_title("Choose the NOR images folder").pick_folder(send),
        "certificate" => dialog
            .set_title("Choose a device certificate")
            .add_filter("Device certificate or activation record", &["pem", "plist", "crt"])
            .pick_file(send),
        _ => dialog.set_title("Choose a restore IPSW").add_filter("Restore IPSW", &["ipsw", "zip"]).pick_file(send),
    }
    receiver.await.ok().flatten()
}

/// Shows the device's bundle in the file manager.
#[tauri::command]
fn reveal(path: String) -> Result<(), String> {
    let result = if cfg!(target_os = "macos") {
        Command::new("open").arg("-R").arg(&path).spawn()
    } else if cfg!(target_os = "windows") {
        Command::new("explorer").arg(format!("/select,{path}")).spawn()
    } else {
        Command::new("xdg-open").arg(Path::new(&path).parent().unwrap_or(Path::new("/"))).spawn()
    };
    result.map(|_| ()).map_err(|e| e.to_string())
}

fn load_settings(data: &Path) -> Settings {
    let default = Settings { library: dirs_home().join("Skeuo") };
    std::fs::read(data.join("settings.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice(&bytes).ok())
        .unwrap_or(default)
}

fn dirs_home() -> PathBuf {
    std::env::var_os("HOME").or_else(|| std::env::var_os("USERPROFILE")).map(PathBuf::from).unwrap_or_default()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let data = app.path().data_dir()?.join("Skeuo");
            let settings = load_settings(&data);
            app.manage(App {
                data,
                settings: Mutex::new(settings),
                daemon: Mutex::new(None),
                daemon_error: Mutex::new(None),
            });
            bootrom_from_environment(&app.state::<App>());
            start_daemon(app.handle());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            status,
            import_bootrom,
            rpc,
            start_device,
            restart_device,
            thumbnail,
            reveal,
            pick_path,
            save_screenshot
        ])
        .build(tauri::generate_context!())
        .expect("could not start Skeuo")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                // the daemon suspends the running device before it exits
                let daemon = app.state::<App>().daemon.lock().unwrap().take();
                if let Some(daemon) = daemon {
                    daemon.shutdown();
                }
            }
        });
}
