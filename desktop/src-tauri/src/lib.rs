mod discovery;

use std::time::Duration;

/// Servers answering the LAN discovery broadcast (used by the connect screen).
#[tauri::command]
async fn discover_servers(timeout_ms: Option<u64>) -> Result<Vec<serde_json::Value>, String> {
    let timeout = Duration::from_millis(timeout_ms.unwrap_or(1800).clamp(300, 10_000));
    tauri::async_runtime::spawn_blocking(move || discovery::discover(timeout, discovery::PORT))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default().plugin(tauri_plugin_opener::init());
    #[cfg(mobile)]
    let builder = builder.plugin(tauri_plugin_geolocation::init());
    builder
        .invoke_handler(tauri::generate_handler![discover_servers])
        .run(tauri::generate_context!())
        .expect("error while running MYTech Solutions");
}
