// Mortiflix Singer desktop app: a window on the singer:// protocol. Pages are served from the bundled web folder;
// /api/singer/* requests go to the singer service (bundled next to this program) as framed HTTP over its
// stdin/stdout, so the app opens no network port.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Read, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex};

use tauri::http::{Request, Response};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

type Pending = Arc<Mutex<HashMap<u64, Sender<Vec<u8>>>>>;

struct Service {
    stdin: Mutex<ChildStdin>,
    pending: Pending,
    next: AtomicU64,
    child: Mutex<Child>,
}

impl Service {
    /// The bundled service sits next to this program; in development it is `python server.py` from the repo
    /// (SINGER_PYTHON picks the interpreter).
    fn spawn() -> std::io::Result<Arc<Service>> {
        let exe_dir = std::env::current_exe()?.parent().map(PathBuf::from).unwrap_or_default();
        let bundled = exe_dir.join(if cfg!(windows) { "singer-service.exe" } else { "singer-service" });
        let mut cmd = if bundled.exists() {
            Command::new(bundled)
        } else {
            let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
            let py = std::env::var("SINGER_PYTHON").unwrap_or_else(|_| repo.join(".venv/bin/python").to_string_lossy().into_owned());
            let mut c = Command::new(py);
            c.arg(repo.join("server.py")).current_dir(&repo);
            c
        };
        cmd.arg("--stdio").stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: no console window for the service
        }
        let mut child = cmd.spawn()?;
        let stdin = child.stdin.take().expect("service stdin");
        let stdout = child.stdout.take().expect("service stdout");
        let pending: Pending = Arc::new(Mutex::new(HashMap::new()));
        let p2 = pending.clone();
        std::thread::spawn(move || {
            let mut r = BufReader::new(stdout);
            let mut line = String::new();
            loop {
                line.clear();
                if r.read_line(&mut line).unwrap_or(0) == 0 { break; }
                let Ok(h) = serde_json::from_str::<serde_json::Value>(line.trim()) else { continue };
                let (id, len) = (h["id"].as_u64().unwrap_or(0), h["len"].as_u64().unwrap_or(0) as usize);
                let mut buf = vec![0u8; len];
                if r.read_exact(&mut buf).is_err() { break; }
                if let Some(tx) = p2.lock().unwrap().remove(&id) { let _ = tx.send(buf); }
            }
            // the service ended: everyone still waiting gets an error answer
            for (_, tx) in p2.lock().unwrap().drain() {
                let _ = tx.send(b"HTTP/1.0 503 Service Unavailable\r\ncontent-type: application/json\r\n\r\n{\"error\": \"the singer service stopped\"}".to_vec());
            }
        });
        Ok(Arc::new(Service { stdin: Mutex::new(stdin), pending, next: AtomicU64::new(1), child: Mutex::new(child) }))
    }

    /// Send one raw HTTP request, wait for the raw response.
    fn call(&self, raw: Vec<u8>) -> Vec<u8> {
        let id = self.next.fetch_add(1, Ordering::Relaxed);
        let (tx, rx) = channel();
        self.pending.lock().unwrap().insert(id, tx);
        {
            let mut w = self.stdin.lock().unwrap();
            let head = format!("{{\"id\": {}, \"len\": {}}}\n", id, raw.len());
            if w.write_all(head.as_bytes()).and_then(|_| w.write_all(&raw)).and_then(|_| w.flush()).is_err() {
                self.pending.lock().unwrap().remove(&id);
                return b"HTTP/1.0 503 Service Unavailable\r\n\r\n".to_vec();
            }
        }
        rx.recv().unwrap_or_else(|_| b"HTTP/1.0 503 Service Unavailable\r\n\r\n".to_vec())
    }
}

fn raw_request(req: &Request<Vec<u8>>) -> Vec<u8> {
    let path = req.uri().path_and_query().map(|p| p.as_str()).unwrap_or("/");
    let mut out = format!("{} {} HTTP/1.1\r\n", req.method(), path).into_bytes();
    for (k, v) in req.headers() {
        if k.as_str().eq_ignore_ascii_case("content-length") { continue; }
        out.extend_from_slice(k.as_str().as_bytes());
        out.extend_from_slice(b": ");
        out.extend_from_slice(v.as_bytes());
        out.extend_from_slice(b"\r\n");
    }
    out.extend_from_slice(format!("content-length: {}\r\n\r\n", req.body().len()).as_bytes());
    out.extend_from_slice(req.body());
    out
}

fn parse_response(raw: &[u8]) -> Response<Vec<u8>> {
    let mut headers = [httparse::EMPTY_HEADER; 32];
    let mut r = httparse::Response::new(&mut headers);
    match r.parse(raw) {
        Ok(httparse::Status::Complete(n)) => {
            let mut b = Response::builder().status(r.code.unwrap_or(500));
            for h in r.headers.iter() { b = b.header(h.name, h.value); }
            b.body(raw[n..].to_vec()).unwrap()
        }
        _ => Response::builder().status(502).body(b"bad answer from the singer service".to_vec()).unwrap(),
    }
}

fn mime_of(path: &str) -> &'static str {
    match path.rsplit('.').next().unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "wav" => "audio/wav",
        "woff2" => "font/woff2",
        _ => "application/octet-stream",
    }
}

fn main() {
    tauri::Builder::default()
        .register_asynchronous_uri_scheme_protocol("singer", |ctx, request, responder| {
            let app = ctx.app_handle().clone();
            std::thread::spawn(move || {
                let path = request.uri().path().to_string();
                if path.starts_with("/api/singer/") {
                    let svc = app.state::<Arc<Service>>();
                    return responder.respond(parse_response(&svc.call(raw_request(&request))));
                }
                // pages: "/" and "/singer/..." both map onto the web folder (the same pages Mortiflix Music serves)
                let rel = path.trim_start_matches('/').trim_start_matches("singer/");
                let rel = if rel.is_empty() { "index.html" } else { rel };
                match app.asset_resolver().get(rel.to_string()) {
                    Some(a) => responder.respond(Response::builder().header("content-type", mime_of(rel)).body(a.bytes().to_vec()).unwrap()),
                    None => responder.respond(Response::builder().status(404).body(b"not found".to_vec()).unwrap()),
                }
            });
        })
        .setup(|app| {
            let svc = Service::spawn().map_err(|e| format!("could not start the singer service: {e}"))?;
            app.manage(svc);
            let url = if cfg!(windows) { "http://singer.localhost/index.html" } else { "singer://localhost/index.html" };
            let downloads = app.path().download_dir().ok();
            let w = WebviewWindowBuilder::new(app, "main", WebviewUrl::CustomProtocol(url.parse().unwrap()))
                .title("Mortiflix Singer")
                .inner_size(1440.0, 900.0)
                .min_inner_size(900.0, 600.0)
                .on_download(move |_w, ev| {
                    // exports (WAV, MIDI, MusicXML, projects) go straight to the Downloads folder
                    if let (tauri::webview::DownloadEvent::Requested { destination, .. }, Some(d)) = (ev, downloads.as_ref()) {
                        if let Some(name) = destination.file_name().map(|n| n.to_os_string()) { *destination = d.join(name); }
                    }
                    true
                })
                .build()?;
            #[cfg(target_os = "linux")]
            w.with_webview(|wv| {
                use webkit2gtk::{PermissionRequestExt, SettingsExt, WebViewExt};
                let view = wv.inner();
                if let Some(s) = view.settings() { s.set_enable_media_stream(true); s.set_enable_webaudio(true); }
                // the Booth needs the microphone: allow it for our own pages
                view.connect_permission_request(|_, req| { req.allow(); true });
            })?;
            let _ = w;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Mortiflix Singer")
        .run(|app, ev| {
            if let tauri::RunEvent::Exit = ev {
                if let Some(svc) = app.try_state::<Arc<Service>>() { let _ = svc.child.lock().unwrap().kill(); }
            }
        });
}
