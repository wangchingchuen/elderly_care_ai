"""Browser acceptance against REAL YOLO/OmDet and local LLM. Requires local sample video."""
import argparse
import re
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
parser = argparse.ArgumentParser()
parser.add_argument('--language', choices=['zh-TW', 'en'], default='zh-TW')
LANG = parser.parse_args().language
CATALOG = json.loads((ROOT/'caretrace/locales/en.json').read_text(encoding='utf-8'))
def ui(text):
    return CATALOG.get(text, text) if LANG == 'en' else text


def check_english(page):
    if LANG != 'en':
        return
    # Test fixtures use English user content. The language switch intentionally uses Chinese.
    text = page.locator('body').inner_text().replace('繁體中文', '')
    assert not re.search(r'[\u3400-\u9fff]', text), text
    for element in page.locator('[placeholder], [aria-label], [title]').all():
        if 'language-toggle' in (element.get_attribute('class') or ''):
            continue
        for attribute in ['placeholder', 'aria-label', 'title']:
            value = element.get_attribute(attribute) or ''
            assert not re.search(r'[\u3400-\u9fff]', value), value


def toggle_twice(page, scope=None):
    scope = scope or page
    button = scope.locator('button.language-toggle')
    button.click()
    expect(page.locator('html')).to_have_attribute('lang', 'zh-TW' if LANG == 'en' else 'en')
    button.click()
    expect(page.locator('html')).to_have_attribute('lang', LANG)

OUT = ROOT/'artifacts'/('e2e-'+uuid.uuid4().hex[:8])
OUT.mkdir(parents=True)
env = {**os.environ, 'CARETRACE_DATA_DIR': str(OUT/'data'), 'CARETRACE_PORT': '5057', 'PYTHONUTF8': '1'}
url = 'http://127.0.0.1:5057'
report = {'language': LANG, 'checks': [], 'errors': []}
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
        if LANG == 'en':
            page.get_by_role('button', name='Switch to English').click()
        expect(page.locator('html')).to_have_attribute('lang', LANG)
        expect(page.get_by_role('heading', name=ui('讓每一份照護，都有依據。'))).to_be_visible()
        page.screenshot(path=str(OUT/'01-empty.png'), full_page=True)
        page.get_by_role('button', name=ui('建立住民'), exact=True).click()
        page.get_by_label(ui('住民代號或名稱')).fill('Demo resident A')
        page.get_by_label(ui('床位／房間')).fill('Ward A, bed 17')
        page.get_by_label(ui('照護背景與日常習慣')).fill('Anonymous test resident. Lunch at noon.')
        check_english(page)
        toggle_twice(page, page.get_by_role('dialog'))
        expect(page.get_by_label(ui('住民代號或名稱'))).to_have_value('Demo resident A')
        expect(page.get_by_label(ui('床位／房間'))).to_have_value('Ward A, bed 17')
        report['checks'].append('switching languages preserves unsaved resident form')
        page.get_by_role('button', name=ui('建立住民'), exact=True).last.click()
        expect(page.get_by_role('dialog')).not_to_be_visible()
        report['checks'].append('resident creation')
        page.get_by_role('button', name=ui('新增影片'), exact=True).click()
        page.locator('input[type=file]').set_input_files(str(ROOT/'test_videos/fall_event.mp4'))
        page.get_by_label(ui('實際拍攝開始時間')).fill('2026-09-28T10:00')
        check_english(page)
        toggle_twice(page, page.get_by_role('dialog'))
        assert page.locator('input[type=file]').evaluate('(el) => el.files[0].name') == 'fall_event.mp4'
        expect(page.get_by_label(ui('實際拍攝開始時間'))).to_have_value('2026-09-28T10:00')
        page.get_by_role('button', name=ui('上傳並開始分析')).click()
        expect(page.get_by_role('dialog')).not_to_be_visible(timeout=60000)
        page.locator('video').or_(page.get_by_role('heading', name=ui('分析失敗'), exact=True)).wait_for(timeout=600000)
        if not page.locator('video').count():
            raise RuntimeError('Video analysis failed: '+page.locator('.analysis-state').inner_text())
        page.locator('video').evaluate('(v) => new Promise((resolve, reject) => { if(v.readyState >= 1) return resolve(true); v.addEventListener("loadedmetadata", () => resolve(true), {once:true}); v.addEventListener("error", reject, {once:true}); })')
        details = page.request.get(url+'/api/videos').json()[0]
        vid = details['id']
        details = page.request.get(url+f'/api/videos/{vid}').json()
        report['video'] = {k:v for k,v in details.items() if k in ('status','duration','details','selected_track','events')}
        assert details['status'] == 'done'
        if details['selected_track'] is None and details['details']['tracks']:
            with page.expect_response('**/assign'):
                page.get_by_label(ui('此住民對應的追蹤代號（可複選）')).select_option(str(details['details']['tracks'][0]['id']))
            expect(page.get_by_label(ui('此住民對應的追蹤代號（可複選）'))).to_be_enabled()
        if len(details['details']['tracks']) > 1:
            tracks = [str(t['id']) for t in details['details']['tracks'][:2]]
            with page.expect_response('**/assign'):
                page.get_by_label(ui('此住民對應的追蹤代號（可複選）')).select_option(tracks)
            expect(page.get_by_label(ui('此住民對應的追蹤代號（可複選）'))).to_be_enabled()
            assigned = page.request.get(url+f'/api/videos/{vid}').json()['details']['assigned_tracks']
            assert sorted(assigned) == sorted(map(int, tracks))
            with page.expect_response('**/assign'):
                page.get_by_label(ui('此住民對應的追蹤代號（可複選）')).select_option(tracks[:1])
            expect(page.get_by_label(ui('此住民對應的追蹤代號（可複選）'))).to_be_enabled()
            report['checks'].append('manual multi-track assignment UI')
        report['checks'].append('real upload, progress, YOLO + OmDet analysis, playable skeleton')
        if page.locator('.segment.fall').count():
            target = [e for e in details['events'] if e['kind']=='fall' and e['track_id']==details['details']['tracks'][0]['id']][-1]['start']
            page.locator('.segment.fall').last.click()
            assert abs(page.locator('video').evaluate('(v) => v.currentTime')-target) < .3
            report['checks'].append('timeline seeks to actual evidence timestamp')
        page.screenshot(path=str(OUT/'02-workspace.png'), full_page=True)
        check_english(page)
        page.get_by_label(ui('照護問題')).fill(ui('有疑似跌倒嗎？'))
        with page.expect_response('**/api/query', timeout=180000) as response:
            page.get_by_role('button', name=ui('送出問題')).click()
        result = response.value.json()
        assert result['plan']['kind'] == 'fall', result
        report['query'] = result
        assert result['mode'] == 'local_llm', result
        expect(page.locator('.answer')).to_be_visible()
        expect(page.locator('.answer > p').first).to_have_text(result['answers'][LANG])
        playback = page.locator('video').evaluate('(v) => v.currentTime')
        source = page.locator('video').get_attribute('src')
        other = 'zh-TW' if LANG == 'en' else 'en'
        page.locator('button.language-toggle').click()
        expect(page.locator('.answer > p').first).to_have_text(result['answers'][other])
        page.locator('button.language-toggle').click()
        expect(page.locator('.answer > p').first).to_have_text(result['answers'][LANG])
        assert page.locator('video').get_attribute('src') == source
        assert abs(page.locator('video').evaluate('(v) => v.currentTime')-playback) < .1
        expect(page.get_by_label(ui('照護問題'))).to_have_value(ui('有疑似跌倒嗎？'))
        check_english(page)
        report['checks'].append('existing answer translates without new query and playback is preserved')
        report['checks'].append('real local LLM question and evidence response')
        if details['events']:
            page.locator('.event-card .event-actions button').first.click()
            expect(page.locator('video')).to_be_visible()
            page.locator('.event-card').first.get_by_role('button', name=ui('人工覆核')).click()
            page.get_by_label(ui('覆核結果')).select_option('confirmed')
            page.get_by_label(ui('備註'), exact=True).fill('Replay checked for workflow testing, not a clinical assessment.')
            page.get_by_text(ui('辨識線索與覆核歷程'), exact=True).click()
            check_english(page)
            toggle_twice(page, page.get_by_role('dialog'))
            expect(page.get_by_label(ui('覆核結果'))).to_have_value('confirmed')
            expect(page.get_by_label(ui('備註'), exact=True)).to_have_value('Replay checked for workflow testing, not a clinical assessment.')
            page.get_by_role('button', name=ui('儲存覆核')).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            report['checks'].append('evidence navigation and review persistence')
        page.get_by_role('button', name=ui('照護日誌')).click()
        with page.expect_download() as download:
            page.get_by_role('link', name=ui('匯出 CSV')).click()
        download.value.save_as(OUT/'records.csv')
        assert (OUT/'records.csv').stat().st_size > 0
        assert (OUT/'records.csv').read_text(encoding='utf-8-sig').startswith('Event ID,Resident' if LANG == 'en' else '事件編號,住民')
        check_english(page)
        report['checks'].append('CSV export')
        page.screenshot(path=str(OUT/'03-journal.png'), full_page=True)
        page.reload()
        expect(page.locator('html')).to_have_attribute('lang', LANG)
        expect(page.get_by_label(ui('切換住民'))).to_have_value(details['resident_id'])
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
            expect(page.get_by_label(ui('切換住民'))).to_be_visible()
            expect(page.get_by_role('button', name=ui('建立其他住民'))).to_be_visible()
            expect(page.locator('button.language-toggle')).to_be_visible()
            toggle_twice(page)
            check_english(page)
            page.screenshot(path=str(OUT/f'05-{name}.png'), full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), name
        report['checks'].append('tablet and mobile have no horizontal overflow')
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_role('button', name=ui('影片與資料')).click()
        check_english(page)
        page.on('dialog', lambda dialog: dialog.accept())
        page.get_by_role('button', name=ui('刪除 {0}').replace('{0}', 'fall_event.mp4')).click()
        expect(page.get_by_role('heading', name=ui('還沒有上傳影片'))).to_be_visible()
        assert page.request.get(url+f'/api/videos/{vid}').status == 404
        report['checks'].append('delete removes video and evidence')
        rid = page.request.get(url+'/api/residents').json()[0]['id']
        response = page.request.post(url+'/api/videos', multipart={'resident_id':rid,'recorded_at':'2026-09-28T12:00:00+08:00','video':{'name':'corrupt.mp4','mimeType':'video/mp4','buffer':b'not a real video'}})
        assert response.status == 202
        bad_id = response.json()['id']
        for _ in range(100):
            bad = page.request.get(url+f'/api/videos/{bad_id}').json()
            if bad['status']=='error': break
            time.sleep(.1)
        assert bad['status']=='error' and bad['error']
        page.reload()
        page.get_by_role('button', name=ui('影片與資料')).click()
        page.get_by_role('button', name=ui('查看'), exact=False).last.click()
        expect(page.get_by_role('heading',name=ui('分析失敗'),exact=True)).to_be_visible()
        check_english(page)
        assert page.request.delete(url+f'/api/videos/{bad_id}').status == 204
        report['checks'].append('corrupt video produces visible failure and remains deletable')
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
