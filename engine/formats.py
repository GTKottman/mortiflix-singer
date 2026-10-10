"""Import and export: MIDI (with lyric events), MusicXML, UTAU .ust, Synthesizer V .svp, Vocaloid .vsqx -> a project;
a project -> MIDI with lyrics, MusicXML. Notes are kept in ticks at the project's ppq (480)."""
from __future__ import annotations
import io, json, re, uuid
import xml.etree.ElementTree as ET
import mido
from .project import new_project

PPQ = 480
nid = lambda: uuid.uuid4().hex[:8]


def _note(tick, dur, pitch, lyric):
    return {'id': nid(), 'tick': int(round(tick)), 'dur': max(1, int(round(dur))), 'pitch': int(pitch), 'lyric': lyric or 'la', 'vel': 64}


def from_midi(data: bytes, title='Imported'):
    mf = mido.MidiFile(file=io.BytesIO(data))
    k = PPQ / mf.ticks_per_beat
    p = new_project(title); p['tempo'] = []; p['tracks'] = []
    lyrics = {}                               # tick -> word, from any track's lyric/text events
    parts, sigs = {}, []
    for ti, tr in enumerate(mf.tracks):
        t, on, name = 0, {}, f'Track {ti + 1}'
        for m in tr:
            t += m.time
            if m.type == 'set_tempo': p['tempo'].append({'tick': int(t * k), 'bpm': round(mido.tempo2bpm(m.tempo), 3)})
            elif m.type == 'time_signature': sigs.append((int(t * k), m.numerator, m.denominator))
            elif m.type == 'track_name': name = m.name or name
            elif m.type in ('lyrics', 'text') and m.text.strip() and not m.text.startswith(('@', '%')): lyrics[int(t * k)] = m.text.strip()
            elif m.type == 'note_on' and m.velocity > 0: on[(m.channel, m.note)] = (t, m.velocity)
            elif m.type in ('note_off', 'note_on') and (m.channel, m.note) in on:
                s, v = on.pop((m.channel, m.note))
                parts.setdefault((ti, m.channel, name), []).append({**_note(s * k, (t - s) * k, m.note, None), 'vel': v})
    p['tempo'] = p['tempo'] or [{'tick': 0, 'bpm': 120}]
    sigs = sorted(set(sigs))
    if sigs:                                  # the first meter is the song's; later ones become meter changes at their bars
        p['time_sig'] = [sigs[0][1], sigs[0][2]] if sigs[0][0] == 0 else p['time_sig']
        p['meters'] = []
        for tick, n, d in sigs:
            if tick == 0: continue
            segs = bar_segments(p); b0, t0, n0, d0 = segs[-1]
            bar = b0 + round((tick - t0) / (PPQ * 4 * n0 / d0))
            p['meters'].append({'bar': int(bar), 'num': n, 'den': d})
        if not p['meters']: del p['meters']
    for (ti, ch, name), notes in parts.items():
        if ch == 9: continue                  # drums are not sung
        notes.sort(key=lambda n: n['tick'])
        for a, b in zip(notes, notes[1:]):   # one voice: cut overlaps
            if a['tick'] + a['dur'] > b['tick']: a['dur'] = max(1, b['tick'] - a['tick'])
        for n in notes: n['lyric'] = lyrics.get(n['tick'], 'la')
        tr = new_project()['tracks'][0]; tr.update(id=nid(), name=name, notes=notes)
        p['tracks'].append(tr)
    if not p['tracks']: p['tracks'] = new_project()['tracks']
    return p


def to_midi(project) -> bytes:
    mf = mido.MidiFile(ticks_per_beat=project.get('ppq', PPQ))
    cond = mido.MidiTrack(); mf.tracks.append(cond)
    metas = [(tp['tick'], mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(tp['bpm']))) for tp in project.get('tempo', [])]
    metas += [(t0, mido.MetaMessage('time_signature', numerator=n, denominator=d)) for _, t0, n, d in bar_segments(project)]
    last = 0
    for tick, msg in sorted(metas, key=lambda x: (x[0], x[1].type != 'time_signature')):
        cond.append(msg.copy(time=int(tick) - last)); last = int(tick)
    for ci, t in enumerate(project['tracks']):
        tr = mido.MidiTrack(); mf.tracks.append(tr); tr.append(mido.MetaMessage('track_name', name=t['name'], time=0))
        ev = []
        for n in t['notes']:
            ev.append((n['tick'], 1, mido.MetaMessage('lyrics', text=n.get('lyric', 'la'), time=0)))
            ev.append((n['tick'], 2, mido.Message('note_on', channel=ci % 16 if ci % 16 != 9 else 10, note=n['pitch'], velocity=n.get('vel', 64), time=0)))
            ev.append((n['tick'] + n['dur'], 0, mido.Message('note_off', channel=ci % 16 if ci % 16 != 9 else 10, note=n['pitch'], velocity=0, time=0)))
        last = 0
        for t_, _, m in sorted(ev, key=lambda e: (e[0], e[1])):
            m.time = t_ - last; last = t_; tr.append(m)
    buf = io.BytesIO(); mf.save(file=buf); return buf.getvalue()


def from_ust(text: str, title='UST'):
    """UTAU: [#SETTING] Tempo=..., then [#0000] Length (ticks @480), Lyric, NoteNum; "R" = rest."""
    p = new_project(title); notes = []; tick = 0; cur = {}
    tempo = 120.0
    for line in text.splitlines() + ['[#END]']:
        line = line.strip()
        if line.startswith('[#'):
            if cur.get('Length'):
                ln = int(float(cur['Length'])); ly = cur.get('Lyric', 'la')
                if ly not in ('R', 'r', ''): notes.append(_note(tick, ln, int(cur.get('NoteNum', 60)), '_' if ly.startswith('-') else ly))
                tick += ln
            cur = {}
        elif '=' in line:
            k, v = line.split('=', 1); cur[k] = v
            if k == 'Tempo': tempo = float(v)
    p['tempo'] = [{'tick': 0, 'bpm': tempo}]; p['tracks'][0]['notes'] = notes
    return p


def from_svp(text: str, title='SVP'):
    """Synthesizer V project (JSON): time in blicks (705600000 per quarter); notes per group, groups referenced by tracks."""
    d = json.loads(text.lstrip('﻿').rstrip('\x00'))
    B = 705600000
    p = new_project(title); p['tracks'] = []
    tm = d.get('time', {})
    p['tempo'] = [{'tick': int(x['position'] / B * PPQ), 'bpm': x['bpm']} for x in tm.get('tempo', [])] or [{'tick': 0, 'bpm': 120}]
    if tm.get('meter'): p['time_sig'] = [tm['meter'][0].get('numerator', 4), tm['meter'][0].get('denominator', 4)]
    groups = {g['uuid']: g for g in d.get('library', [])}
    for t in d.get('tracks', []):
        notes = []
        refs = [(t.get('mainGroup', {}), 0)] + [(groups.get(r.get('groupID'), {}), r.get('blickOffset', 0)) for r in t.get('groups', [])]
        for g, off in refs:
            for n in g.get('notes', []):
                ly = n.get('lyrics', 'la')
                notes.append(_note((n['onset'] + off) / B * PPQ, n['duration'] / B * PPQ, n.get('pitch', 60), '_' if ly in ('-', '+') else ly))
        tr = new_project()['tracks'][0]; tr.update(id=nid(), name=t.get('name', 'Track'), notes=sorted(notes, key=lambda n: n['tick']))
        p['tracks'].append(tr)
    if not p['tracks']: p['tracks'] = new_project()['tracks']
    return p


def from_vsqx(text: str, title='VSQX'):
    """Vocaloid 3/4 (.vsqx): vsTrack > musicalPart (posTick) > note (posTick/t, durTick/dur, noteNum/n, lyric/y)."""
    text = re.sub(r'\sxmlns(:\w+)?="[^"]*"', '', text, count=0)
    root = ET.fromstring(text)
    g = lambda e, *names: next((e.findtext(n) for n in names if e.find(n) is not None), None)
    p = new_project(title); p['tracks'] = []
    res = int(g(root.find('.//masterTrack') if root.find('.//masterTrack') is not None else root, 'resolution') or 480)
    tempos = []
    for t in root.iter('tempo'):
        tick = g(t, 'posTick', 't'); bpm = g(t, 'bpm', 'v')
        if tick is not None and bpm is not None: tempos.append({'tick': int(int(tick) * PPQ / res), 'bpm': int(bpm) / 100})
    p['tempo'] = tempos or [{'tick': 0, 'bpm': 120}]
    for vt in root.iter('vsTrack'):
        notes = []
        for part in vt.iter('musicalPart'):
            base = int(g(part, 'posTick', 't') or 0)
            for n in part.iter('note'):
                ly = g(n, 'lyric', 'y') or 'la'
                notes.append(_note((base + int(g(n, 'posTick', 't'))) * PPQ / res, int(g(n, 'durTick', 'dur')) * PPQ / res, int(g(n, 'noteNum', 'n')), '_' if ly in ('-', '+') else ly))
        tr = new_project()['tracks'][0]; tr.update(id=nid(), name=g(vt, 'trackName', 'name') or 'Track', notes=notes)
        p['tracks'].append(tr)
    if not p['tracks']: p['tracks'] = new_project()['tracks']
    return p


STEPS = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def from_musicxml(text: str, title='MusicXML'):
    """Partwise MusicXML: notes with pitch/duration/lyric per part; ties and syllabic begin/middle become '-' joins."""
    root = ET.fromstring(re.sub(r'<!DOCTYPE[^>]*>', '', text))
    p = new_project(title); p['tracks'] = []
    for part in root.findall('part'):
        notes, tick, div, tempo = [], 0, 1, None
        for meas in part.findall('measure'):
            for el in meas:
                if el.tag == 'attributes' and el.findtext('divisions'): div = int(el.findtext('divisions'))
                if el.tag == 'direction' and el.find('.//sound') is not None and el.find('.//sound').get('tempo'): tempo = tempo or float(el.find('.//sound').get('tempo'))
                if el.tag == 'backup': tick -= int(el.findtext('duration')) * PPQ / div
                if el.tag == 'forward': tick += int(el.findtext('duration')) * PPQ / div
                if el.tag != 'note': continue
                if el.find('chord') is not None: continue
                dur = int(el.findtext('duration') or 0) * PPQ / div
                if el.find('rest') is None and el.find('pitch') is not None:
                    pt = el.find('pitch')
                    midi = 12 * (int(pt.findtext('octave')) + 1) + STEPS[pt.findtext('step')] + int(float(pt.findtext('alter') or 0))
                    tie_stop = any(t.get('type') == 'stop' for t in el.findall('tie'))
                    lyr = el.find('lyric')
                    if tie_stop and notes and notes[-1]['pitch'] == midi and lyr is None:
                        notes[-1]['dur'] += int(dur)
                    else:
                        word = lyr.findtext('text') if lyr is not None else ('_' if notes else 'la')
                        syl = lyr.findtext('syllabic') if lyr is not None else None
                        if syl in ('begin', 'middle'): word += '-'
                        notes.append(_note(tick, dur, midi, word))
                tick += dur
        tr = new_project()['tracks'][0]; tr.update(id=nid(), name=part.get('id', 'Part'), notes=notes)
        p['tracks'].append(tr)
        if tempo: p['tempo'] = [{'tick': 0, 'bpm': tempo}]
    if not p['tracks']: p['tracks'] = new_project()['tracks']
    return p


def bar_segments(project):
    """[(first bar index, start tick, num, den)]: the song's meters (time_sig from bar 0, then project['meters'] =
    [{bar, num, den}] with 0-based bar indexes)."""
    ppq = project.get('ppq', PPQ); ts = project.get('time_sig', [4, 4])
    segs = [(0, 0, ts[0], ts[1])]
    for m in sorted(project.get('meters') or [], key=lambda m: m['bar']):
        b0, t0, n0, d0 = segs[-1]
        if m['bar'] <= b0: continue
        segs.append((m['bar'], t0 + (m['bar'] - b0) * ppq * 4 * n0 // d0, m['num'], m['den']))
    return segs


def bar_len(project, bar_index):
    ppq = project.get('ppq', PPQ)
    b0, t0, n, d = [s for s in bar_segments(project) if s[0] <= bar_index][-1]
    return ppq * 4 * n // d, (n, d)


def to_musicxml(project) -> bytes:
    """One part per track; durations in divisions of 480 per quarter; rests filled in; lyrics with syllabic."""
    names = ['C', 'C', 'D', 'D', 'E', 'F', 'F', 'G', 'G', 'A', 'A', 'B']; alters = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0]
    ts = project.get('time_sig', [4, 4]); bar = int(PPQ * 4 * ts[0] / ts[1])
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<score-partwise version="3.1"><part-list>']
    out += [f'<score-part id="P{i + 1}"><part-name>{t["name"]}</part-name></score-part>' for i, t in enumerate(project['tracks'])]
    out.append('</part-list>')
    for i, t in enumerate(project['tracks']):
        out.append(f'<part id="P{i + 1}">')
        events, cur = [], 0
        for n in sorted(t['notes'], key=lambda n: n['tick']):
            if n['tick'] > cur: events.append((cur, n['tick'] - cur, None))
            events.append((n['tick'], n['dur'], n)); cur = n['tick'] + n['dur']
        m, pos = 1, 0
        bar, meter = bar_len(project, 0)
        out.append(f'<measure number="1"><attributes><divisions>{PPQ}</divisions><time><beats>{ts[0]}</beats><beat-type>{ts[1]}</beat-type></time></attributes>')
        if i == 0: out.append(f'<direction><sound tempo="{project["tempo"][0]["bpm"]}"/></direction>')
        prev_join = False
        for start, dur, n in events:
            dur_full = dur
            while dur > 0:
                room = bar - pos; d = min(dur, room)
                if n is None: out.append(f'<note><rest/><duration>{d}</duration></note>')
                else:
                    pc = n['pitch'] % 12
                    ly = n['lyric']; join = ly.endswith('-'); text = ly.rstrip('-')
                    syl = ('middle' if prev_join else 'begin') if join else ('end' if prev_join else 'single')
                    first = dur_full != -1
                    lyric = '' if ly in ('_', '+') or not first else f'<lyric><syllabic>{syl}</syllabic><text>{text}</text></lyric>'
                    tie = ('' if first else '<tie type="stop"/>') + ('<tie type="start"/>' if d < dur else '')
                    out.append(f'<note><pitch><step>{names[pc]}</step>{"<alter>1</alter>" if alters[pc] else ""}<octave>{n["pitch"] // 12 - 1}</octave></pitch><duration>{d}</duration>{tie}{lyric}</note>')
                    if first: prev_join = join if ly not in ('_', '+') else prev_join
                dur -= d; pos += d; dur_full = -1      # a note cut at a barline carries its lyric on the first piece
                if pos >= bar:
                    m += 1; pos = 0; out.append(f'</measure><measure number="{m}">')
                    bar, new = bar_len(project, m - 1)
                    if new != meter: out.append(f'<attributes><time><beats>{new[0]}</beats><beat-type>{new[1]}</beat-type></time></attributes>'); meter = new
        out.append('</measure></part>')
    out.append('</score-partwise>')
    return '\n'.join(out).encode()


def load(data: bytes, filename: str):
    ext = filename.lower().rsplit('.', 1)[-1]
    title = re.sub(r'\.[^.]+$', '', filename.rsplit('/', 1)[-1])
    if ext in ('mid', 'midi'): return from_midi(data, title)
    text = data.decode('utf-8', 'replace') if ext != 'ust' else data.decode('shift_jis', 'replace') if b'\x82' in data[:2000] else data.decode('utf-8', 'replace')
    if ext == 'ust': return from_ust(text, title)
    if ext == 'svp': return from_svp(text, title)
    if ext == 'vsqx': return from_vsqx(text, title)
    if ext in ('musicxml', 'xml'): return from_musicxml(text, title)
    if ext == 'msing': return json.loads(text)
    raise ValueError(f'unknown file type .{ext}')
