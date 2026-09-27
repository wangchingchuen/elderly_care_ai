import io
import json
from datetime import datetime

import numpy as np
import pytest

from caretrace.app import create_app
from caretrace.db import connect, initialize
from caretrace.perception import EventBuilder, Tracker, classify_pose, hand_near_face
from caretrace.query import answer, date_range, validate_plan, within_dates
from caretrace.query import Planner


class FakePlanner:
    model = None
    error = None
    def plan(self, question, context='', previous=None):
        return {'kind': 'fall' if '跌' in question else 'all', 'operation': 'list'}, 'test_double', None


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, planner=FakePlanner(), start_worker=False)


@pytest.fixture
def client(app):
    return app.test_client()


def resident(client, name='住民 A'):
    return client.post('/api/residents', json={'name': name}).json['id']


def upload(client, rid, name='sample.mp4', content=b'video-test-double'):
    return client.post('/api/videos', data={'resident_id': rid, 'recorded_at': '2026-09-27T23:59:58+08:00', 'video': (io.BytesIO(content), name)})


def seed(app, client, rid):
    vid = upload(client, rid).json['id']
    with connect(app.config['DATABASE']) as db:
        db.execute("UPDATE videos SET status='done', selected_track=1, duration=20, details=? WHERE id=?", (json.dumps({'tracks': [{'id': 1}, {'id': 2}]}), vid))
        for eid, track, start in [('first', 1, 1), ('midnight', 1, 5), ('otherperson', 2, 7)]:
            db.execute('INSERT INTO events(id,video_id,track_id,kind,start,end,score,signals) VALUES (?,?,?, ?,?,?,?,?)', (eid, vid, track, 'fall', start, start+1, .8, '{}'))
    return vid


def test_upload_validation_and_paths(client, app):
    rid = resident(client)
    assert client.post('/api/videos').status_code == 404
    assert upload(client, rid, 'x.exe').status_code == 400
    assert upload(client, rid, content=b'').status_code == 400
    response = upload(client, rid, '../../outside.mp4')
    assert response.status_code == 202
    assert response.json['filename'] == 'outside.mp4'
    assert 'source_path' not in response.json
    assert client.post('/api/videos', data={'resident_id': rid, 'recorded_at': '2026-09-28T10:00', 'video': (io.BytesIO(b'a'), 'x.mp4')}).status_code == 400


def test_query_resident_track_and_midnight_isolation(client, app):
    rid = resident(client)
    seed(app, client, rid)
    other = resident(client, '住民 B')
    result = client.post('/api/query', json={'resident_id': rid, 'question': '2026-09-28 有跌倒嗎？'}).json
    assert [e['id'] for e in result['evidence']] == ['midnight']
    assert result['mode'] == 'test_double'
    assert client.post('/api/query', json={'resident_id': other, 'question': '有跌倒嗎？'}).json['evidence'] == []


def test_reviews_audited_and_rejected_evidence_excluded(client, app):
    rid = resident(client)
    seed(app, client, rid)
    for status in ['confirmed', 'rejected']:
        assert client.post('/api/events/first/reviews', json={'status': status, 'note': '人工比對'}).status_code == 200
    assert len(client.get('/api/events/first/reviews').json) == 2
    result = client.post('/api/query', json={'resident_id': rid, 'question': '有跌倒嗎？'}).json
    assert [e['id'] for e in result['evidence']] == ['midnight']
    assert client.post('/api/events/first/reviews', json={'status': 'made-up'}).status_code == 400


def test_assignment_and_deletion_clear_dependent_records(client, app):
    rid = resident(client)
    vid = seed(app, client, rid)
    assert client.post(f'/api/videos/{vid}/assign', json={'track_id': 3}).status_code == 400
    assert client.post(f'/api/videos/{vid}/assign', json={'track_id': 2}).status_code == 200
    assert [e['id'] for e in client.get(f'/api/log?resident_id={rid}').json] == ['otherperson']
    client.post('/api/query', json={'resident_id': rid, 'question': '有跌倒嗎？'})
    assert client.delete(f'/api/residents/{rid}').status_code == 409
    assert client.delete(f'/api/videos/{vid}').status_code == 204
    assert client.get(f'/api/videos/{vid}').status_code == 404
    with connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM queries').fetchone()[0] == 0
    assert client.delete(f'/api/residents/{rid}').status_code == 204


def test_restart_retains_completed_and_marks_unfinished(client, app):
    rid = resident(client)
    vid = seed(app, client, rid)
    active = upload(client, rid).json['id']
    initialize(app.config['DATABASE'])
    assert client.get(f'/api/videos/{vid}').json['status'] == 'done'
    assert client.get(f'/api/videos/{active}').json['status'] == 'interrupted'
    assert client.post(f'/api/videos/{active}/retry').status_code == 202
    assert client.post(f'/api/videos/{active}/retry').status_code == 409
    assert client.delete(f'/api/videos/{active}').status_code == 409


def test_export_formula_escaping_and_dates(client, app):
    rid = resident(client, '=CMD()')
    seed(app, client, rid)
    csv = client.get(f'/api/export?resident_id={rid}&start=2026-09-28&end=2026-09-28').data.decode('utf-8-sig')
    assert "'=CMD()" in csv
    assert 'midnight' in csv and 'first' not in csv
    assert client.get('/api/log?start=2026-10-10&end=2026-01-01').status_code == 400


def test_host_origin_and_media_boundaries(client):
    assert client.get('/api/health', headers={'Host': 'evil.example'}).status_code == 403
    assert client.post('/api/residents', json={'name': 'x'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/residents', json={'name': 'x'}, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
    assert client.get('/media/nope/original').status_code == 404
    assert client.get('/api/nope').status_code == 404


def test_temporal_logic_and_gaps():
    b = EventBuilder(.2)
    for t in [0, .2, .4]: b.add(1, t, 'standing', .9)
    for t in [.6, .8, 1]: b.add(1, t, 'lying', .9)
    events = b.finish(1.2)
    assert len([e for e in events if e['kind'] == 'fall']) == 1
    b = EventBuilder(.2)
    b.add(1, 0, 'standing', .9)
    b.add(1, 5, 'lying', .9)
    assert not any(e['kind'] == 'fall' for e in b.finish(6))


def test_sitting_transition_and_multi_person_are_separate():
    b = EventBuilder(.2)
    for t in [0, .2, .4]:
        b.add(1, t, 'standing', .9)
        b.add(2, t, 'sitting', .9)
    for t in [.6, .8, 1]: b.add(2, t, 'lying', .9)
    assert not any(e['kind'] == 'fall' for e in b.finish(1.2))
    assert any(e['kind'] == 'normal_lying' for e in b.finish(1.2))


def test_eating_requires_repeated_samples():
    b = EventBuilder(.2)
    b.add(1, 0, 'sitting', .9, True, .4)
    b.add(1, .2, 'sitting', .9, False)
    assert not any(e['kind'] == 'eating' for e in b.finish(.4))
    b = EventBuilder(.2)
    for t in [0,.2,.4,.6,.8]:
        b.add(1,t,'sitting',.9,True,.4)
    assert any(e['kind'] == 'eating' for e in b.finish(1))


def test_tracker_does_not_reuse_disappeared_identity():
    tracker = Tracker()
    assert tracker.update([[0,0,100,100], [200,0,300,100]], 0) == [1, 2]
    assert tracker.update([[205,0,305,100], [2,0,102,100]], .2) == [2, 1]
    assert tracker.update([[0,0,100,100]], 4) == [3]


def test_insufficient_keypoints_are_unknown():
    assert classify_pose(np.zeros((17,2)), np.zeros(17)) == 'uncertain'
    assert not hand_near_face(np.zeros((17,2)), np.zeros(17))


def test_straight_legs_are_not_misclassified_by_body_proportions():
    points = np.array([[50,0],[45,0],[55,0],[40,0],[60,0],[40,20],[60,20],[40,50],[60,50],
                       [40,80],[60,80],[40,80],[60,80],[40,115],[60,115],[40,150],[60,150]], dtype=float)
    assert classify_pose(points, np.ones(17)) == 'standing'
    points[[13,14]] = [[70,90],[90,90]]
    points[[15,16]] = [[70,115],[90,115]]
    assert classify_pose(points, np.ones(17)) == 'sitting'


def test_multiple_tracks_may_be_manually_assigned(client, app):
    rid = resident(client)
    vid = seed(app, client, rid)
    assert client.post(f'/api/videos/{vid}/assign', json={'track_ids':[1,2]}).status_code == 200
    assert len(client.get(f'/api/log?resident_id={rid}').json) == 3
    assert client.post(f'/api/videos/{vid}/assign', json={'track_ids':[]}).status_code == 200
    assert client.get(f'/api/log?resident_id={rid}').json == []


def test_dates_and_plan_reject_injection():
    assert date_range('這週和上週進食比較', current=datetime.fromisoformat('2026-09-30T10:00:00+08:00')) == ('2026-09-28', '2026-09-30', ['2026-09-21', '2026-09-27'])
    with pytest.raises(ValueError): validate_plan({'kind':'fall', 'operation':'list', 'sql':'DROP TABLE events'})
    with pytest.raises(ValueError): validate_plan({'kind':'medication', 'operation':'list'})
    text, hits, _ = answer('?', [], {'kind':'fall'}, None, None)
    assert '不代表' in text and hits == []


def test_keyword_fallback_does_not_claim_intake_or_diagnosis(monkeypatch, tmp_path):
    monkeypatch.setenv('CARETRACE_DISABLE_LLM','1')
    planner = Planner(tmp_path)
    for question in ['他吃了多少？','What medication did they take?']:
        plan, mode, warning = planner.plan(question)
        assert plan['kind'] == 'unsupported' and mode == 'rules' and warning
