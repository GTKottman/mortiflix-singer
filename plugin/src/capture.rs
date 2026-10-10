//! MIDI captured from the DAW while it plays, written as a standard MIDI file into ~/MortiflixSinger/inbox for the
//! editor to import (notes keep their beat positions; the project's words go on them there).

#[derive(Clone, Copy, Debug)]
pub struct Captured { pub beat: f64, pub note: u8, pub velocity: u8, pub on: bool }

fn vlq(mut v: u32, out: &mut Vec<u8>) {
    let mut bytes = vec![(v & 0x7f) as u8];
    v >>= 7;
    while v > 0 { bytes.push(((v & 0x7f) as u8) | 0x80); v >>= 7; }
    bytes.reverse();
    out.extend(bytes);
}

/// Format-0 MIDI file at 480 ticks per beat with the host tempo; tick 0 is the song's start.
pub fn to_smf(events: &[Captured], bpm: f64) -> Vec<u8> {
    let ppq = 480u32;
    let mut ev: Vec<Captured> = events.to_vec();
    ev.sort_by(|a, b| a.beat.partial_cmp(&b.beat).unwrap().then(a.on.cmp(&b.on)));   // offs before ons at the same tick
    let mut trk = Vec::new();
    let us = (60_000_000.0 / bpm.max(1.0)) as u32;
    trk.extend([0x00, 0xff, 0x51, 0x03, (us >> 16) as u8, (us >> 8) as u8, us as u8]);
    let mut last = 0u32;
    for e in &ev {
        let tick = (e.beat.max(0.0) * ppq as f64).round() as u32;      // absolute beats: the notes keep their place in the song
        vlq(tick - last.min(tick), &mut trk);
        last = tick.max(last);
        trk.extend([if e.on { 0x90 } else { 0x80 }, e.note, if e.on { e.velocity.max(1) } else { 0 }]);
    }
    trk.extend([0x00, 0xff, 0x2f, 0x00]);
    let mut out = b"MThd".to_vec();
    out.extend([0, 0, 0, 6, 0, 0, 0, 1, (ppq >> 8) as u8, ppq as u8]);
    out.extend(b"MTrk");
    out.extend((trk.len() as u32).to_be_bytes());
    out.extend(trk);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn smf_header_and_notes() {
        let ev = [Captured { beat: 4.0, note: 60, velocity: 100, on: true }, Captured { beat: 5.0, note: 60, velocity: 0, on: false }];
        let b = to_smf(&ev, 120.0);
        assert_eq!(&b[..4], b"MThd");
        assert_eq!(&b[14..18], b"MTrk");
        // tempo event, note on at beat 4 (1920 = 0x8f 0x00), note off one beat (480 = 0x83 0x60) later
        let trk = &b[22..];
        assert_eq!(&trk[7..12], &[0x8f, 0x00, 0x90, 60, 100]);
        assert_eq!(&trk[12..17], &[0x83, 0x60, 0x80, 60, 0]);
    }
}
