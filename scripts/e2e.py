"""Browser acceptance against REAL YOLO/OmDet and local LLM. Requires local sample video."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts'/('e2e-'+uuid.uuid4().hex[:8])
OUT.mkdir(parents=True)
env = {**os.environ, 'CARETRACE_DATA_DIR': str(OUT/'data'), 'CARETRACE_PORT': '5057', 'PYTHONUTF8': '1'}
url = 'http://127.0.0.1:5057'
report = {'checks': [], 'errors': []}
log = (OUT/'server.log').open('w', encoding='utf-8')

def start_server():
    proc = subprocess.Popen([sys.executable, '-u', '-m', 'caretrace.app'], cwd=ROOT, env=env, stdout=log, stderr=log)
    for _ in range(100):
        try:
            if urlopen(url+'/api/health', timeout=1).status == 200: return proc
        except Exception:
            if proc.poll() is not None: raise RuntimeError('Server failed; see '+str(OUT/'server.log'))
            time.sleep(.2)
    proc.terminate()
    raise TimeoutError('Server startup timeout')

proc = start_server()
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000}, device_scale_factor=1)
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        page.goto(url)
        expect(page.get_by_role('heading', name='讓每一份照護，都有依據。')).to_be_visible()
        page.screenshot(path=str(OUT/'01-empty.png'), full_page=True)
        page.get_by_role('button', name='建立住民', exact=True).click()
        page.get_by_label('住民代號或名稱').fill('展示住民 A')
        page.get_by_label('床位／房間').fill('A 區 17 床')
        page.get_by_label('照護背景與日常習慣').fill('測試用匿名住民，午餐約十二點。')
        page.get_by_role('button', name='建立住民', exact=True).last.click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        report['checks'].append('resident creation')
        page.get_by_role('button', name='新增影片', exact=True).click()
        page.locator('input[type=file]').set_input_files(str(ROOT/'test_videos/fall_event.mp4'))
        page.get_by_label('實際拍攝開始時間').fill('2026-09-28T10:00')
        page.get_by_role('button', name='上傳並開始分析').click()
        expect(page.get_by_role('dialog')).not_to_be_visible(timeout=60000)
        page.locator('video').or_(page.get_by_role('heading', name='分析失敗', exact=True)).wait_for(timeout=600000)
        if not page.locator('video').count():
            raise RuntimeError('Video analysis failed: '+page.locator('.analysis-state').inner_text())
        page.locator('video').evaluate('(v) => new Promise((resolve, reject) => { if(v.readyState >= 1) return resolve(true); v.addEventListener("loadedmetadata", () => resolve(true), {once:true}); v.addEventListener("error", reject, {once:true}); })')
        details = page.request.get(url+'/api/videos').json()[0]
        vid = details['id']
        details = page.request.get(url+f'/api/videos/{vid}').json()
        report['video'] = {k:v for k,v in details.items() if k in ('status','duration','details','selected_track','events')}
        assert details['status'] == 'done'
        if details['selected_track'] is None and details['details']['tracks']:
            page.get_by_label('此住民對應的追蹤代號').select_option(str(details['details']['tracks'][0]['id']))
        report['checks'].append('real upload, progress, YOLO + OmDet analysis, playable skeleton')
        page.screenshot(path=str(OUT/'02-workspace.png'), full_page=True)
        page.get_by_label('照護問題').fill('有疑似跌倒嗎？')
        with page.expect_response('**/api/query', timeout=180000) as response:
            page.get_by_role('button', name='送出問題').click()
        result = response.value.json()
        assert result['plan']['kind'] == 'fall', result
        report['query'] = result
        assert result['mode'] == 'local_llm', result
        expect(page.locator('.answer')).to_be_visible()
        report['checks'].append('real local LLM question and evidence response')
        if details['events']:
            page.locator('.event-card .event-actions button').first.click()
            expect(page.locator('video')).to_be_visible()
            page.locator('.event-card').first.get_by_role('button', name='人工覆核').click()
            page.get_by_label('覆核結果').select_option('confirmed')
            page.get_by_label('備註', exact=True).fill('端到端測試覆核：已回看骨架；此為操作測試，非臨床判讀。')
            page.get_by_role('button', name='儲存覆核').click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            report['checks'].append('evidence navigation and review persistence')
        page.get_by_role('button', name='照護日誌').click()
        with page.expect_download() as download:
            page.get_by_role('link', name='匯出 CSV').click()
        download.value.save_as(OUT/'records.csv')
        assert (OUT/'records.csv').stat().st_size > 0
        report['checks'].append('CSV export')
        page.screenshot(path=str(OUT/'03-journal.png'), full_page=True)
        page.reload()
        expect(page.get_by_text('展示住民 A', exact=True).first).to_be_visible()
        proc.terminate(); proc.wait(timeout=20)
        proc = start_server()
        page.reload()
        persisted = page.request.get(url+f'/api/videos/{vid}').json()
        assert persisted['status'] == 'done'
        assert any(e['review'] == 'confirmed' for e in persisted['events'])
        report['checks'].append('service restart retains video, events and review')
        page.screenshot(path=str(OUT/'04-overview.png'), full_page=True)
        for width, height, name in [(834,1112,'tablet'),(390,844,'mobile')]:
            page.set_viewport_size({'width':width,'height':height})
            page.screenshot(path=str(OUT/f'05-{name}.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), name
        report['checks'].append('tablet and mobile have no horizontal overflow')
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_role('button', name='影片與資料').click()
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name='刪除 fall_event.mp4').click()
        expect(page.get_by_role('heading', name='還沒有上傳影片')).to_be_visible()
        assert page.request.get(url+f'/api/videos/{vid}').status == 404
        report['checks'].append('delete removes video and evidence')
        assert not report['errors'], report['errors']
        browser.close()
except Exception as exc:
    report['failure'] = repr(exc)
    raise
finally:
    proc.terminate()
    proc.wait(timeout=20)
    log.close()
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Acceptance artifacts:', OUT, flush=True)
    print(json.dumps({'checks':report['checks'], 'errors':report['errors'], 'failure':report.get('failure')},ensure_ascii=False), flush=True)
