"""Real local inference, never a synthetic substitute for model validation."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from caretrace.perception import Analyzer
from caretrace.query import Planner

out = ROOT/'artifacts/model-validation'
out.mkdir(parents=True, exist_ok=True)
engine = Analyzer(ROOT)
report = {'videos': [], 'queries': []}
if not list((ROOT/'test_videos').glob('*.mp4')):
    raise SystemExit('No local MP4 test videos found; model validation was not run.')
for path in sorted((ROOT/'test_videos').glob('*.mp4')):
    try:
        last = [0]
        def progress(n, text):
            if n-last[0] >= 10 or n < 5:
                print(path.name, round(n), text, flush=True)
                last[0] = n
        result = engine.analyze(path, out/(path.stem+'-skeleton.mp4'), True, progress)
        report['videos'].append({'name': path.name, **result})
    except Exception as exc:
        import traceback
        traceback.print_exc()
        report['videos'].append({'name': path.name, 'error': repr(exc)})
        print(repr(exc), flush=True)
    (out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
planner = Planner(ROOT)
for question, expected in [('有進食紀錄嗎？','eating'), ('有疑似跌倒嗎？','fall'), ('整理照護紀錄','all'), ('When was the person sitting?', 'sitting'), ('他吃了多少？', 'unsupported')]:
    t = time.monotonic()
    plan, mode, warning = planner.plan(question)
    report['queries'].append({'question': question, 'expected': expected, 'plan': plan, 'mode': mode, 'warning': warning, 'seconds': round(time.monotonic()-t,2)})
    print(report['queries'][-1], flush=True)
(out/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
if any('error' in v for v in report['videos']) or any(q['plan']['kind'] != q['expected'] or q['mode'] != 'local_llm' for q in report['queries']):
    raise SystemExit(1)
