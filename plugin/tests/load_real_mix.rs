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

#[test]
fn the_same_mix_from_a_render_server() {
    // Mortiflix Music on this machine stands in for the PC a laptop would use; skipped when it isn't running
    let server = "http://localhost:4747";
    if !mix::remote_projects(server).iter().any(|p| p == "Bridge test") { eprintln!("skipped: no server with 'Bridge test'"); return; }
    let local = mix::load("Bridge test", 48000.0, "").expect("local");
    let remote = mix::load("Bridge test", 48000.0, server).expect("remote");
    assert_eq!(remote.phrases, local.phrases);
    assert_eq!(remote.missing, 0);
    assert_eq!(remote.left.len(), local.left.len());
    let diff = remote.left.iter().zip(&local.left).map(|(a, b)| (a - b).abs()).fold(0f32, f32::max);
    assert!(diff < 1e-6, "the downloaded phrases are the rendered ones (max diff {diff})");
}
