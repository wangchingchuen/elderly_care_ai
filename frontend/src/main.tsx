import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowDownToLine, ArrowRight, Check, CheckCheck, ChevronDown, CircleHelp, Clock3, FileText, Film, LayoutDashboard, LoaderCircle, MessageSquareText, Plus, Search, ShieldCheck, Sparkles, Trash2, Upload, Users, X, RotateCcw, Eye, ScanLine, CircleAlert, ArrowUpRight, CalendarDays, Play } from 'lucide-react';
import './style.css';

type Resident = { id: string; name: string; bed: string; context: string };
type Evidence = { id: string; video_id: string; track_id: number; kind: string; start: number; end: number; score: number; review: string; note: string; filename?: string; recorded_at?: string; resident_name?: string; signals: Record<string, unknown> };
type Video = { id: string; filename: string; status: string; recorded_at: string; created_at: string; progress: number; stage: string; duration: number; error: string | null; selected_track: number | null; events?: Evidence[]; daily_enabled: number; details: { tracks?: { id: number; samples: number }[]; assigned_tracks?: number[]; elapsed_seconds?: number; device?: string; note?: string } };
type Answer = { answer: string; mode: string; warning?: string; plan: { kind: string }; evidence: Evidence[]; comparison_evidence: Evidence[]; scope: { start?: string; end?: string } };
const labels: Record<string, string> = { standing: '站立', sitting: '坐姿', lying: '躺臥', fall: '疑似跌倒', normal_lying: '坐姿轉躺臥', eating: '進食候選' };
const statusLabel: Record<string, string> = { queued: '等待分析', processing: '分析中', done: '已完成', error: '分析失敗', interrupted: '已中斷' };
const reviewLabel: Record<string, string> = { pending: '待覆核', confirmed: '已確認', rejected: '已排除' };
const stamp = (n: number) => `${Math.floor(n / 60).toString().padStart(2, '0')}:${Math.floor(n % 60).toString().padStart(2, '0')}`;
const datetime = (v: string) => new Date(v).toLocaleString('zh-TW', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
const localNow = () => { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) { const value = await response.json().catch(() => ({})); throw new Error(value.error || `請求失敗 (${response.status})`); }
  return response.status === 204 ? undefined as T : response.json();
}
const post = (value: unknown): RequestInit => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });

function App() {
  const [page, setPage] = useState('overview');
  const [residents, setResidents] = useState<Resident[]>([]);
  const [resident, setResident] = useState('');
  const [videos, setVideos] = useState<Video[]>([]);
  const [log, setLog] = useState<Evidence[]>([]);
  const [video, setVideo] = useState<Video | null>(null);
  const [modal, setModal] = useState<'resident' | 'upload' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [search, setSearch] = useState('');
  const [original, setOriginal] = useState(false);
  const [seek, setSeek] = useState(0);
  const [current, setCurrent] = useState(0);
  const [review, setReview] = useState<Evidence | null>(null);
  const [history, setHistory] = useState<{ status: string; note: string; created_at: string }[]>([]);
  const [health, setHealth] = useState<{ version: string; llm_loaded: boolean } | null>(null);
  const player = useRef<HTMLVideoElement>(null);
  const selection = useRef('');
  const residentInfo = residents.find(r => r.id === resident);
  const pending = log.filter(e => e.review === 'pending');
  const completed = videos.filter(v => v.status === 'done');
  const processing = videos.filter(v => ['queued', 'processing'].includes(v.status));
  const assignedTracks = video?.details.assigned_tracks ?? (video?.selected_track != null ? [video.selected_track] : []);
  const chosenEvents = (video?.events || []).filter(e => !assignedTracks.length || assignedTracks.includes(e.track_id));

  async function refresh(id = resident) {
    if (!id) { setVideos([]); setLog([]); return; }
    const filters = new URLSearchParams({ resident_id: id, start, end });
    const [v, l] = await Promise.all([api<Video[]>(`/api/videos?resident_id=${id}`), api<Evidence[]>(`/api/log?${filters}`)]);
    if (selection.current !== id) return;
    setVideos(v); setLog(l);
  }
  useEffect(() => {
    api<Resident[]>('/api/residents').then(r => { setResidents(r); if (r[0]) setResident(r[0].id); }).catch(e => setError(e.message));
    api<typeof health>('/api/health').then(setHealth).catch(e => setError(e.message));
  }, []);
  useEffect(() => { selection.current = resident; setVideo(null); setAnswer(null); setOriginal(false); refresh().catch(e => setError(e.message)); }, [resident, start, end]);
  useEffect(() => {
    if (!processing.length) return;
    const timer = window.setInterval(() => { refresh().catch(e => setError(e.message)); if (video) api<Video>(`/api/videos/${video.id}`).then(setVideo).catch(e => setError(e.message)); }, 2000);
    return () => clearInterval(timer);
  }, [resident, processing.length, video?.id, start, end]);
  useEffect(() => { if (notice) { const t = setTimeout(() => setNotice(''), 4500); return () => clearTimeout(t); } }, [notice]);
  useEffect(() => { if (!modal && !review) return; const listener = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) { setModal(null); setReview(null); } }; window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener); }, [modal, review, busy]);

  async function openVideo(id: string, at = 0) {
    try { const v = await api<Video>(`/api/videos/${id}`); setVideo(v); setSeek(at); setCurrent(at); setOriginal(false); setPage('workspace'); if (player.current && video?.id === id) player.current.currentTime = at; }
    catch (e) { setError((e as Error).message); }
  }
  async function ask(text = question) {
    if (!text.trim() || !resident) return;
    setQuestion(text); setAsking(true); setError('');
    const id = resident;
    try { const result = await api<Answer>('/api/query', post({ resident_id: id, question: text, start, end, previous_kind: answer?.plan.kind })); if (selection.current === id) setAnswer(result); }
    catch (e) { setError((e as Error).message); }
    finally { setAsking(false); }
  }
  async function removeVideo(v: Video) {
    if (!window.confirm(`刪除「${v.filename}」？原始影片、骨架證據、事件及相關查詢紀錄會一併移除。`)) return;
    try { await api(`/api/videos/${v.id}`, { method: 'DELETE' }); if (video?.id === v.id) setVideo(null); setAnswer(null); await refresh(); setNotice('影片與相關紀錄已刪除'); } catch (e) { setError((e as Error).message); }
  }
  async function openReview(e: Evidence) {
    setReview(e); setHistory([]);
    try { setHistory(await api(`/api/events/${e.id}/reviews`)); } catch (err) { setError((err as Error).message); }
  }
  async function saveReview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!review) return;
    const form = new FormData(event.currentTarget); setBusy(true);
    try { await api(`/api/events/${review.id}/reviews`, post({ status: form.get('status'), note: form.get('note') })); setReview(null); setAnswer(null); await refresh(); if (video) setVideo(await api(`/api/videos/${video.id}`)); setNotice('覆核結果已儲存，修改紀錄已保留'); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function submitModal(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    const form = new FormData(event.currentTarget);
    try {
      if (modal === 'resident') {
        const r = await api<Resident>('/api/residents', post(Object.fromEntries(form)));
        setResidents(old => [...old, r]); setResident(r.id); setNotice('住民資料已建立');
      } else {
        form.set('resident_id', resident); form.set('recorded_at', new Date(String(form.get('recorded_at'))).toISOString()); form.set('daily_enabled', form.has('daily_enabled') ? 'true' : 'false');
        const v = await api<Video>('/api/videos', { method: 'POST', body: form }); setVideo(v); setPage('workspace'); await refresh(); setNotice('影片已加入分析佇列');
      }
      setModal(null);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  const eventCard = (e: Evidence, index = 0) => <article className={`event-card ${e.kind === 'fall' ? 'attention' : ''}`} key={e.id}>
    <div className={`event-icon ${e.kind}`}><Activity size={18} /></div>
    <div className="event-copy"><div className="event-top"><strong>{labels[e.kind]}</strong><span className={`badge ${e.review}`}>{reviewLabel[e.review]}</span></div>
      <p>{e.recorded_at ? datetime(e.recorded_at) + ' · ' : ''}T{e.track_id} · {stamp(e.start)}–{stamp(e.end)}</p>
      {e.note && <p className="review-note">{e.note}</p>}
      <div className="event-actions"><button className="text-button" onClick={() => openVideo(e.video_id, e.start)} aria-label={`回看證據 ${index + 1}`}><Play size={12}/> 回看證據</button><button className="text-button muted" onClick={() => openReview(e)}>人工覆核 <ArrowUpRight size={12}/></button></div>
    </div></article>;

  const queryPanel = <section className="query-panel panel"><div className="panel-heading"><span className="icon-tile"><Sparkles size={18}/></span><div><h2>問問照護紀錄</h2><p>每個回答，都有跡可循</p></div></div>
    <div className="query-intro"><MessageSquareText size={28}/><h3>想確認哪一段日常？</h3><p>從一個問題開始，找到對應的紀錄與證據。</p></div>
    <div className="suggestions">{['有進食紀錄嗎？', '有疑似跌倒嗎？', '整理照護紀錄'].map(q => <button disabled={asking || !resident} key={q} onClick={() => ask(q)}>{q}<ArrowUpRight size={13}/></button>)}</div>
    <form className="question-box" onSubmit={e => { e.preventDefault(); ask(); }}><textarea aria-label="照護問題" placeholder="例如：這週和上週的進食紀錄有什麼不同？" value={question} maxLength={1000} onChange={e => setQuestion(e.target.value)}/><div><span><ShieldCheck size={12}/> 本機查詢・證據限定</span><button aria-label="送出問題" disabled={!resident || asking || !question.trim()}>{asking ? <LoaderCircle className="spin" size={18}/> : <ArrowRight size={18}/>}</button></div></form>
    {asking && <div className="query-loading" role="status"><LoaderCircle className="spin" size={17}/> 正在整理證據，首次載入模型可能較久…</div>}
    {answer && <div className="answer" aria-live="polite"><div className="eyebrow"><Sparkles size={13}/>{answer.mode === 'local_llm' ? '本機 LLM 查詢規劃' : '關鍵字備援'}</div><p>{answer.answer}</p>{answer.warning && <p className="warning">{answer.warning}</p>}<small>範圍：{answer.scope.start || '最早紀錄'} → {answer.scope.end || '最新紀錄'}</small><div className="answer-evidence">{answer.evidence.slice(0, 30).map((e, i) => eventCard(e, i))}</div>{answer.evidence.length > 30 && <p>其餘證據請至照護日誌查看。</p>}{answer.comparison_evidence.length > 0 && <details><summary>對照期間證據（{answer.comparison_evidence.length}）</summary>{answer.comparison_evidence.slice(0, 30).map((e, i) => eventCard(e, i))}</details>}</div>}
    <div className="gentle-note"><CircleHelp size={14}/><span>未找到紀錄不代表沒有發生。最終判斷由照護者保留。</span></div>
  </section>;

  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="/" aria-label="CareTrace 首頁"><span className="brand-mark"><Activity size={24}/></span><span>CareTrace<small>有跡可循的照護</small></span></a>
      <div className="workspace-tag"><span className="live-dot"/> 本機照護工作區 <ChevronDown size={14}/></div>
      <div className="nav-caption">工作空間</div><nav>{[{ id: 'overview', name: '照護總覽', icon: LayoutDashboard }, { id: 'workspace', name: '證據工作區', icon: ScanLine }, { id: 'journal', name: '照護日誌', icon: FileText }, { id: 'library', name: '影片與資料', icon: Film }].map(item => <button key={item.id} className={page === item.id ? 'active' : ''} onClick={() => setPage(item.id)}><item.icon size={19}/>{item.name}{item.id === 'journal' && pending.length > 0 && <span className="nav-count">{pending.length}</span>}</button>)}</nav>
      <div className="resident-heading"><span>照護對象</span><button className="icon-button" aria-label="新增住民" onClick={() => setModal('resident')}><Plus size={16}/></button></div>
      <div className="residents">{residents.map((r, i) => <button className={resident === r.id ? 'selected' : ''} key={r.id} onClick={() => setResident(r.id)}><span className={`avatar avatar-${i % 3}`}>{r.name.slice(0, 1)}</span><span>{r.name}<small>{r.bed || '未設定床位'}</small></span>{resident === r.id && <span className="selection-dot"/>}</button>)}{!residents.length && <button className="add-resident" onClick={() => setModal('resident')}><Plus size={16}/> 建立第一位住民</button>}</div>
      <div className="privacy-card"><ShieldCheck size={23}/><strong>讓證據留下，讓隱私受到照顧。</strong><p>本機處理 · 預設骨架呈現<br/>人工覆核 · 原始資料可刪除</p><span>PRIVACY BY DESIGN</span></div><div className="sidebar-footer"><span className="live-dot"/>{health ? `本機服務已連線 · v${health.version}` : '連線中…'}</div>
    </aside>
    <main><header className="topbar"><div>CareTrace <span>/</span> {({ overview: '照護總覽', workspace: '證據工作區', journal: '照護日誌', library: '影片與資料' } as Record<string, string>)[page]}</div><div className="topbar-right"><span><ShieldCheck size={14}/> Local & private</span><span className="user-avatar">照</span></div></header>
      <div className="main-content"><div className="page-heading"><div><div className="eyebrow">CARE WITH CONFIDENCE</div><h1>{page === 'overview' ? '讓每一份照護，都有依據。' : page === 'workspace' ? '看見紀錄背後的證據。' : page === 'journal' ? '把日常，整理成可信的紀錄。' : '照護資料，安心留在本機。'}</h1><p>{residentInfo ? `${residentInfo.name}${residentInfo.bed ? ' · '+residentInfo.bed : ''} 的照護工作區` : '建立照護對象，上傳第一段影片，開始留下可追溯的紀錄。'}</p></div><button className="primary" onClick={() => setModal(resident ? 'upload' : 'resident')}><Plus size={17}/>{resident ? '新增影片' : '建立住民'}</button></div>
      {error && <div className="alert error" role="alert"><CircleAlert size={18}/><span>{error}</span><button className="icon-button" aria-label="關閉錯誤" onClick={() => setError('')}><X size={16}/></button></div>}
      {notice && <div className="toast" role="status"><CheckCheck size={17}/>{notice}</div>}
      <div className="scope-row"><div className="scope-person"><Users size={16}/><select aria-label="切換住民" value={resident} onChange={e => setResident(e.target.value)}><option value="" disabled>尚未選擇住民</option>{residents.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select><button className="icon-button" aria-label="建立其他住民" onClick={() => setModal('resident')}><Plus size={15}/></button><span>紀錄範圍</span></div><div className="date-filter"><CalendarDays size={15}/><input aria-label="開始日期" type="date" value={start} onChange={e => setStart(e.target.value)}/><span>—</span><input aria-label="結束日期" type="date" value={end} onChange={e => setEnd(e.target.value)}/>{(start || end) && <button className="icon-button" aria-label="清除日期" onClick={() => { setStart(''); setEnd(''); }}><X size={14}/></button>}</div></div>
      {page === 'overview' && <><section className="stats"><div className="stat"><span><Film size={16}/> 已分析影片</span><strong>{completed.length}<small>段</small></strong><p>{processing.length ? `${processing.length} 段正在處理` : '已保存，可隨時回看'}</p><span className="stat-decoration" aria-hidden="true"><Film size={62}/></span></div><div className="stat"><span><Activity size={16}/> 行為證據</span><strong>{log.length}<small>段</small></strong><p>依目前日期與住民篩選</p><span className="stat-decoration"><Activity size={64}/></span></div><div className="stat"><span><CheckCheck size={16}/> 人工已確認</span><strong>{log.filter(e => e.review === 'confirmed').length}<small>段</small></strong><p>保留覆核與備註紀錄</p><span className="stat-decoration"><ShieldCheck size={62}/></span></div><div className="stat warm"><span><Clock3 size={16}/> 等待覆核</span><strong>{pending.length}<small>段</small></strong><p>你的判斷，讓紀錄更完整</p><button className="text-button" onClick={() => setPage('journal')}>前往覆核 <ArrowRight size={13}/></button></div></section>
      <div className="overview-grid"><div><section className="hero-panel"><div className="eyebrow"><span className="live-dot"/> FROM MOMENTS TO EVIDENCE</div><h2>不只知道發生了什麼，<br/>還能看見它的依據。</h2><p>串起行為、時間與證據，<br/>讓關心有答案，讓照護有紀錄。</p><button onClick={() => setPage('workspace')}>開啟證據工作區 <ArrowRight size={16}/></button><div className="orbit-art" aria-hidden="true"><div className="orbit o1"/><div className="orbit o2"/><div className="orbit o3"/><span className="orbit-center"><Activity size={45}/></span><span className="orbit-node node-1"><ShieldCheck size={20}/></span><span className="orbit-node node-2"><Check size={19}/></span><span className="orbit-node node-3"><FileText size={18}/></span></div></section>
      <section className="panel recent"><div className="section-heading"><div><h2>最近的照護證據</h2><p>每一段日常，都值得被好好記錄</p></div><button className="text-button" onClick={() => setPage('journal')}>查看全部 <ArrowRight size={14}/></button></div>{log.length ? log.slice(-4).reverse().map((e, i) => eventCard(e, i)) : <Empty title="第一份照護紀錄，從這裡開始" text="分析影片後，這裡會呈現可回看的行為證據。" action={() => setModal(resident ? 'upload' : 'resident')} button="開始建立紀錄"/>}</section></div>{queryPanel}</div></>}
      {page === 'workspace' && <div className="work-grid"><div><section className="panel evidence-panel"><div className="section-heading"><div><h2>證據回看</h2><p>時間同步 · 行為軌跡 · 人工判讀</p></div><span className="badge confirmed"><ShieldCheck size={12}/> 骨架優先</span></div><select aria-label="選擇影片" value={video?.id || ''} onChange={e => e.target.value && openVideo(e.target.value)}><option value="">選擇一段影片</option>{videos.map(v => <option key={v.id} value={v.id}>{v.filename} · {statusLabel[v.status]}</option>)}</select>
      {video ? <>{video.status === 'done' ? <><div className="player-controls"><span><Film size={14}/>{video.filename}</span><button className="text-button" onClick={() => { setSeek(player.current?.currentTime || 0); setOriginal(!original); }}>{original ? <ScanLine size={14}/> : <Eye size={14}/>} {original ? '回到骨架' : '查看本機原始影片'}</button></div><video ref={player} controls preload="metadata" src={`/media/${video.id}/${original ? 'original' : 'skeleton'}`} onLoadedMetadata={() => { if (player.current) player.current.currentTime = seek; }} onTimeUpdate={() => setCurrent(player.current?.currentTime || 0)} onError={() => setError('瀏覽器無法播放這個影片格式，請使用骨架證據或轉換為 H.264 MP4。')}/><div className="playback-info"><span className="mono">{stamp(current)} <span>/ {stamp(video.duration)}</span></span><span>{original ? '原始畫面 · 僅供本機覆核' : '隱私視圖 · 無原始人像'}</span></div>
      {!!video.details.tracks?.length && <div className="track-select"><label htmlFor="track">此住民對應的追蹤代號（可複選）</label><select id="track" multiple disabled={assigning} value={assignedTracks.map(String)} onChange={async e => { const trackIds = Array.from(e.target.selectedOptions, o => Number(o.value)); setAssigning(true); try { await api(`/api/videos/${video.id}/assign`, post({ track_ids: trackIds })); setVideo(await api(`/api/videos/${video.id}`)); setAnswer(null); await refresh(); } catch (err) { setError((err as Error).message); } finally { setAssigning(false); } }} >{video.details.tracks.map(t => <option key={t.id} value={t.id}>Track {t.id} · {t.samples} 個取樣</option>)}</select></div>}
      {video.selected_track === null && <p className="warning">尚未指定住民追蹤對應，這段影片的事件不會納入照護查詢。</p>}
      {!!video.details.tracks?.length && <p className="tiny-note">同一人被分段追蹤時，可按住 Ctrl 複選。請回看確認，避免勾選其他人。</p>}
      <div className="timeline"><div className="timeline-caption"><span>行為時間軸</span><span>點選色塊即可回看</span></div>{Object.entries(labels).map(([kind, label]) => <div className="timeline-row" key={kind}><span>{label}</span><div className="timeline-lane">{chosenEvents.filter(e => e.kind === kind).map(e => <button key={e.id} className={`segment ${kind}`} style={{ left: `${e.start / video.duration * 100}%`, width: `${Math.max(.8, (e.end - e.start) / video.duration * 100)}%` }} title={`${label} ${stamp(e.start)}–${stamp(e.end)}`} aria-label={`${label} ${stamp(e.start)}`} onClick={() => { if (player.current) player.current.currentTime = e.start; }}/>) }<i className="playhead" style={{ left: `${Math.min(100, current / video.duration * 100)}%` }}/></div></div>)}</div><p className="tiny-note">取樣與追蹤可能漏失短暫或遮擋動作。模型分數並非行為正確機率。</p></> : <div className="analysis-state">{['queued', 'processing'].includes(video.status) ? <LoaderCircle className="spin" size={32}/> : <CircleAlert size={32}/>}<h3>{video.stage}</h3><p>{video.error || '分析會在背景繼續，您可以先瀏覽其他紀錄。'}</p><progress max="100" value={video.progress}/><span>{Math.round(video.progress)}%</span>{['error', 'interrupted'].includes(video.status) && <button className="secondary" onClick={async () => { try { setVideo(await api(`/api/videos/${video.id}/retry`, { method: 'POST' })); await refresh(); } catch (e) { setError((e as Error).message); } }}><RotateCcw size={15}/> 重新分析</button>}</div>}</> : <Empty title="選擇影片，查看行為的來龍去脈" text="每段證據都有時間範圍，點選即可回到當下。"/>}</section>
      {video?.status === 'done' && <section className="panel recent"><div className="section-heading"><h2>影片事件 <span className="count">{chosenEvents.length}</span></h2></div>{chosenEvents.length ? chosenEvents.map((e, i) => eventCard(e, i)) : <Empty title="尚無足夠行為證據" text="可查看骨架影片，確認畫面涵蓋與模型取樣狀況。"/>}</section>}</div>{queryPanel}</div>}
      {page === 'journal' && <section className="panel journal"><div className="section-heading"><div><h2>可追溯照護日誌</h2><p>時間以台灣時區顯示 · 人工覆核保留修改歷程</p></div><a className="secondary" href={`/api/export?${new URLSearchParams({ resident_id: resident, start, end })}`}><ArrowDownToLine size={16}/> 匯出 CSV</a></div><div className="search-field"><Search size={17}/><input aria-label="搜尋事件" placeholder="搜尋行為、影片或備註…" value={search} onChange={e => setSearch(e.target.value)}/></div>{log.length ? <div className="table-scroll"><table><thead><tr><th>時間 / 來源</th><th>行為證據</th><th>影片時間</th><th>覆核狀態</th><th>操作</th></tr></thead><tbody>{log.filter(e => `${labels[e.kind]} ${e.filename} ${e.note}`.includes(search)).map(e => <tr key={e.id}><td><strong>{e.recorded_at && datetime(new Date(new Date(e.recorded_at).getTime() + e.start * 1000).toISOString())}</strong><small>{e.filename}</small></td><td><span className={`kind-dot ${e.kind}`}/>{labels[e.kind]}<small>{e.note || `追蹤 T${e.track_id}`}</small></td><td className="mono">{stamp(e.start)}–{stamp(e.end)}</td><td><span className={`badge ${e.review}`}>{reviewLabel[e.review]}</span></td><td><div className="table-actions"><button className="icon-button" title="回看證據" onClick={() => openVideo(e.video_id, e.start)}><Play size={16}/></button><button className="secondary small" onClick={() => openReview(e)}>覆核</button></div></td></tr>)}</tbody></table></div> : <Empty title="這個範圍尚無照護紀錄" text="上傳影片並完成追蹤對應後，證據會自動整理在這裡。"/>}</section>}
      {page === 'library' && <><section className="panel library"><div className="section-heading"><div><h2>影片資料庫</h2><p>原始影片與分析結果只保存在本機</p></div><span className="badge neutral">{videos.length} 段影片</span></div>{videos.length ? videos.map(v => <div className="video-row" key={v.id}><div className="video-thumbnail"><Film size={25}/></div><div className="video-copy"><strong>{v.filename}</strong><p>{datetime(v.recorded_at)} · {v.duration ? stamp(v.duration) : '等待分析'} · {v.daily_enabled ? '姿態＋日常行為' : '僅姿態'}</p>{v.status === 'processing' && <progress max="100" value={v.progress}/>}</div><span className={`badge ${v.status === 'done' ? 'confirmed' : 'pending'}`}>{statusLabel[v.status]}</span><button className="secondary small" onClick={() => openVideo(v.id)}>查看 <ArrowUpRight size={13}/></button><button className="icon-button danger" aria-label={`刪除 ${v.filename}`} disabled={['queued', 'processing'].includes(v.status)} onClick={() => removeVideo(v)}><Trash2 size={16}/></button></div>) : <Empty title="還沒有上傳影片" text="支援 MP4、MOV、WebM、AVI，單檔 512 MB、15 分鐘以內。" action={() => setModal(resident ? 'upload' : 'resident')} button="新增影片"/>}</section>{residentInfo && <section className="panel profile"><div><h2>{residentInfo.name} 的照護背景</h2><p>{residentInfo.context || '尚未填寫照護背景。'}</p><small>影片歸屬由使用者指定，不使用人臉辨識。資料留在此電腦。</small></div><button className="text-button danger" onClick={async () => { if (!confirm('刪除住民資料？需先刪除所有相關影片。')) return; try { await api(`/api/residents/${resident}`, { method: 'DELETE' }); const remaining = residents.filter(r => r.id !== resident); setResidents(remaining); setResident(remaining[0]?.id || ''); } catch (e) { setError((e as Error).message); } }}><Trash2 size={14}/> 刪除住民</button></section>}</>}
      <footer className="page-footer"><span>CareTrace <span>·</span> Verifiable Daily Care Records</span><span>保留人的判斷，讓科技支持照護。</span></footer></div>
    </main>
    {(modal || review) && <div className="modal-backdrop"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><button className="modal-close icon-button" aria-label="關閉視窗" disabled={busy} onClick={() => { setModal(null); setReview(null); }}><X size={20}/></button><span className="modal-symbol">{review ? <CheckCheck size={25}/> : modal === 'resident' ? <Users size={25}/> : <Upload size={25}/>}</span><h2 id="modal-title">{review ? '人工覆核證據' : modal === 'resident' ? '建立照護對象' : '新增影片紀錄'}</h2><p>{review ? `${labels[review.kind]} · T${review.track_id} · ${stamp(review.start)}–${stamp(review.end)}` : modal === 'resident' ? '建議使用代號，資料僅保存在本機。' : `為 ${residentInfo?.name} 建立可回看的照護證據。`}</p>{error && <div className="alert error" role="alert">{error}</div>}
    {review ? <form onSubmit={saveReview}><label>覆核結果<select name="status" defaultValue={review.review}><option value="pending">待覆核</option><option value="confirmed">人工確認</option><option value="rejected">排除／誤判</option></select></label><label>備註<textarea name="note" maxLength={2000} defaultValue={review.note} placeholder="描述您在證據中看到的情況…"/></label><small>模型分數 {review.score.toFixed(3)} · 不是行為正確機率</small><details><summary>辨識線索與覆核歷程</summary><pre>{JSON.stringify(review.signals, null, 2)}</pre>{history.map((h, i) => <p key={i}>{datetime(h.created_at)} · {reviewLabel[h.status]} · {h.note || '無備註'}</p>)}</details><button className="primary wide" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16}/> : <Check size={16}/>} 儲存覆核</button></form> : <form onSubmit={submitModal}>{modal === 'resident' ? <><label>住民代號或名稱<input name="name" required maxLength={80} placeholder="例如：住民 A" autoFocus/></label><label>床位／房間<input name="bed" maxLength={40} placeholder="例如：A 區 17 床"/></label><label>照護背景與日常習慣<textarea name="context" maxLength={2000} placeholder="例如：午餐約 12 點、午後習慣休息。作為查詢背景，不自動作出照護決策。"/></label></> : <><label className="upload-field"><Upload size={25}/><strong>選擇本機影片</strong><span>MP4 / MOV / WebM / AVI · 512 MB · 15 分鐘</span><input name="video" type="file" accept=".mp4,.mov,.webm,.avi" required/></label><label>實際拍攝開始時間<input type="datetime-local" name="recorded_at" defaultValue={localNow()} required/></label><label className="checkbox"><input type="checkbox" name="daily_enabled" defaultChecked/><span>同時分析日常行為（OmDet-Turbo）<small>結合餐具／食物與手部動作；首次需下載模型。</small></span></label><p className="tiny-note">請確認這段影片屬於所選住民。多個追蹤對象需於分析完成後人工指定。</p></>}<button className="primary wide" disabled={busy}>{busy ? <LoaderCircle className="spin" size={16}/> : <ArrowRight size={16}/>} {busy ? '處理中…' : modal === 'resident' ? '建立住民' : '上傳並開始分析'}</button></form>}</section></div>}
  </div>;
}
function Empty({ title, text, action, button }: { title: string; text: string; action?: () => void; button?: string }) { return <div className="empty"><span><ScanLine size={28}/></span><h3>{title}</h3><p>{text}</p>{action && <button className="secondary" onClick={action}>{button}<ArrowRight size={14}/></button>}</div>; }
createRoot(document.getElementById('root')!).render(<App/>);
