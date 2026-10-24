//! LAN discovery of the MYTech server: UDP broadcast "MYTECH_DISCOVER" to port 47800; every server
//! answers with a small JSON (product, version, host, address, port, scheme). No internet involved.
use serde_json::Value;
use std::collections::HashSet;
use std::net::UdpSocket;
use std::time::{Duration, Instant};

pub const MAGIC: &[u8] = b"MYTECH_DISCOVER";
pub const PORT: u16 = 47800;

pub fn discover(timeout: Duration, port: u16) -> std::io::Result<Vec<Value>> {
    let sock = UdpSocket::bind("0.0.0.0:0")?;
    sock.set_broadcast(true)?;
    sock.set_read_timeout(Some(Duration::from_millis(150)))?;
    for target in [format!("255.255.255.255:{port}"), format!("127.0.0.1:{port}")] {
        let _ = sock.send_to(MAGIC, target);
    }
    let deadline = Instant::now() + timeout;
    let mut seen = HashSet::new();
    let mut found = Vec::new();
    let mut buf = [0u8; 4096];
    while Instant::now() < deadline {
        let (n, from) = match sock.recv_from(&mut buf) {
            Ok(r) => r,
            Err(_) => continue,
        };
        let Ok(mut info) = serde_json::from_slice::<Value>(&buf[..n]) else { continue };
        if info.get("product").and_then(Value::as_str) != Some("MYTech Solutions") {
            continue;
        }
        let address = match info.get("address").and_then(Value::as_str) {
            Some(a) if !a.is_empty() && a != "0.0.0.0" => a.to_string(),
            _ => from.ip().to_string(),
        };
        info["address"] = Value::String(address.clone());
        let port = info.get("port").and_then(Value::as_u64).unwrap_or(8000);
        if seen.insert(format!("{address}:{port}")) {
            found.push(info);
        }
    }
    Ok(found)
}
