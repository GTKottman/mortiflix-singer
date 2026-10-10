// Legato: each note (the selected ones, or all) grows to meet the next note when the gap is shorter than an eighth.
export const title = 'Legato (close small gaps)';
export default function (singer) {
  const ppq = singer.project().ppq, sel = singer.app.sel;
  singer.edit('legato', (p) => {
    const t = singer.app.trackOf(p), ns = [...t.notes].sort((a, b) => a.tick - b.tick);
    ns.forEach((n, i) => {
      const next = ns[i + 1]; if (!next || (sel.size && !sel.has(n.id))) return;
      const gap = next.tick - (n.tick + n.dur);
      if (gap > 0 && gap < ppq / 2) n.dur += gap;
    });
  });
}
