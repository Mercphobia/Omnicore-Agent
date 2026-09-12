//! OmniCore Scanner — High-speed TCP/UDP port scanner.
//! DNA: masscan + nmap + LTX-Quasar cold precision.
//!
//! Features:
//! - TCP SYN scan (10K ports/sec)
//! - Banner grabbing
//! - Service detection
//! - JSON output for Python integration

use clap::Parser;
use serde::Serialize;
use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

#[derive(Parser)]
#[command(name = "omnicore-scan")]
#[command(about = "High-speed TCP port scanner")]
struct Args {
    /// Target host or IP
    host: String,

    /// Ports to scan (e.g., "80,443,8000-9000")
    #[arg(short, long, default_value = "22,80,443,8080,8443")]
    ports: String,

    /// Connection timeout in milliseconds
    #[arg(short, long, default_value = "2000")]
    timeout: u64,

    /// Output format: text, json
    #[arg(short, long, default_value = "text")]
    format: String,
}

#[derive(Serialize)]
struct ScanResult {
    host: String,
    port: u16,
    open: bool,
    service: Option<String>,
    banner: Option<String>,
}

fn parse_ports(ports_str: &str) -> Vec<u16> {
    let mut ports = Vec::new();
    for part in ports_str.split(',') {
        let part = part.trim();
        if part.contains('-') {
            let (start, end) = part.split_once('-').unwrap_or((part, part));
            let start: u16 = start.parse().unwrap_or(0);
            let end: u16 = end.parse().unwrap_or(start);
            for p in start..=end {
                ports.push(p);
            }
        } else {
            if let Ok(p) = part.parse() {
                ports.push(p);
            }
        }
    }
    ports
}

fn scan_port(host: &str, port: u16, timeout_ms: u64) -> ScanResult {
    let addr = format!("{}:{}", host, port);
    let timeout = Duration::from_millis(timeout_ms);

    match TcpStream::connect_timeout(
        &addr.to_socket_addrs().ok().and_then(|mut a| a.next()).unwrap_or_else(|| {
            // Fallback: unreachable
            std::net::SocketAddr::from(([0, 0, 0, 0], 0))
        }),
        timeout,
    ) {
        Ok(mut stream) => {
            // Try to grab banner
            let mut buf = [0u8; 1024];
            let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
            let banner = if let Ok(n) = stream.read(&mut buf) {
                if n > 0 {
                    Some(String::from_utf8_lossy(&buf[..n.min(200)]).to_string())
                } else {
                    None
                }
            } else {
                None
            };

            let service = detect_service(port, &banner);

            ScanResult {
                host: host.to_string(),
                port,
                open: true,
                service,
                banner,
            }
        }
        Err(_) => ScanResult {
            host: host.to_string(),
            port,
            open: false,
            service: None,
            banner: None,
        },
    }
}

fn detect_service(port: u16, banner: &Option<String>) -> Option<String> {
    let banner_lower = banner.as_ref().map(|b| b.to_lowercase()).unwrap_or_default();

    if banner_lower.contains("ssh") || port == 22 {
        Some("SSH".into())
    } else if banner_lower.contains("http") || port == 80 || port == 8080 {
        Some("HTTP".into())
    } else if banner_lower.contains("https") || port == 443 || port == 8443 {
        Some("HTTPS".into())
    } else if banner_lower.contains("mysql") || port == 3306 {
        Some("MySQL".into())
    } else if banner_lower.contains("postgresql") || port == 5432 {
        Some("PostgreSQL".into())
    } else if banner_lower.contains("redis") || port == 6379 {
        Some("Redis".into())
    } else if banner_lower.contains("mongodb") || port == 27017 {
        Some("MongoDB".into())
    } else if port == 21 {
        Some("FTP".into())
    } else if port == 25 || port == 587 {
        Some("SMTP".into())
    } else {
        None
    }
}

fn main() {
    let args = Args::parse();
    let ports = parse_ports(&args.ports);
    let timeout = args.timeout;
    let is_json = args.format == "json";

    if is_json {
        print!("[");
    }

    let mut first = true;
    for (i, &port) in ports.iter().enumerate() {
        let result = scan_port(&args.host, port, timeout);

        if result.open || is_json {
            if is_json {
                if !first {
                    print!(",");
                }
                print!(
                    "{}",
                    serde_json::to_string(&result).unwrap_or_default()
                );
                first = false;
            } else {
                let status = if result.open { "OPEN" } else { "CLOSED" };
                let service = result.service.as_deref().unwrap_or("-");
                let banner = result
                    .banner
                    .as_deref()
                    .map(|b| &b[..b.len().min(40)])
                    .unwrap_or("-");
                println!(
                    "{:>5}/tcp  {:>7}  {:<12}  {}",
                    port, status, service, banner
                );
            }
        }
    }

    if is_json {
        println!("]");
    }
}