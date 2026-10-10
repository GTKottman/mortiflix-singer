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
