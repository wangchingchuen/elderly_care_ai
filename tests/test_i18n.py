"""Locale changes must not change evidence, validation, exports or query semantics."""
import csv
import io
import re

import pytest

from caretrace.app import create_app
from caretrace.db import connect
from caretrace.i18n import system_message
from caretrace.query import Planner, answer, date_range


@pytest.fixture
def localized(tmp_path, monkeypatch):
    monkeypatch.setenv('CARETRACE_DISABLE_LLM', '1')
    app = create_app(tmp_path, start_worker=False)
    client = app.test_client()
    rid = client.post('/api/residents', json={'name': '住民 A'}).json['id']
    vid = client.post('/api/videos', data={
        'resident_id': rid, 'recorded_at': '2026-09-28T10:00:00+08:00',
        'video': (io.BytesIO(b'test-double'), 'sample.mp4')}).json['id']
    with connect(app.config['DATABASE']) as db:
        db.execute("UPDATE videos SET status='done',selected_track=1,details=? WHERE id=?",
                   ('{"assigned_tracks":[1]}', vid))
        for eid, kind, review, day in [('fall', 'fall', 'confirmed', 0), ('meal', 'eating', 'pending', 3),
                                        ('excluded', 'fall', 'rejected', 6)]:
            db.execute('INSERT INTO events(id,video_id,track_id,kind,start,end,score,signals,review,note) VALUES (?,?,1,?,?,?,?,?,?,?)',
                       (eid, vid, kind, day, day+1, .8, '{}', review, '=原始備註'))
    return client, rid


@pytest.mark.parametrize('zh,en,kind', [
    ('有疑似跌倒嗎？', 'Are there any possible falls?', 'fall'),
    ('有進食紀錄嗎？', 'Are there any eating records?', 'eating'),
    ('整理照護紀錄', 'Summarize the care records', 'all'),
    ('吃了多少？', 'How much food was eaten?', 'unsupported'),
])
def test_query_language_preserves_evidence(localized, zh, en, kind):
    client, rid = localized
    def ask(q, locale):
        return client.post('/api/query', json={'resident_id': rid, 'question': q},
                           headers={'Accept-Language': locale}).json
    a, b = ask(zh, 'zh-TW'), ask(en, 'en')
    assert a['plan']['kind'] == b['plan']['kind'] == kind
    assert a['evidence'] == b['evidence']
    assert a['answers'] == b['answers']
    assert a['answer'] == b['answers']['zh-TW']
    assert b['answer'] == a['answers']['en']
    assert not re.search(r'[\u3400-\u9fff]', b['answer'] + b['warning'])
    assert all(e['id'] != 'excluded' for e in b['evidence'])
    assert b['warning_source'] == a['warning']


def test_csv_translates_labels_but_preserves_data_and_formula_guard(localized):
    client, rid = localized
    zh = list(csv.reader(io.StringIO(client.get(f'/api/export?resident_id={rid}&lang=zh-TW').data.decode('utf-8-sig'))))
    response = client.get(f'/api/export?resident_id={rid}&lang=en')
    en = list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
    assert response.headers['Content-Language'] == 'en'
    assert en[0] == ['Event ID', 'Resident', 'Event time (UTC+8)', 'Video', 'Behavior',
                     'Start (seconds)', 'End (seconds)', 'Model score', 'Review', 'Notes', 'Evidence']
    assert en[1][4] == 'Possible fall'
    assert en[1][8] == 'Confirmed'
    for a,b in zip(zh[1:], en[1:]):
        for index in [0,1,2,3,5,6,7,9,10]:
            assert a[index] == b[index]
        assert b[1] == '住民 A' and b[9] == "'=原始備註"
    assert client.get(f'/api/export?resident_id={rid}&format=json&lang=en').json['events'] == client.get(f'/api/export?resident_id={rid}&format=json').json['events']


def test_errors_and_fallback_warning(localized):
    client, _ = localized
    for locale, expected in [('en', 'Video not found'), ('zh-TW', '找不到影片')]:
        response = client.get('/api/videos/missing', headers={'Accept-Language': locale})
        assert response.status_code == 404
        assert response.json['error'] == expected
        assert response.json['error_source'] == '找不到影片'
    assert client.get('/api/videos/missing?lang=other').json['error'] == '找不到影片'
    assert 'RuntimeError' in system_message('語言模型不可用或輸出未通過驗證（RuntimeError），改用關鍵字備援', 'en')


def test_comparison_and_follow_up_parity(tmp_path, monkeypatch):
    monkeypatch.setenv('CARETRACE_DISABLE_LLM', '1')
    planner = Planner(tmp_path)
    assert planner.plan('那上週呢？', previous='eating')[0]['kind'] == planner.plan('What about last week?', previous='eating')[0]['kind'] == 'eating'
    assert date_range('比較這週與上週') == date_range('Compare this week and last week')
    events = [{'kind':'eating','review':'confirmed','recorded_at':'2026-09-21T10:00:00+08:00','start':0}]
    args = ('', events, {'kind':'eating','operation':'compare'}, '2026-09-28', '2026-09-28', ['2026-09-21','2026-09-27'])
    zh, en = answer(*args), answer(*args, locale='en')
    assert zh[1:] == en[1:]
    assert '0 clips in this period and 1 in the comparison period' in en[0]
    assert 'does not establish how much was eaten' in en[0]
