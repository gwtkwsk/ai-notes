#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::Manager;
use tauri::RunEvent;

struct BackendState(Mutex<Option<Child>>);

fn backend_workdir() -> Option<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.parent().and_then(|p| p.parent()).map(|p| p.to_path_buf())
}

fn spawn_backend() -> Result<Child, Box<dyn std::error::Error>> {
    let uv_bin = std::env::var("DISCO_NOTES_UV").unwrap_or_else(|_| "uv".to_string());
    let python = std::env::var("DISCO_NOTES_PYTHON").unwrap_or_else(|_| "python".to_string());
    let port = std::env::var("DISCO_NOTES_PORT").unwrap_or_else(|_| "8765".to_string());

    let mut cmd = Command::new(uv_bin);
    cmd.arg("run")
        .arg(python)
        .arg("-m")
        .arg("app.api.server")
        .env("DISCO_NOTES_PORT", &port)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());

    if let Some(dir) = backend_workdir() {
        cmd.current_dir(dir);
    }

    Ok(cmd.spawn()?)
}

fn main() {
    let app = tauri::Builder::default()
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            let child = spawn_backend()?;
            let state = app.state::<BackendState>();
            *state.0.lock().unwrap() = Some(child);
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            let child = {
                let state = app_handle.state::<BackendState>();
                let taken = state.0.lock().unwrap().take();
                taken
            };
            if let Some(mut child) = child {
                let _ = child.kill();
            }
        }
    });
}
