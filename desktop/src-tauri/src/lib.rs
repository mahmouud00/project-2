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

/// Map links open in the system browser (Google Maps / OpenStreetMap only, nothing else).
const MAP_PREFIXES: &[&str] = &[
    "https://www.google.com/maps", "https://google.com/maps", "https://maps.google.com/", "https://maps.app.goo.gl/",
    "https://goo.gl/maps/", "https://www.openstreetmap.org/",
];

#[tauri::command]
fn open_map(url: String) -> Result<(), String> {
    let ok = url.len() < 2000
        && MAP_PREFIXES.iter().any(|p| url.starts_with(p))
        && !url.chars().any(|c| c.is_whitespace() || c.is_control() || c == '"' || c == '\'');
    if !ok {
        return Err("not a map link".into());
    }
    // no shell involved: the link is one argument of the program that opens it
    #[cfg(target_os = "windows")]
    let result = std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", &url]).spawn();
    #[cfg(target_os = "macos")]
    let result = std::process::Command::new("open").arg(&url).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let result = std::process::Command::new("xdg-open").arg(&url).spawn();
    result.map(|_| ()).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![discover_servers, open_map])
        .run(tauri::generate_context!())
        .expect("error while running MYTech Solutions");
}
