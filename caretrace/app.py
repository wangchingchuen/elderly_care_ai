import csv
import hashlib
import io
import json
import os
import queue
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from . import __version__
from .i18n import translate, system_message
from .db import connect, initialize, now, unpack
from .perception import Analyzer, KINDS
from .query import Planner, TZ, answer, date_range, event_time, within_dates

ROOT = Path(__file__).resolve().parents[1]


def create_app(data_dir=None, analyzer=None, planner=None, start_worker=True):
    app = Flask(__name__, static_folder=None)
    data = Path(data_dir or os.getenv('CARETRACE_DATA_DIR', ROOT/'data')).resolve()
    data.mkdir(parents=True, exist_ok=True)
    media = data/'media'
    media.mkdir(exist_ok=True)
    database = data/'caretrace.sqlite3'
    initialize(database)
    engine = analyzer or Analyzer(ROOT)
    language = planner or Planner(ROOT)
    tasks = queue.Queue()
    app.config.update(MAX_CONTENT_LENGTH=512*1024*1024, DATABASE=str(database), DATA_DIR=str(data))
    app.extensions.update(analyzer=engine, planner=language, tasks=tasks)

    def locale():
        requested = request.args.get('lang')
        if requested:
            return 'en' if requested == 'en' else 'zh-TW'
        return request.accept_languages.best_match(['zh-TW', 'en'], default='zh-TW')

    def fetch_video(video_id):
        with connect(database) as db:
            row = db.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone()
        if row is None:
            abort(404, '找不到影片')
        return unpack(row)

    def public_video(video):
        return {k: v for k, v in video.items() if k not in ('source_path', 'evidence_path')}

    def events_for(resident=None):
        sql = '''SELECT e.*, v.filename, v.recorded_at, v.resident_id, v.selected_track, v.details AS video_details, r.name AS resident_name
                 FROM events e JOIN videos v ON v.id=e.video_id JOIN residents r ON r.id=v.resident_id
                 WHERE v.status='done' '''
        with connect(database) as db:
            rows = db.execute(sql + (' AND v.resident_id=?' if resident else '') + ' ORDER BY v.recorded_at,e.start', (resident,) if resident else ()).fetchall()
        result = []
        for row in rows:
            item = unpack(row)
            assigned = json.loads(item.pop('video_details')).get('assigned_tracks', [item['selected_track']])
            if item['track_id'] in assigned:
                result.append(item)
        return result

    def worker():
        while True:
            video_id = tasks.get()
            try:
                video = fetch_video(video_id)
                with connect(database) as db:
                    db.execute("UPDATE videos SET status='processing',error=NULL WHERE id=?", (video_id,))

                def progress(percent, stage):
                    with connect(database) as db:
                        db.execute('UPDATE videos SET progress=?,stage=? WHERE id=?', (percent, stage, video_id))

                output = media/video_id/'skeleton.mp4'
                result = engine.analyze(video['source_path'], output, bool(video['daily_enabled']), progress)
                tracks = result['details']['tracks']
                # A single track is unambiguous within a user-assigned resident's clip.
                selected = tracks[0]['id'] if len(tracks) == 1 else None
                result['details']['assigned_tracks'] = [selected] if selected is not None else []
                with connect(database) as db:
                    db.execute('DELETE FROM events WHERE video_id=?', (video_id,))
                    for e in result['events']:
                        db.execute('INSERT INTO events(id,video_id,track_id,kind,start,end,score,signals) VALUES (?,?,?,?,?,?,?,?)',
                                   (uuid.uuid4().hex, video_id, e['track_id'], e['kind'], e['start'], e['end'], e['score'], json.dumps(e['signals'], ensure_ascii=False)))
                    db.execute("UPDATE videos SET status='done',progress=100,stage='分析完成',duration=?,evidence_path=?,details=?,selected_track=? WHERE id=?",
                               (result['duration'], str(output), json.dumps(result['details'], ensure_ascii=False), selected, video_id))
            except Exception as exc:
                app.logger.exception('Video analysis failed: %s', video_id)
                with connect(database) as db:
                    db.execute("UPDATE videos SET status='error',stage='分析失敗',error=? WHERE id=?", (f'{type(exc).__name__}: {str(exc)[:500]}', video_id))
            finally:
                tasks.task_done()

    if start_worker:
        threading.Thread(target=worker, daemon=True, name='caretrace-inference').start()

    @app.before_request
    def local_only():
        if request.host.split(':')[0] not in ('localhost', '127.0.0.1', '[', '::1'):
            abort(403, '僅允許本機存取')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('Origin')
            if request.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlparse(origin).netloc != request.host):
                abort(403, '禁止跨來源操作')

    @app.after_request
    def headers(response):
        response.headers['Content-Language'] = locale()
        response.vary.add('Accept-Language')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
        if request.path.startswith(('/api/', '/media/')):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=system_message(exc.description, locale()), error_source=exc.description), exc.code

    @app.errorhandler(ValueError)
    def validation_error(exc):
        return jsonify(error=system_message(str(exc), locale()), error_source=str(exc)), 400

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            abort(400, '需要 JSON 物件')
        return value

    def require_resident(resident_id):
        with connect(database) as db:
            resident = db.execute('SELECT * FROM residents WHERE id=?', (resident_id,)).fetchone()
        if not resident:
            abort(404, '請先選擇有效住民')
        return dict(resident)

    @app.get('/api/health')
    def health():
        return jsonify(version=__version__, mode='local', llm_loaded=language.model is not None,
                       llm_error=language.error, queue_size=tasks.qsize(), kinds=KINDS)

    @app.route('/api/residents', methods=['GET', 'POST'])
    def residents():
        with connect(database) as db:
            if request.method == 'GET':
                return jsonify([dict(r) for r in db.execute('SELECT * FROM residents ORDER BY created_at')])
            value = body()
            name = str(value.get('name', '')).strip()
            if not name or len(name) > 80:
                abort(400, '請輸入 1–80 字的住民代號或名稱')
            resident = dict(id=uuid.uuid4().hex, name=name, bed=str(value.get('bed', ''))[:40], context=str(value.get('context', ''))[:2000], created_at=now())
            db.execute('INSERT INTO residents VALUES (:id,:name,:bed,:context,:created_at)', resident)
        return jsonify(resident), 201

    @app.delete('/api/residents/<resident_id>')
    def delete_resident(resident_id):
        require_resident(resident_id)
        with connect(database) as db:
            if db.execute('SELECT 1 FROM videos WHERE resident_id=?', (resident_id,)).fetchone():
                abort(409, '請先刪除此住民的影片')
            db.execute('DELETE FROM queries WHERE resident_id=?', (resident_id,))
            db.execute('DELETE FROM residents WHERE id=?', (resident_id,))
        return '', 204

    @app.route('/api/videos', methods=['GET', 'POST'])
    def videos():
        if request.method == 'GET':
            resident = request.args.get('resident_id')
            with connect(database) as db:
                rows = db.execute('SELECT * FROM videos' + (' WHERE resident_id=?' if resident else '') + ' ORDER BY created_at DESC', (resident,) if resident else ()).fetchall()
            return jsonify([public_video(unpack(r)) for r in rows])
        resident = require_resident(request.form.get('resident_id', ''))
        recorded = request.form.get('recorded_at', '')
        try:
            dt = datetime.fromisoformat(recorded.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                raise ValueError()
        except ValueError:
            abort(400, '請提供含時區的拍攝時間')
        upload = request.files.get('video')
        if not upload or not upload.filename:
            abort(400, '請選擇影片')
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ('.mp4', '.mov', '.webm', '.avi'):
            abort(400, '支援 MP4、MOV、WebM 與 AVI')
        video_id = uuid.uuid4().hex
        folder = media/video_id
        folder.mkdir()
        source = folder/('source'+suffix)
        try:
            upload.save(source)
            if source.stat().st_size == 0:
                abort(400, '影片是空檔案')
            digest = hashlib.sha256()
            with source.open('rb') as f:
                for chunk in iter(lambda: f.read(1024*1024), b''):
                    digest.update(chunk)
            with connect(database) as db:
                db.execute('''INSERT INTO videos(id,resident_id,filename,recorded_at,created_at,status,stage,source_path,sha256,daily_enabled)
                              VALUES (?,?,?,?,?,'queued','等待分析',?,?,?)''',
                           (video_id, resident['id'], Path(upload.filename.replace('\\', '/')).name[:200], dt.isoformat(), now(), str(source), digest.hexdigest(), int(request.form.get('daily_enabled', 'true') == 'true')))
        except Exception:
            shutil.rmtree(folder)
            raise
        tasks.put(video_id)
        return jsonify(public_video(fetch_video(video_id))), 202

    @app.get('/api/videos/<video_id>')
    def video_detail(video_id):
        video = public_video(fetch_video(video_id))
        with connect(database) as db:
            video['events'] = [unpack(r) for r in db.execute('SELECT * FROM events WHERE video_id=? ORDER BY start', (video_id,))]
        return jsonify(video)

    @app.post('/api/videos/<video_id>/assign')
    def assign(video_id):
        video = fetch_video(video_id)
        value = body()
        tracks = value.get('track_ids', [value.get('track_id')])
        valid = [t['id'] for t in video['details'].get('tracks', [])]
        if not isinstance(tracks, list) or any(type(t) is not int or t not in valid for t in tracks):
            abort(400, '請選擇影片中實際存在的追蹤代號')
        tracks = list(dict.fromkeys(tracks))
        video['details']['assigned_tracks'] = tracks
        with connect(database) as db:
            db.execute('UPDATE videos SET selected_track=?,details=? WHERE id=?', (tracks[0] if tracks else None, json.dumps(video['details'], ensure_ascii=False), video_id))
            db.execute('DELETE FROM queries WHERE resident_id=?', (video['resident_id'],))
        return jsonify(public_video(fetch_video(video_id)))

    @app.post('/api/videos/<video_id>/retry')
    def retry(video_id):
        with connect(database) as db:
            cursor = db.execute("UPDATE videos SET status='queued',progress=0,error=NULL,stage='等待重新分析' WHERE id=? AND status IN ('error','interrupted')", (video_id,))
            if not cursor.rowcount:
                abort(409, '只有失敗或中斷的分析可以重試')
        tasks.put(video_id)
        return jsonify(public_video(fetch_video(video_id))), 202

    @app.delete('/api/videos/<video_id>')
    def delete_video(video_id):
        video = fetch_video(video_id)
        if video['status'] in ('queued', 'processing'):
            abort(409, '分析進行中，請完成後再刪除')
        # The directory is derived solely from a DB-validated UUID, never an upload name.
        folder = (media/video_id).resolve()
        if folder.parent != media.resolve():
            abort(400)
        if folder.exists():
            shutil.rmtree(folder)
        with connect(database) as db:
            db.execute('DELETE FROM queries WHERE resident_id=?', (video['resident_id'],))
            db.execute('DELETE FROM videos WHERE id=?', (video_id,))
        return '', 204

    @app.get('/media/<video_id>/<kind>')
    def evidence(video_id, kind):
        video = fetch_video(video_id)
        if kind not in ('skeleton', 'original'):
            abort(404)
        path = video['evidence_path'] if kind == 'skeleton' else video['source_path']
        if not path or not Path(path).is_file():
            abort(404, '證據影片尚未就緒')
        return send_file(path, conditional=True)

    @app.route('/api/events/<event_id>/reviews', methods=['GET', 'POST'])
    def reviews(event_id):
        with connect(database) as db:
            row = db.execute('SELECT e.*,v.resident_id FROM events e JOIN videos v ON v.id=e.video_id WHERE e.id=?', (event_id,)).fetchone()
            if not row:
                abort(404, '找不到事件')
            if request.method == 'GET':
                return jsonify([dict(r) for r in db.execute('SELECT * FROM reviews WHERE event_id=? ORDER BY id', (event_id,))])
            value = body()
            status, note = value.get('status'), str(value.get('note', '')).strip()
            if status not in ('pending', 'confirmed', 'rejected') or len(note) > 2000:
                abort(400, '覆核狀態或備註無效')
            db.execute('UPDATE events SET review=?,note=? WHERE id=?', (status, note, event_id))
            db.execute('INSERT INTO reviews(event_id,status,note,created_at) VALUES (?,?,?,?)', (event_id, status, note, now()))
            db.execute('DELETE FROM queries WHERE resident_id=?', (row['resident_id'],))
        return jsonify(status=status, note=note)

    @app.get('/api/log')
    def log():
        resident = request.args.get('resident_id')
        start, end, _ = date_range('', request.args.get('start') or None, request.args.get('end') or None)
        events = [e for e in events_for(resident) if within_dates(e, start, end)]
        return jsonify(events)

    @app.post('/api/query')
    def query():
        value = body()
        resident = require_resident(value.get('resident_id', ''))
        question = str(value.get('question', '')).strip()
        if not question or len(question) > 1000:
            abort(400, '請輸入 1–1000 字的問題')
        start, end, compare = date_range(question, value.get('start') or None, value.get('end') or None)
        plan, mode, warning = language.plan(question, resident['context'], value.get('previous_kind'))
        events = events_for(resident['id'])
        text, hits, previous = answer(question, events, plan, start, end, compare)
        answers = {'zh-TW': text, 'en': answer(question, events, plan, start, end, compare, locale='en')[0]}
        result = dict(id=uuid.uuid4().hex, answer=answers[locale()], answers=answers, plan=plan, mode=mode,
                      warning=system_message(warning, locale()), warning_source=warning,
                      scope={'resident_id': resident['id'], 'start': start, 'end': end, 'compare': compare},
                      evidence=hits, comparison_evidence=previous, created_at=now())
        with connect(database) as db:
            db.execute('INSERT INTO queries VALUES (?,?,?,?,?)', (result['id'], resident['id'], question, json.dumps(result, ensure_ascii=False), result['created_at']))
        return jsonify(result)

    @app.get('/api/export')
    def export():
        resident = request.args.get('resident_id')
        start, end, _ = date_range('', request.args.get('start') or None, request.args.get('end') or None)
        rows = [e for e in events_for(resident) if within_dates(e, start, end)]
        if request.args.get('format') == 'json':
            return jsonify(version=__version__, exported_at=now(), events=rows)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([translate(key, locale()) for key in ['事件編號', '住民', '拍攝時間', '影片', '行為', '開始秒', '結束秒', '模型分數', '覆核', '備註', '證據']])
        def safe(value):
            value = str(value)
            return "'"+value if value.lstrip().startswith(('=', '+', '-', '@')) else value
        for e in rows:
            review_label = {'pending': '待覆核', 'confirmed': '已確認', 'rejected': '已排除'}[e['review']]
            writer.writerow([safe(x) for x in [e['id'], e['resident_name'], event_time(e).astimezone(TZ).isoformat(), e['filename'], translate(KINDS[e['kind']], locale()), e['start'], e['end'], e['score'], translate(review_label, locale()), e['note'], f"/media/{e['video_id']}/skeleton#t={e['start']}"]])
        return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name='caretrace-records.csv')

    @app.get('/')
    @app.get('/<path:path>')
    def frontend(path='index.html'):
        if path.startswith(('api/', 'media/')):
            abort(404)
        dist = ROOT/'frontend/dist'
        if not (dist/'index.html').exists():
            return '前端尚未建置。請執行 scripts/setup.ps1，再執行 scripts/start.ps1。', 503
        return send_from_directory(dist, path if (dist/path).is_file() else 'index.html')

    return app


if __name__ == '__main__':
    from waitress import serve
    serve(create_app(), host='127.0.0.1', port=int(os.getenv('CARETRACE_PORT', '5000')), threads=8)
