// The pipeline daemon (`python3 -m skeuo serve`, pipeline/skeuo/serve.py): JSON lines over its stdin and stdout.
// call() sends a request and waits for its response; events go to every window as the "daemon" event, and to
// on_event in Rust.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};
use tokio::sync::oneshot;

#[derive(Debug, Clone, Serialize)]
pub struct RpcError {
    pub code: String,
    pub message: String,
}

impl RpcError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        RpcError { code: code.into(), message: message.into() }
    }
}

type Pending = Mutex<HashMap<u64, oneshot::Sender<Result<Value, RpcError>>>>;

pub struct Daemon {
    stdin: Mutex<Option<ChildStdin>>,
    child: Mutex<Child>,
    pending: Arc<Pending>,
    next_id: AtomicU64,
}

impl Daemon {
    /// Starts the daemon. python: the interpreter; pipeline: the directory with the skeuo package.
    pub fn start(
        app: AppHandle,
        python: &str,
        pipeline: &Path,
        args: &[String],
        on_event: impl Fn(&AppHandle, &Value) + Send + 'static,
    ) -> std::io::Result<Arc<Daemon>> {
        let mut child = Command::new(python)
            .args(["-m", "skeuo", "serve"])
            .args(args)
            .current_dir(pipeline)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()?;
        let stdin = child.stdin.take();
        let stdout = BufReader::new(child.stdout.take().unwrap());
        let pending: Arc<Pending> = Arc::new(Mutex::new(HashMap::new()));

        let reader_pending = pending.clone();
        std::thread::spawn(move || {
            for line in stdout.lines().map_while(Result::ok) {
                let Ok(message) = serde_json::from_str::<Value>(&line) else { continue };
                if message.get("event").is_some() {
                    on_event(&app, &message);
                    let _ = app.emit("daemon", &message);
                } else if let Some(id) = message.get("id").and_then(Value::as_u64) {
                    let result = match message.get("error") {
                        Some(error) => Err(RpcError::new(
                            error["code"].as_str().unwrap_or("failed"),
                            error["message"].as_str().unwrap_or("unknown error"),
                        )),
                        None => Ok(message.get("result").cloned().unwrap_or(Value::Null)),
                    };
                    if let Some(sender) = reader_pending.lock().unwrap().remove(&id) {
                        let _ = sender.send(result);
                    }
                }
            }
            // the daemon exited: fail what is still waiting
            for (_, sender) in reader_pending.lock().unwrap().drain() {
                let _ = sender.send(Err(RpcError::new("daemon_exited", "the Skeuo daemon stopped")));
            }
            let _ = app.emit("daemon", json!({"event": "exited"}));
        });

        Ok(Arc::new(Daemon {
            stdin: Mutex::new(stdin),
            child: Mutex::new(child),
            pending,
            next_id: AtomicU64::new(1),
        }))
    }

    pub async fn call(&self, method: &str, params: Value) -> Result<Value, RpcError> {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver) = oneshot::channel();
        self.pending.lock().unwrap().insert(id, sender);
        let line = json!({"id": id, "method": method, "params": params}).to_string();
        let written = match self.stdin.lock().unwrap().as_mut() {
            Some(stdin) => writeln!(stdin, "{line}").and_then(|_| stdin.flush()).is_ok(),
            None => false,
        };
        if !written {
            self.pending.lock().unwrap().remove(&id);
            return Err(RpcError::new("daemon_exited", "the Skeuo daemon isn't running"));
        }
        receiver.await.unwrap_or_else(|_| Err(RpcError::new("daemon_exited", "the Skeuo daemon stopped")))
    }

    /// Closes the daemon's stdin, which makes it suspend the running device and exit, and waits for that.
    pub fn shutdown(&self) {
        self.stdin.lock().unwrap().take();
        let _ = self.child.lock().unwrap().wait();
    }
}
