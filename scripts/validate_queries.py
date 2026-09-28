"""Run bilingual query plans against the actual local model (no video or user data)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from caretrace.query import Planner

cases = [
    ('有疑似跌倒嗎？', 'fall', None),
    ('Are there any possible falls?', 'fall', None),
    ('有進食紀錄嗎？', 'eating', None),
    ('Are there any eating records?', 'eating', None),
    ('整理照護紀錄', 'all', None),
    ('Summarize the care records', 'all', None),
    ('這週和上週的進食紀錄有什麼不同？', 'eating', None),
    ('Compare eating records this week and last week.', 'eating', None),
    ('那上週呢？', 'eating', 'eating'),
    ('What about last week?', 'eating', 'eating'),
    ('吃了多少？', 'unsupported', None),
    ('How much food was eaten?', 'unsupported', None),
]
planner = Planner(ROOT)
results = []
for question, expected, previous in cases:
    plan, mode, warning = planner.plan(question, previous=previous)
    results.append(dict(question=question, plan=plan, mode=mode, warning=warning,
                        passed=plan['kind'] == expected and mode == 'local_llm'))
    print(json.dumps(results[-1], ensure_ascii=False), flush=True)
output = ROOT/'artifacts/bilingual-query-plans.json'
output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
raise SystemExit(0 if all(row['passed'] for row in results) else 1)
