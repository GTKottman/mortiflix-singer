// Live pitch for the Booth: YIN on 2048-sample windows every 1024 samples, plus the raw samples for recording.
class Tracker extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; this.hop = 0; }
  yin(x, sr) {
    const W = 1024, maxTau = Math.min(W, Math.floor(sr / 55)), minTau = Math.floor(sr / 900);
    const d = new Float32Array(maxTau + 1);
    for (let tau = 1; tau <= maxTau; tau++) { let s = 0; for (let i = 0; i < W; i++) { const v = x[i] - x[i + tau]; s += v * v; } d[tau] = s; }
    let run = 0; const c = new Float32Array(maxTau + 1); c[0] = 1;
    for (let tau = 1; tau <= maxTau; tau++) { run += d[tau]; c[tau] = d[tau] * tau / (run || 1); }
    for (let tau = minTau; tau < maxTau; tau++) {
      if (c[tau] < 0.15) {
        while (tau + 1 < maxTau && c[tau + 1] < c[tau]) tau++;
        const a = c[tau - 1], b = c[tau], e = c[tau + 1], den = a - 2 * b + e;
        const t = den ? tau + (a - e) / (2 * den) : tau;
        return { f0: sr / t, clarity: 1 - b };
      }
    }
    return { f0: 0, clarity: 0 };
  }
  process(inputs) {
    const ch = inputs[0][0]; if (!ch) return true;
    this.port.postMessage({ pcm: ch.slice(0) });
    for (let i = 0; i < ch.length; i++) { this.buf[this.n++ % 2048] = ch[i]; }
    this.hop += ch.length;
    if (this.hop >= 1024 && this.n >= 2048) {
      this.hop = 0;
      const x = new Float32Array(2048), start = this.n % 2048;
      for (let i = 0; i < 2048; i++) x[i] = this.buf[(start + i) % 2048];
      let e = 0; for (let i = 1024; i < 2048; i++) e += x[i] * x[i];
      const rms = Math.sqrt(e / 1024);
      const p = rms > 0.004 ? this.yin(x, sampleRate) : { f0: 0, clarity: 0 };
      this.port.postMessage({ f0: p.f0, rms, t: currentTime });
    }
    return true;
  }
}
registerProcessor('tracker', Tracker);
