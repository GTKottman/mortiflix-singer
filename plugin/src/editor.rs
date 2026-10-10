//! One small panel: which project, what's loaded, tempo check, gain, MIDI capture.

use crate::{capture, mix, BridgeParams, Shared};
use nih_plug::prelude::*;
use nih_plug_egui::egui::{self, Color32, RichText};
use nih_plug_egui::{create_egui_editor, widgets::ParamSlider};
use std::sync::atomic::Ordering;
use std::sync::Arc;

const ACCENT: Color32 = Color32::from_rgb(167, 139, 250);
const DIM: Color32 = Color32::from_rgb(150, 150, 160);
const WARN: Color32 = Color32::from_rgb(229, 72, 77);
const BG: Color32 = Color32::from_rgb(20, 16, 28);

pub fn create(params: Arc<BridgeParams>, shared: Arc<Shared>) -> Option<Box<dyn Editor>> {
    create_egui_editor(
        params.editor_state.clone(),
        (Vec::<String>::new(), String::new(), String::new()),
        |ctx, (list, _, _)| { ctx.set_visuals(egui::Visuals::dark()); *list = Vec::new(); },
        move |ctx, setter, (list, note, server_edit)| {
            egui::CentralPanel::default().frame(egui::Frame::default().fill(BG).inner_margin(16.0)).show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.label(RichText::new("MORTIFLIX SINGER").size(18.0).strong().color(ACCENT));
                    ui.label(RichText::new("bridge").color(DIM));
                });
                ui.add_space(10.0);
                let current = shared.project.read().map(|p| p.clone()).unwrap_or_default();
                let server = shared.server.read().map(|p| p.clone()).unwrap_or_default();
                if server_edit.is_empty() && !server.is_empty() { *server_edit = server.clone(); }
                ui.horizontal(|ui| {
                    ui.label("Renders from");
                    let r = ui.add(egui::TextEdit::singleline(server_edit).hint_text("this computer (or http://your-pc:4747)").desired_width(250.0));
                    if r.lost_focus() && server_edit.trim() != server {
                        if let Ok(mut w) = shared.server.write() { *w = server_edit.trim().to_string(); }
                        list.clear(); shared.reload.store(true, Ordering::Relaxed);
                    }
                });
                if list.is_empty() { *list = if server.is_empty() { mix::projects() } else { mix::remote_projects(&server) }; }
                ui.horizontal(|ui| {
                    ui.label("Project");
                    egui::ComboBox::from_id_salt("project")
                        .selected_text(if current.is_empty() { "choose…" } else { current.as_str() })
                        .width(260.0)
                        .show_ui(ui, |ui| {
                            for p in list.iter() {
                                if ui.selectable_label(*p == current, p).clicked() {
                                    if let Ok(mut w) = shared.project.write() { *w = p.clone(); }
                                    shared.reload.store(true, Ordering::Relaxed);
                                }
                            }
                        });
                    if ui.button("↻").on_hover_text("look for new projects").clicked() { list.clear(); }
                });
                ui.horizontal(|ui| {
                    let base = if server.is_empty() { "http://localhost:4747".to_string() } else { server.trim_end_matches('/').to_string() };
                    if ui.add_enabled(!current.is_empty(), egui::Button::new("Open in the editor")).clicked() {
                        open_url(&format!("{base}/singer/editor.html?project={}", current.replace(' ', "%20")));
                    }
                    if ui.add_enabled(shared.mix.lock().map(|m| m.is_some()).unwrap_or(false), egui::Button::new("Bounce to WAV")).clicked() {
                        *note = bounce(&shared, &current);
                    }
                });
                ui.add_space(6.0);
                ui.label(RichText::new(shared.status.lock().map(|s| s.clone()).unwrap_or_default()).color(DIM));
                // the vocals follow the DAW's beat position; a different tempo moves the starts but can't stretch the singing
                if let Some(m) = shared.mix.lock().ok().and_then(|m| m.clone()) {
                    let host = f32::from_bits(shared.host_bpm.load(Ordering::Relaxed)) as f64;
                    let mine = m.tempo.first_bpm();
                    if host > 0.0 && (host - mine).abs() > 0.05 {
                        ui.label(RichText::new(format!("The DAW is at {host:.2} BPM, the project at {mine:.2}: set them the same.")).color(WARN));
                    }
                }
                ui.add_space(12.0);
                ui.horizontal(|ui| { ui.label("Gain"); ui.add(ParamSlider::for_param(&params.gain, setter).with_width(220.0)); });
                ui.add_space(12.0);
                ui.separator();
                let mut cap = params.capture.value();
                if ui.checkbox(&mut cap, "Capture MIDI played into this track").changed() {
                    setter.begin_set_parameter(&params.capture);
                    setter.set_parameter(&params.capture, cap);
                    setter.end_set_parameter(&params.capture);
                }
                let count = shared.captured.lock().map(|c| c.iter().filter(|e| e.on).count()).unwrap_or(0);
                ui.horizontal(|ui| {
                    ui.label(RichText::new(format!("{count} notes captured")).color(DIM));
                    if ui.add_enabled(count > 0, egui::Button::new("Send to Singer")).clicked() {
                        *note = send(&shared, &current);
                    }
                    if ui.add_enabled(count > 0, egui::Button::new("Clear")).clicked() {
                        if let Ok(mut c) = shared.captured.lock() { c.clear(); }
                        note.clear();
                    }
                });
                if !note.is_empty() { ui.label(RichText::new(note.as_str()).color(DIM)); }
                ui.add_space(8.0);
                ui.label(RichText::new("Edit and render in Mortiflix Singer; the new take plays here within a second.").small().color(DIM));
            });
            ctx.request_repaint_after(std::time::Duration::from_millis(250));
        },
    )
}

fn send(shared: &Shared, project: &str) -> String {
    let events = shared.captured.lock().map(|c| c.clone()).unwrap_or_default();
    let bpm = f32::from_bits(shared.host_bpm.load(Ordering::Relaxed)) as f64;
    let dir = mix::home().join("inbox");
    let name = format!("{}-{}.mid", if project.is_empty() { "daw" } else { project },
                       std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0));
    match std::fs::create_dir_all(&dir).and_then(|_| std::fs::write(dir.join(&name), capture::to_smf(&events, if bpm > 0.0 { bpm } else { 120.0 }))) {
        Ok(_) => { if let Ok(mut c) = shared.captured.lock() { c.clear(); } format!("Sent: open the editor's Inbox ({name})") }
        Err(e) => format!("Could not write the inbox: {e}"),
    }
}

fn open_url(url: &str) {
    #[cfg(target_os = "windows")]
    let _ = std::process::Command::new("cmd").args(["/C", "start", "", url]).spawn();
    #[cfg(target_os = "macos")]
    let _ = std::process::Command::new("open").arg(url).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let _ = std::process::Command::new("xdg-open").arg(url).spawn();
}

/// The vocal as a WAV from bar 1, into Documents/Mortiflix Singer, to drop on an audio track.
fn bounce(shared: &Shared, project: &str) -> String {
    let Some(m) = shared.mix.lock().ok().and_then(|m| m.clone()) else { return "Nothing loaded yet".into() };
    let base = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")).unwrap_or_else(|_| ".".into());
    let dir = std::path::PathBuf::from(base).join("Documents").join("Mortiflix Singer");
    let path = dir.join(format!("Vocal - {project}.wav"));
    match std::fs::create_dir_all(&dir).map_err(|e| e.to_string()).and_then(|_| mix::bounce(&m, &path)) {
        Ok(_) => format!("Bounced: {}", path.display()),
        Err(e) => format!("Could not bounce: {e}"),
    }
}
