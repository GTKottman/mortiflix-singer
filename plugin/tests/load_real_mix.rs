//! Against a real render: run the singer service, render a project named "Bridge test" (notes from beat 4), then
//! `cargo test`. Skipped when that project hasn't been rendered on this machine.
use mortiflix_singer_bridge::mix;

#[test]
fn bridge_test_project_sings_on_its_beat() {
    if !mix::manifest_path("Bridge test").exists() { eprintln!("skipped: no rendered 'Bridge test'"); return; }
    let m = mix::load("Bridge test", 48000.0, "").expect("loads");
    assert!(m.phrases >= 1 && m.missing == 0);
    let at = |beats: f64| (m.tempo.beats_to_ms(beats) / 1000.0 * 48000.0) as usize;
    let rms = |a: usize, b: usize| (m.left[a..b].iter().map(|x| x * x).sum::<f32>() / (b - a) as f32).sqrt();
    let before = rms(at(1.0), at(3.0));             // nothing is written before beat 4
    let sung = rms(at(4.1), at(6.0));               // "ride the" from beat 4
    assert!(before < 1e-3, "silence before the first note, got {before}");
    assert!(sung > 0.02, "singing from beat 4, got {sung}");
}
