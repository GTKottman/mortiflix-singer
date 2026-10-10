//! The project's rendered vocals, as the DAW hears them: `<project>.mix.json` (written by the singer service on every
//! final render) lists each track's phrases; they are mixed once into one stereo buffer at the host's sample rate.

use std::path::{Path, PathBuf};

/// Where Mortiflix Singer keeps its projects: $SINGER_HOME or ~/MortiflixSinger (the same rule as the service).
pub fn home() -> PathBuf {
    if let Ok(h) = std::env::var("SINGER_HOME") { return PathBuf::from(h); }
    let base = std::env::var("USERPROFILE").or_else(|_| std::env::var("HOME")).unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join("MortiflixSinger")
}

pub fn projects() -> Vec<String> {
    let mut out: Vec<String> = std::fs::read_dir(home().join("projects"))
        .map(|rd| rd.filter_map(|e| e.ok()).filter_map(|e| {
            let n = e.file_name().to_string_lossy().into_owned();
            n.strip_suffix(".msing").map(|s| s.to_string())
        }).collect())
        .unwrap_or_default();
    out.sort();
    out
}

pub fn manifest_path(project: &str) -> PathBuf { home().join("projects").join(format!("{project}.mix.json")) }

/// Ticks <-> milliseconds through the project's tempo map.
#[derive(Clone, Debug)]
pub struct TempoMap { ppq: f64, ticks: Vec<f64>, bpms: Vec<f64>, ms: Vec<f64> }

impl TempoMap {
    pub fn new(ppq: f64, mut pts: Vec<(f64, f64)>) -> Self {
        pts.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
        if pts.is_empty() { pts.push((0.0, 120.0)); }
        if pts[0].0 != 0.0 { let b = pts[0].1; pts.insert(0, (0.0, b)); }
        let (mut ticks, mut bpms, mut ms, mut acc) = (vec![], vec![], vec![], 0.0);
        for (i, &(t, b)) in pts.iter().enumerate() {
            if i > 0 { acc += (t - pts[i - 1].0) * 60000.0 / (pts[i - 1].1 * ppq); }
            ticks.push(t); bpms.push(b); ms.push(acc);
        }
        TempoMap { ppq, ticks, bpms, ms }
    }
    pub fn beats_to_ms(&self, beats: f64) -> f64 {
        let tick = beats * self.ppq;
        let i = self.ticks.iter().rposition(|&t| t <= tick).unwrap_or(0);
        self.ms[i] + (tick - self.ticks[i]) * 60000.0 / (self.bpms[i] * self.ppq)
    }
    pub fn first_bpm(&self) -> f64 { self.bpms[0] }
}

pub struct Mix {
    pub left: Vec<f32>,
    pub right: Vec<f32>,
    pub sample_rate: f32,
    pub tempo: TempoMap,
    pub phrases: usize,
    pub missing: usize,
    pub updated: f64,
}

fn read_wav(path: &Path) -> Option<(Vec<f32>, u32)> {
    let mut r = hound::WavReader::open(path).ok()?;
    let spec = r.spec();
    let ch = spec.channels.max(1) as usize;
    let data: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => r.samples::<f32>().filter_map(|s| s.ok()).collect(),
        hound::SampleFormat::Int => {
            let scale = 1.0 / (1u64 << (spec.bits_per_sample - 1)) as f32;
            r.samples::<i32>().filter_map(|s| s.ok()).map(|s| s as f32 * scale).collect()
        }
    };
    Some((data.chunks(ch).map(|c| c.iter().sum::<f32>() / ch as f32).collect(), spec.sample_rate))
}

/// Linear resampling: enough for placing finished vocals at the host's rate.
fn resample(x: &[f32], from: f32, to: f32) -> Vec<f32> {
    if (from - to).abs() < 0.5 || x.is_empty() { return x.to_vec(); }
    let n = ((x.len() as f64) * to as f64 / from as f64) as usize;
    let step = from as f64 / to as f64;
    (0..n).map(|i| {
        let p = i as f64 * step;
        let k = p as usize;
        let f = (p - k as f64) as f32;
        let a = x[k.min(x.len() - 1)];
        let b = x[(k + 1).min(x.len() - 1)];
        a + (b - a) * f
    }).collect()
}

pub fn load(project: &str, host_sr: f32) -> Result<Mix, String> {
    let text = std::fs::read_to_string(manifest_path(project)).map_err(|_| "not rendered yet: render it in Mortiflix Singer".to_string())?;
    let m: serde_json::Value = serde_json::from_str(&text).map_err(|e| format!("bad mix file: {e}"))?;
    let ppq = m["ppq"].as_f64().unwrap_or(480.0);
    let tempo = TempoMap::new(ppq, m["tempo"].as_array().map(|a| a.iter().map(|p| (p["tick"].as_f64().unwrap_or(0.0), p["bpm"].as_f64().unwrap_or(120.0))).collect()).unwrap_or_default());
    let tracks = m["tracks"].as_array().cloned().unwrap_or_default();
    let soloed = tracks.iter().any(|t| t["solo"].as_bool().unwrap_or(false));
    let (mut left, mut right) = (Vec::<f32>::new(), Vec::<f32>::new());
    let (mut phrases, mut missing) = (0, 0);
    for t in &tracks {
        if t["mute"].as_bool().unwrap_or(false) || (soloed && !t["solo"].as_bool().unwrap_or(false)) { continue; }
        let g = 10f32.powf(t["gain_db"].as_f64().unwrap_or(0.0) as f32 / 20.0);
        let pan = t["pan"].as_f64().unwrap_or(0.0) as f32;
        let (gl, gr) = (((pan + 1.0) * std::f32::consts::FRAC_PI_4).cos() * 2f32.sqrt() * g, ((pan + 1.0) * std::f32::consts::FRAC_PI_4).sin() * 2f32.sqrt() * g);
        for ph in t["phrases"].as_array().cloned().unwrap_or_default() {
            let Some((y, sr)) = ph["file"].as_str().and_then(|f| read_wav(Path::new(f))) else { missing += 1; continue };
            let y = resample(&y, sr as f32, host_sr);
            let start = (ph["start_ms"].as_f64().unwrap_or(0.0) / 1000.0 * host_sr as f64).round() as i64;
            let (skip, a) = if start < 0 { ((-start) as usize, 0usize) } else { (0, start as usize) };
            let y = &y[skip.min(y.len())..];
            if left.len() < a + y.len() { left.resize(a + y.len(), 0.0); right.resize(a + y.len(), 0.0); }
            let n = y.len();
            let k = (host_sr as usize / 100).min(n / 2);           // 10 ms fades at the phrase edges
            for (i, &s) in y.iter().enumerate() {
                let fade = if i < k { i as f32 / k as f32 } else if i >= n - k { (n - i) as f32 / k as f32 } else { 1.0 };
                left[a + i] += s * fade * gl;
                right[a + i] += s * fade * gr;
            }
            phrases += 1;
        }
    }
    Ok(Mix { left, right, sample_rate: host_sr, tempo, phrases, missing, updated: m["updated"].as_f64().unwrap_or(0.0) })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tempo_map_two_tempos() {
        let t = TempoMap::new(480.0, vec![(0.0, 120.0), (1920.0, 60.0)]);
        assert!((t.beats_to_ms(2.0) - 1000.0).abs() < 1e-6);   // 2 beats at 120
        assert!((t.beats_to_ms(5.0) - 3000.0).abs() < 1e-6);   // 4 beats at 120 = 2 s, then 1 beat at 60 = 1 s
    }

    #[test]
    fn resample_length() {
        let x = vec![0.0f32; 44100];
        assert_eq!(resample(&x, 44100.0, 48000.0).len(), 48000);
    }
}
