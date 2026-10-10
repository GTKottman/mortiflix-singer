import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from engine import formats
from engine.project import new_project


def sample():
    p = new_project('t', 100)
    p['tracks'][0]['notes'] = [{'id': 'a', 'tick': 0, 'dur': 480, 'pitch': 62, 'lyric': 'keep', 'vel': 64},
                               {'id': 'b', 'tick': 480, 'dur': 240, 'pitch': 64, 'lyric': 'sun-', 'vel': 64},
                               {'id': 'c', 'tick': 720, 'dur': 240, 'pitch': 62, 'lyric': 'rise', 'vel': 64},
                               {'id': 'd', 'tick': 1920, 'dur': 960, 'pitch': 60, 'lyric': 'now', 'vel': 90}]
    return p


def strip(p): return [(n['tick'], n['dur'], n['pitch'], n['lyric']) for n in p['tracks'][0]['notes']]


def test_midi_round_trip_keeps_words_and_tempo():
    q = formats.from_midi(formats.to_midi(sample()))
    assert strip(q) == strip(sample())
    assert abs(q['tempo'][0]['bpm'] - 100) < 0.01


def test_musicxml_round_trip():
    q = formats.from_musicxml(formats.to_musicxml(sample()).decode())
    assert strip(q) == strip(sample())


def test_note_across_a_barline():
    p = new_project(); p['tracks'][0]['notes'] = [{'id': 'a', 'tick': 1440, 'dur': 960, 'pitch': 60, 'lyric': 'hold', 'vel': 64}]
    q = formats.from_musicxml(formats.to_musicxml(p).decode())
    assert strip(q) == [(1440, 960, 60, 'hold')]          # the tie at the barline joins it back


def test_ust():
    ust = "[#SETTING]\nTempo=90\n[#0000]\nLength=480\nLyric=la\nNoteNum=60\n[#0001]\nLength=480\nLyric=R\nNoteNum=60\n[#0002]\nLength=960\nLyric=lu\nNoteNum=62\n[#TRACKEND]\n"
    q = formats.from_ust(ust)
    assert strip(q) == [(0, 480, 60, 'la'), (960, 960, 62, 'lu')] and q['tempo'][0]['bpm'] == 90


def test_svp():
    B = 705600000
    svp = '{"time":{"tempo":[{"position":0,"bpm":128}],"meter":[{"index":0,"numerator":4,"denominator":4}]},"library":[],"tracks":[{"name":"Lead","mainGroup":{"notes":[{"onset":0,"duration":%d,"pitch":67,"lyrics":"go"},{"onset":%d,"duration":%d,"pitch":69,"lyrics":"-"}]},"groups":[]}]}' % (B, B, B // 2)
    q = formats.from_svp(svp)
    assert strip(q) == [(0, 480, 67, 'go'), (480, 240, 69, '_')] and q['tempo'][0]['bpm'] == 128


def test_vsqx():
    x = '<vsq4 xmlns="http://www.yamaha.co.jp/vocaloid/schema/vsq4/"><masterTrack><resolution>480</resolution><tempo><t>0</t><v>14000</v></tempo></masterTrack><vsTrack><name>V</name><vsPart><t>1920</t><note><t>0</t><dur>480</dur><n>64</n><y>hi</y></note></vsPart></vsTrack></vsq4>'
    q = formats.from_vsqx(x.replace('vsPart', 'musicalPart'))
    assert strip(q) == [(1920, 480, 64, 'hi')] and q['tempo'][0]['bpm'] == 140


def test_meter_changes_survive_midi_and_musicxml():
    from engine.formats import to_midi, from_midi, to_musicxml, bar_segments
    p = {'version': 1, 'ppq': 480, 'title': 'm', 'tempo': [{'tick': 0, 'bpm': 120}], 'time_sig': [4, 4],
         'meters': [{'bar': 2, 'num': 3, 'den': 4}, {'bar': 4, 'num': 6, 'den': 8}],
         'tracks': [{'id': 't1', 'name': 'Lead', 'notes': [{'id': 'a', 'tick': 0, 'dur': 480 * 14, 'pitch': 60, 'lyric': 'ah'}]}]}
    assert bar_segments(p) == [(0, 0, 4, 4), (2, 3840, 3, 4), (4, 6720, 6, 8)]
    back = from_midi(to_midi(p))
    assert back['time_sig'] == [4, 4] and back['meters'] == p['meters']
    xml = to_musicxml(p).decode()
    assert '<beats>3</beats><beat-type>4</beat-type>' in xml and '<beats>6</beats><beat-type>8</beat-type>' in xml
    assert xml.index('<beats>3</beats>') > xml.index('<measure number="3">')     # 3/4 starts at bar 3 (index 2)


def test_vocaloid_vpr():
    import io, json, zipfile
    from engine.formats import load
    seq = {'masterTrack': {'tempo': {'events': [{'pos': 0, 'value': 12500}]}, 'timeSig': {'events': [{'bar': 0, 'numer': 3, 'denom': 4}]}},
           'tracks': [{'type': 0, 'name': 'Vox', 'parts': [{'pos': 1920, 'notes': [
               {'lyric': 'ride', 'pos': 0, 'duration': 240, 'number': 62, 'velocity': 80},
               {'lyric': 'on', 'pos': 240, 'duration': 480, 'number': 64, 'velocity': 64}]}]},
                      {'type': 1, 'name': 'Audio', 'parts': []}]}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z: z.writestr('Project/sequence.json', json.dumps(seq))
    p = load(buf.getvalue(), 'song.vpr')
    assert p['tempo'] == [{'tick': 0, 'bpm': 125.0}] and p['time_sig'] == [3, 4]
    assert [(n['tick'], n['dur'], n['pitch'], n['lyric'], n['vel']) for n in p['tracks'][0]['notes']] == [(1920, 240, 62, 'ride', 80), (2160, 480, 64, 'on', 64)]
    assert len(p['tracks']) == 1 and p['tracks'][0]['name'] == 'Vox'
