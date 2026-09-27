import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(path):
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript('''
        CREATE TABLE IF NOT EXISTS residents (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, bed TEXT NOT NULL DEFAULT '',
            context TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY, resident_id TEXT NOT NULL REFERENCES residents(id),
            filename TEXT NOT NULL, recorded_at TEXT NOT NULL, created_at TEXT NOT NULL,
            status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            stage TEXT NOT NULL DEFAULT '', error TEXT, duration REAL NOT NULL DEFAULT 0,
            source_path TEXT NOT NULL, evidence_path TEXT, sha256 TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}', selected_track INTEGER,
            daily_enabled INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, video_id TEXT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
            track_id INTEGER NOT NULL, kind TEXT NOT NULL, start REAL NOT NULL,
            end REAL NOT NULL, score REAL NOT NULL, signals TEXT NOT NULL,
            review TEXT NOT NULL DEFAULT 'pending', note TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS events_video ON events(video_id);
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
            status TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS queries (
            id TEXT PRIMARY KEY, resident_id TEXT REFERENCES residents(id),
            question TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL
        );
        PRAGMA user_version=1;
        ''')
        db.execute("UPDATE videos SET status='interrupted', stage='上次分析中斷，請重試', error='服務於分析完成前關閉' WHERE status IN ('queued','processing')")


def unpack(row):
    if row is None:
        return None
    result = dict(row)
    for key in ('details', 'signals'):
        if key in result:
            result[key] = json.loads(result[key])
    return result
