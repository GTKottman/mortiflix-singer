// Playback: rendered phrases scheduled on the song timeline (per-track gain, pan, mute, solo); notes not rendered
// yet play as a soft guide tone so the song is always audible while it renders.
import { tempoMap, trackNotes } from './model.js';

export class Player {
  constructor(app) { this.app = app; this.ctx = null; this.buffers = new Map(); this.nodes = []; this.playing = false; this.startAt = 0; this.startMs = 0; }
  audio() { if (!this.ctx) { this.ctx = new AudioContext(); this.out = this.ctx.createGain(); this.out.connect(this.ctx.destination); } return this.ctx; }
  async buffer(url) {
    if (this.buffers.has(url)) return this.buffers.get(url);
    const p = fetch(url).then((r) => r.arrayBuffer()).then((b) => this.audio().decodeAudioData(b));
    this.buffers.set(url, p); return p;
  }
  tone(midi, at, dur, gain = 0.12, dest) {
    const ctx = this.audio(), o = ctx.createOscillator(), g = ctx.createGain();
    o.type = 'triangle'; o.frequency.value = 440 * 2 ** ((midi - 69) / 12);
    g.gain.setValueAtTime(0, at); g.gain.linearRampToValueAtTime(gain, at + 0.02); g.gain.setValueAtTime(gain, at + Math.max(0.03, dur - 0.05)); g.gain.linearRampToValueAtTime(0, at + dur);
    o.connect(g).connect(dest || this.out); o.start(at); o.stop(at + dur + 0.05); this.nodes.push(o); return o;
  }
  preview(midi) { const ctx = this.audio(); if (ctx.state === 'suspended') ctx.resume(); this.tone(midi, ctx.currentTime + 0.01, 0.35, 0.15); }
  nowMs() { return this.playing ? this.startMs + (this.audio().currentTime - this.startAt) * 1000 : null; }
  async play(fromTick) {
    this.stop();
    const ctx = this.audio(); if (ctx.state === 'suspended') await ctx.resume();
    const p = this.app.project(), tm = tempoMap(p), from = tm.toMs(fromTick);
    const soloed = p.tracks.some((t) => t.solo);
    const lead = 0.12, t0 = ctx.currentTime + lead;
    this.startAt = t0; this.startMs = from; this.playing = true;
    const bk = p.backing;
    if (bk?.file && !bk.mute && !soloed) {                    // the instrumental, in sync, under the vocals
      const g = ctx.createGain(); g.gain.value = 10 ** ((bk.gain_db || 0) / 20); g.connect(this.out); this.nodes.push(g);
      this.buffer(`${this.app.api}/backing/${bk.file}`).then((buf) => {
        if (!this.playing) return;
        const src = ctx.createBufferSource(); src.buffer = buf; src.connect(g);
        const when = t0 + ((bk.offset_ms || 0) - from) / 1000;
        if (when >= ctx.currentTime) src.start(when); else if (ctx.currentTime - when < buf.duration) src.start(ctx.currentTime, ctx.currentTime - when);
        this.nodes.push(src);
      });
    }
    for (const t of p.tracks) {
      if (t.mute || (soloed && !t.solo)) continue;
      const g = ctx.createGain(); g.gain.value = 10 ** ((t.gain_db || 0) / 20);
      const pan = ctx.createStereoPanner(); pan.pan.value = t.pan || 0; g.connect(pan).connect(this.out); this.nodes.push(g, pan);
      const phrases = this.app.renders[t.id] || [];
      const covered = (ms) => phrases.some((ph) => ms >= ph.start_ms && ms <= ph.end_ms);
      for (const ph of phrases) {
        if (ph.end_ms < from) continue;
        this.buffer(ph.url).then((buf) => {
          if (!this.playing) return;
          const src = ctx.createBufferSource(); src.buffer = buf; src.connect(g);
          const when = t0 + (ph.start_ms - from) / 1000;
          if (when >= ctx.currentTime) src.start(when); else src.start(ctx.currentTime, ctx.currentTime - when);
          this.nodes.push(src);
        });
      }
      if (this.app.guide) for (const n of trackNotes(p, t)) {      // guide tones for what isn't rendered (group copies too)
        const a = tm.toMs(n.tick), b = tm.toMs(n.tick + n.dur);
        if (b < from || covered(a + 1)) continue;
        this.tone(n.pitch + (t.transpose || 0), t0 + Math.max(0, a - from) / 1000, (b - Math.max(a, from)) / 1000, 0.08, g);
      }
    }
    const tick = () => { if (!this.playing) return; this.app.onPlayhead(tm.toTick(this.nowMs())); requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }
  stop() {
    this.playing = false;
    for (const n of this.nodes) { try { n.stop?.(); } catch {} try { n.disconnect(); } catch {} }
    this.nodes = [];
  }
}
