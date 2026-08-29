use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// 起動した Python バックエンド（サイドカー）のプロセスハンドル。
/// アプリ終了時に確実に kill するため managed state に載せる。
struct Backend(Mutex<Option<CommandChild>>);

fn free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .expect("空きポートの確保に失敗しました")
}

/// バックエンドが指定ポートで待受を開始するまで待つ（最長 30 秒）。
fn wait_for_port(port: u16) -> bool {
    let deadline = Instant::now() + Duration::from_secs(30);
    while Instant::now() < deadline {
        if std::net::TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .setup(|app| {
            let port = free_port();
            let handle = app.handle().clone();

            // Python バックエンド（FastAPI + 同梱フロント）をサイドカーとして起動
            let (mut rx, child) = app
                .shell()
                .sidecar("modbus-sim-backend")?
                .args(["--host", "127.0.0.1", "--port", &port.to_string()])
                .spawn()?;
            app.manage(Backend(Mutex::new(Some(child))));

            // サイドカーの出力をログへ流す（パイプが詰まらないように必ず読む）
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            log::info!("[backend] {}", String::from_utf8_lossy(&line).trim_end())
                        }
                        CommandEvent::Stderr(line) => {
                            log::warn!("[backend] {}", String::from_utf8_lossy(&line).trim_end())
                        }
                        CommandEvent::Terminated(payload) => {
                            log::error!("[backend] terminated: {:?}", payload.code)
                        }
                        _ => {}
                    }
                }
            });

            // 待受開始を待ってからウィンドウを開く（メインスレッドを塞がない）
            std::thread::spawn(move || {
                let ready = wait_for_port(port);
                if !ready {
                    log::error!("バックエンドが起動しませんでした (port {port})");
                }
                let url = format!("http://127.0.0.1:{port}/");
                let result = WebviewWindowBuilder::new(
                    &handle,
                    "main",
                    WebviewUrl::External(url.parse().expect("URL parse")),
                )
                .title("Modbus Simulator")
                .inner_size(980.0, 680.0)
                .min_inner_size(800.0, 560.0)
                .build();
                if let Err(e) = result {
                    log::error!("ウィンドウ生成に失敗: {e}");
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                if let Some(state) = app_handle.try_state::<Backend>() {
                    if let Some(child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                    }
                }
            }
        });
}
