// Breaths: a breath note ("br") in the gap before every phrase that has at least half a beat of room.
export const title = 'Breaths before phrases';
export default function (singer) {
  const ppq = singer.project().ppq;
  singer.edit('add breaths', (p) => {
    const t = singer.app.trackOf(p), ns = [...t.notes].sort((a, b) => a.tick - b.tick);
    const add = [];
    ns.forEach((n, i) => {
      if (n.lyric === 'br') return;
      const prevEnd = i ? ns[i - 1].tick + ns[i - 1].dur : -Infinity;
      if (i && ns[i - 1].lyric === 'br') return;
      const room = n.tick - Math.max(prevEnd, 0);
      if (room >= ppq / 2) {
        const dur = Math.min(ppq, room - ppq / 8);
        add.push({ id: `br${Math.random().toString(36).slice(2, 9)}`, tick: n.tick - dur - ppq / 16, dur, pitch: n.pitch, lyric: 'br', vel: 64 });
      }
    });
    t.notes.push(...add.filter((b) => b.tick >= 0));
  });
}
