import io
import time
from pathlib import Path

from caretrace.app import create_app
from caretrace.db import connect


class ControlledAnalyzer:
    """Lifecycle test double. Real model acceptance is scripts/e2e.py."""
    def analyze(self, source, target, daily, progress):
        if Path(source).read_bytes() == b'bad':
            raise ValueError('Corrupt test input')
        progress(50, 'test')
        Path(target).write_bytes(b'test video placeholder')
        return {'duration': 2, 'events': [{'track_id': 1,'kind':'standing','start':0,'end':1,'score':.9,'signals':{}}], 'details': {'tracks':[{'id':1,'samples':2}]}}


def test_worker_recovers_after_failed_job_and_serves_ranges(tmp_path):
    app = create_app(tmp_path, analyzer=ControlledAnalyzer())
    c = app.test_client()
    rid = c.post('/api/residents',json={'name':'test'}).json['id']
    ids = []
    for contents in [b'bad',b'good']:
        response = c.post('/api/videos',data={'resident_id':rid,'recorded_at':'2026-09-28T10:00:00+08:00','video':(io.BytesIO(contents),'clip.mp4')})
        ids.append(response.json['id'])
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        if all(c.get('/api/videos/'+vid).json['status'] in ('done','error') for vid in ids): break
        time.sleep(.02)
    assert c.get('/api/videos/'+ids[0]).json['status'] == 'error'
    result = c.get('/api/videos/'+ids[1]).json
    assert result['status'] == 'done'
    assert result['details']['assigned_tracks'] == [1]
    assert len(result['events']) == 1
    response = c.get(f'/media/{ids[1]}/skeleton',headers={'Range':'bytes=0-3'})
    assert response.status_code == 206 and response.data == b'test'
    assert response.headers['Cache-Control'] == 'no-store'
