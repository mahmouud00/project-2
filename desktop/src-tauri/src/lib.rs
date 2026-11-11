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

/// An exported file (Excel, a printout, a library package…) written to the user's Downloads folder under its own
/// name ("name (2).xlsx" when one is already there). The bytes come as the raw request body and the name, URL-encoded,
/// in the `x-name` header. Returns where it was written. WebView2 drops the browser-style download of a generated
/// file, so the program writes it itself.
#[tauri::command]
fn save_download(app: tauri::AppHandle, request: tauri::ipc::Request<'_>) -> Result<String, String> {
    use tauri::Manager;
    let tauri::ipc::InvokeBody::Raw(data) = request.body() else {
        return Err("expected the file's bytes".into());
    };
    let name = request
        .headers()
        .get("x-name")
        .and_then(|v| v.to_str().ok())
        .map(percent_decode)
        .unwrap_or_default();
    let dir = app
        .path()
        .download_dir()
        .or_else(|_| app.path().document_dir())
        .map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let clean: String = name
        .chars()
        .map(|c| if "\\/:*?\"<>|".contains(c) || c.is_control() { '-' } else { c })
        .collect();
    let clean = clean.trim().trim_matches('.').to_string();
    let clean = if clean.is_empty() { "file".to_string() } else { clean };
    let (stem, ext) = match clean.rfind('.') {
        Some(i) if i > 0 => (clean[..i].to_string(), clean[i..].to_string()),
        _ => (clean.clone(), String::new()),
    };
    let mut path = dir.join(&clean);
    let mut n = 2;
    while path.exists() {
        path = dir.join(format!("{stem} ({n}){ext}"));
        n += 1;
    }
    std::fs::write(&path, data).map_err(|e| e.to_string())?;
    Ok(path.to_string_lossy().into_owned())
}

/// "%D9%82" -> the UTF-8 text it encodes (the file name sent by encodeURIComponent).
fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Ok(v) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init());
    #[cfg(mobile)]
    let builder = builder.plugin(tauri_plugin_geolocation::init());
    builder
        .invoke_handler(tauri::generate_handler![discover_servers, save_download])
        .run(tauri::generate_context!())
        .expect("error while running MYTech Solutions");
}
