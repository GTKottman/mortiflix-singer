//! Mortiflix Singer Bridge: put it on an instrument track, pick a Singer project, and the DAW plays that project's
//! rendered vocals in time with its own beat position. Edits rendered in Mortiflix Singer arrive within a second.
//! With Capture on, the notes the DAW plays into it are kept and can be sent to the editor's inbox.

use nih_plug::prelude::*;
use nih_plug_egui::EguiState;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex, RwLock};

pub mod capture;
mod editor;
pub mod mix;

/// What the loader thread, the audio thread and the editor share.
pub struct Shared {
    pub project: Arc<RwLock<String>>,
    pub mix: Mutex<Option<Arc<mix::Mix>>>,
    pub status: Mutex<String>,
    pub host_sr: AtomicU32,
    pub host_bpm: AtomicU32,
    pub stop: AtomicBool,
    pub reload: AtomicBool,
    pub captured: Mutex<Vec<capture::Captured>>,
}

#[derive(Params)]
pub struct BridgeParams {
    #[persist = "editor-state"]
    pub editor_state: Arc<EguiState>,
    #[persist = "project"]
    pub project: Arc<RwLock<String>>,
    #[id = "gain"]
    pub gain: FloatParam,
    #[id = "capture"]
    pub capture: BoolParam,
}

pub struct Bridge {
    params: Arc<BridgeParams>,
    shared: Arc<Shared>,
    current: Option<Arc<mix::Mix>>,
    loader: Option<std::thread::JoinHandle<()>>,
    sr: f32,
}

impl Default for Bridge {
    fn default() -> Self {
        let project = Arc::new(RwLock::new(String::new()));
        let params = Arc::new(BridgeParams {
            editor_state: EguiState::from_size(520, 360),
            project: project.clone(),
            gain: FloatParam::new("Gain", 0.0, FloatRange::Linear { min: -30.0, max: 12.0 })
                .with_unit(" dB").with_step_size(0.1).with_smoother(SmoothingStyle::Linear(30.0)),
            capture: BoolParam::new("Capture MIDI", false),
        });
        let shared = Arc::new(Shared {
            project,
            mix: Mutex::new(None),
            status: Mutex::new("Pick a project".into()),
            host_sr: AtomicU32::new(44100f32.to_bits()),
            host_bpm: AtomicU32::new(0f32.to_bits()),
            stop: AtomicBool::new(false),
            reload: AtomicBool::new(true),
            captured: Mutex::new(Vec::with_capacity(8192)),
        });
        Self { params, shared, current: None, loader: None, sr: 44100.0 }
    }
}

/// Watches the chosen project's mix file and reloads it when it changes (or the project or sample rate does).
fn loader(shared: Arc<Shared>) {
    let mut seen: Option<(String, std::time::SystemTime, u32)> = None;
    while !shared.stop.load(Ordering::Relaxed) {
        let project = shared.project.read().map(|p| p.clone()).unwrap_or_default();
        let sr_bits = shared.host_sr.load(Ordering::Relaxed);
        if project.is_empty() {
            *shared.status.lock().unwrap() = "Pick a project".into();
            *shared.mix.lock().unwrap() = None;
            seen = None;
        } else {
            let mtime = std::fs::metadata(mix::manifest_path(&project)).and_then(|m| m.modified()).ok();
            let key = mtime.map(|t| (project.clone(), t, sr_bits));
            if shared.reload.swap(false, Ordering::Relaxed) || key != seen {
                let st = match mix::load(&project, f32::from_bits(sr_bits)) {
                    Ok(m) => {
                        let s = format!("{} phrases, {:.0} s{}", m.phrases, m.left.len() as f32 / m.sample_rate,
                                        if m.missing > 0 { format!(" ({} not rendered: render again)", m.missing) } else { String::new() });
                        *shared.mix.lock().unwrap() = Some(Arc::new(m));
                        s
                    }
                    Err(e) => { *shared.mix.lock().unwrap() = None; e }
                };
                *shared.status.lock().unwrap() = st;
                seen = key;
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(500));
    }
}

impl Drop for Bridge {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.loader.take() { let _ = h.join(); }
    }
}

impl Plugin for Bridge {
    const NAME: &'static str = "Mortiflix Singer";
    const VENDOR: &'static str = "Mortiflix";
    const URL: &'static str = "https://github.com/GTKottman/mortiflix-singer";
    const EMAIL: &'static str = "";
    const VERSION: &'static str = env!("CARGO_PKG_VERSION");

    const AUDIO_IO_LAYOUTS: &'static [AudioIOLayout] = &[AudioIOLayout {
        main_input_channels: None,
        main_output_channels: NonZeroU32::new(2),
        ..AudioIOLayout::const_default()
    }];
    const MIDI_INPUT: MidiConfig = MidiConfig::Basic;

    type SysExMessage = ();
    type BackgroundTask = ();

    fn params(&self) -> Arc<dyn Params> { self.params.clone() }

    fn editor(&mut self, _async_executor: AsyncExecutor<Self>) -> Option<Box<dyn Editor>> {
        editor::create(self.params.clone(), self.shared.clone())
    }

    fn initialize(&mut self, _layout: &AudioIOLayout, config: &BufferConfig, _context: &mut impl InitContext<Self>) -> bool {
        self.sr = config.sample_rate;
        if self.shared.host_sr.swap(config.sample_rate.to_bits(), Ordering::Relaxed) != config.sample_rate.to_bits() {
            self.shared.reload.store(true, Ordering::Relaxed);
        }
        if self.loader.is_none() {
            let s = self.shared.clone();
            self.loader = Some(std::thread::spawn(move || loader(s)));
        }
        true
    }

    fn process(&mut self, buffer: &mut Buffer, _aux: &mut AuxiliaryBuffers, context: &mut impl ProcessContext<Self>) -> ProcessStatus {
        // a newly loaded mix replaces the current one between blocks (never waits on the loader)
        if let Ok(mut slot) = self.shared.mix.try_lock() {
            match (&*slot, &self.current) {
                (Some(a), Some(b)) if Arc::ptr_eq(a, b) => {}
                _ => self.current = slot.clone(),
            }
            if slot.is_none() { self.current = None; }
            let _ = &mut slot;
        }
        let t = context.transport();
        if let Some(bpm) = t.tempo { self.shared.host_bpm.store((bpm as f32).to_bits(), Ordering::Relaxed); }
        let playing = t.playing;
        let pos_beats = t.pos_beats();
        let bpm = t.tempo.unwrap_or(120.0);

        // MIDI capture: notes with their beat positions, while the DAW plays
        let capturing = self.params.capture.value() && playing;
        while let Some(ev) = context.next_event() {
            if !capturing { continue; }
            let (timing, note, vel, on) = match ev {
                NoteEvent::NoteOn { timing, note, velocity, .. } => (timing, note, velocity, true),
                NoteEvent::NoteOff { timing, note, .. } => (timing, note, 0.0, false),
                _ => continue,
            };
            if let (Some(b), Ok(mut cap)) = (pos_beats, self.shared.captured.try_lock()) {
                if cap.len() < cap.capacity() {
                    cap.push(capture::Captured { beat: b + timing as f64 / self.sr as f64 * bpm / 60.0, note, velocity: (vel * 127.0) as u8, on });
                }
            }
        }

        let n = buffer.samples();
        let out = buffer.as_slice();
        let (l, r) = out.split_at_mut(1);
        let (l, r) = (&mut *l[0], &mut *r[0]);
        l.fill(0.0);
        r.fill(0.0);
        let (Some(m), true, Some(beats)) = (&self.current, playing, pos_beats) else { return ProcessStatus::Normal };
        let start = (m.tempo.beats_to_ms(beats) / 1000.0 * m.sample_rate as f64).round() as i64;
        for i in 0..n {
            let g = util::db_to_gain(self.params.gain.smoothed.next());
            let k = start + i as i64;
            if k >= 0 && (k as usize) < m.left.len() {
                l[i] = m.left[k as usize] * g;
                r[i] = m.right[k as usize] * g;
            }
        }
        ProcessStatus::Normal
    }
}

impl ClapPlugin for Bridge {
    const CLAP_ID: &'static str = "com.mortiflix.singer.bridge";
    const CLAP_DESCRIPTION: Option<&'static str> = Some("Plays Mortiflix Singer vocals in time with your DAW");
    const CLAP_MANUAL_URL: Option<&'static str> = Some(Self::URL);
    const CLAP_SUPPORT_URL: Option<&'static str> = None;
    const CLAP_FEATURES: &'static [ClapFeature] = &[ClapFeature::Instrument, ClapFeature::Stereo];
}

impl Vst3Plugin for Bridge {
    const VST3_CLASS_ID: [u8; 16] = *b"MortiflixSingBr1";
    const VST3_SUBCATEGORIES: &'static [Vst3SubCategory] = &[Vst3SubCategory::Instrument, Vst3SubCategory::Stereo];
}

nih_export_clap!(Bridge);
nih_export_vst3!(Bridge);
