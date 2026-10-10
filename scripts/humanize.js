// Humanize: starts move up to 1/64 note either way and velocities vary a little (selected notes, or all).
// The same project always gets the same result (a fixed seed), so a re-run doesn't keep drifting it.
export const title = 'Humanize timing and dynamics';
export default function (singer) {
  const ppq = singer.project().ppq, sel = singer.app.sel;
  let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647) * 2 - 1;
  singer.edit('humanize', (p) => {
    for (const n of singer.app.trackOf(p).notes) {
      if (sel.size && !sel.has(n.id)) continue;
      const d = Math.round(rnd() * ppq / 16);
      n.tick = Math.max(0, n.tick + d); n.dur = Math.max(ppq / 16, n.dur - d);
      n.vel = Math.max(1, Math.min(127, Math.round((n.vel ?? 64) + rnd() * 10)));
    }
  });
}
