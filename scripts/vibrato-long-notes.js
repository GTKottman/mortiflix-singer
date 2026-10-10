// Vibrato on long notes: notes of a beat or more (selected, or all) get 35 cents of vibrato starting after 300 ms.
export const title = 'Vibrato on long notes';
export default function (singer) {
  const ppq = singer.project().ppq, sel = singer.app.sel;
  singer.edit('vibrato on long notes', (p) => {
    for (const n of singer.app.trackOf(p).notes) {
      if ((sel.size && !sel.has(n.id)) || n.dur < ppq || n.lyric === 'br') continue;
      n.vib_depth = 35; n.vib_start = 300; n.vib_rate = n.vib_rate || 5.5;
    }
  });
}
