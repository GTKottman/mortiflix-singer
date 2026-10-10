"""The desktop transport: framed HTTP over the service's stdin/stdout, several requests in flight at once."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_stdio_frames(tmp_path):
    p = subprocess.Popen([sys.executable, str(ROOT / 'server.py'), '--stdio', '--home', str(tmp_path)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=ROOT)
    reqs = {1: b'GET /api/singer/script HTTP/1.1\r\nHost: x\r\n\r\n', 2: b'GET /api/singer/nope HTTP/1.1\r\nHost: x\r\n\r\n'}
    for rid, raw in reqs.items():
        p.stdin.write(json.dumps({'id': rid, 'len': len(raw)}).encode() + b'\n' + raw)
    p.stdin.flush()
    got = {}
    for _ in reqs:
        h = json.loads(p.stdout.readline()); got[h['id']] = p.stdout.read(h['len'])
    p.stdin.close(); p.wait(timeout=10)
    head, body = got[1].split(b'\r\n\r\n', 1)
    assert head.startswith(b'HTTP/1.0 200') and len(json.loads(body)) > 500
    assert got[2].startswith(b'HTTP/1.0 404')
