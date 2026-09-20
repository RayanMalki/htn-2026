import { lazy, Suspense, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, finished, seconds } from './api';
import Authorship from './Authorship';
import Evidence from './Evidence';
import type { Case, ClaimResult } from './types';
import { ClaimCarousel, Overview, Scanner, ShareResult, Sheet, TopicExamples } from './MedbotUI';

const Dashboard = lazy(() => import('./Dashboard'));
const stages = ['queued', 'downloading', 'transcribing', 'researching', 'judging', 'rendering', 'complete'];
const labels: Record<string, string> = { queued: 'Queued', downloading: 'Reading the video', rendering: 'Creating your video', transcribing: 'Finding spoken claims', researching: 'Searching the literature', judging: 'Checking the evidence', complete: 'Analysis complete', awaiting_upload: 'Video upload needed', incomplete: 'Analysis incomplete', no_claims: 'No spoken medical claims' };

function CaseView({ value, onUpdate }: { value: Case; onUpdate: (c: Case) => void }) {
  const [tick, setTick] = useState(Date.now());
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const [about, setAbout] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [videoNotice, setVideoNotice] = useState(false);
  const [scannerPaused, setScannerPaused] = useState(false);
  const lastVideo = useRef(value.result.video?.status);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    if (value.result.video?.status === 'ready' && lastVideo.current !== 'ready') setVideoNotice(true);
    lastVideo.current = value.result.video?.status;
  }, [value.result.video?.status]);
  useEffect(() => {
    if (finished(value.status) || value.status === 'awaiting_upload') return;
    const timer = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [value.status]);
  const elapsed = finished(value.status) || value.status === 'awaiting_upload'
    ? value.result.timings?.total || 0
    : Math.max(value.result.timings?.total || 0, Math.max(0, (tick - Date.parse(value.result.submitted_at || value.created_at)) / 1000));
  const claims = value.result.analysis?.claims || [];
  const items: ClaimResult[] = claims.map(claim => value.result.claims?.[claim.id] || {
    claim, status: value.status === 'incomplete' ? 'incomplete' : 'researching',
    error: value.status === 'incomplete' ? 'This claim could not be assessed before the analysis stopped.' : undefined,
  });
  const activeIndex = stages.indexOf(value.status);

  async function upload(file?: File) {
    if (!file) return;
    if (file.size > 100 * 1024 * 1024) { setError('Please use a video under 100 MB.'); return; }
    setUploading(true); setError('');
    try {
      const body = new FormData(); body.append('file', file);
      onUpdate(await api<Case>(`/api/cases/${value.id}/media`, { method: 'POST', body }));
    } catch (e) { setError((e as Error).message); }
    finally { setUploading(false); }
  }

  return <section className="case-workspace" aria-label="Analysis results">
    <div className="result-intro"><span className="eyebrow"><span className="blue-dot" />YOUR CHECK, EXPLAINED</span><div className="result-question"><h1>Wait, does<br />the research<br /><em>back that up?</em></h1><div className="question-sculpture" aria-hidden="true"><span className="question-paper" /><b>?</b></div></div><p>Look past the promise. See what the retrieved evidence says about each claim, and what it leaves unanswered.</p></div>
    <div className="section-heading result-heading"><div><h2 ref={heading} tabIndex={-1}>{value.result.video?.status === 'failed' ? 'Evidence first. Video next.' : labels[value.status] || 'Checking your video'}</h2></div>
      <div className="elapsed"><span className={finished(value.status) ? 'status-dot' : 'status-dot live'} />
        {seconds(elapsed)}<span className="subtle"> elapsed · timing varies</span></div></div>
    <div className="clip-row"><span>Public video · spoken health claims</span><button className="text-button" onClick={() => setAbout(true)}>About this clip ↗</button></div>
    {about && <Sheet title="About this clip" onClose={() => setAbout(false)}><p>MedBot checks up to three spoken health claims. On-screen text, linked papers and comments are not independently extracted by this pipeline.</p><a className="source-link" href={value.source_url} target="_blank" rel="noreferrer">Original video ↗</a><p>This is an unlisted result, not a private medical record.</p></Sheet>}
    {!finished(value.status) && value.status !== 'awaiting_upload' && !items.some(item => item.verdict) && <div className="scan-progress"><Scanner active /><p role="status">{labels[value.status] || 'Waiting for an update'}…</p><p className="subtle">A real paper can still be used out of context. We check the claim against retrieved passages.</p></div>}
    <ol className="progress-stages" aria-label="Pipeline progress">{stages.slice(1).filter(s => s !== 'rendering' || value.result.video || value.status === 'rendering').map(s => {
      const i = stages.indexOf(s);
      const done = s === 'rendering' ? value.result.video?.status === 'ready' : activeIndex > i || value.status === 'complete';
      return <li key={s} aria-current={activeIndex === i ? 'step' : undefined} className={`${done ? 'done' : ''} ${activeIndex === i ? 'active' : ''}`}>
        <span>{done ? '✓' : i}</span>{['', 'Read video', 'Extract claims', 'Find research', 'Check evidence', 'Create video', 'Results'][i]}</li>;
    })}</ol>
    {value.result.model_mode === 'mock' ? <div className="notice"><b>Mock model mode</b> The claim and judgment are prepared inputs. Literature retrieval is real when configured. This is not an analysis of the submitted video.</div> : null}
    {items.length > 0 && <Overview items={items} mock={value.result.model_mode === 'mock'} />}
    {!finished(value.status) && elapsed > 90 && value.status !== 'awaiting_upload' ? <div className="notice">This run is taking longer than the demo target. Progress and any completed evidence remain available.</div> : null}
    {value.result.limitations?.length ? <div className="notice" aria-label="Analysis limitations">
      {value.result.limitations.map((limitation, i) => <p key={i}>{limitation}</p>)}
    </div> : null}
    {value.error ? <p className="error" role="alert">{value.error.message}</p> : null}
    {value.status === 'awaiting_upload' ? <div className="upload-panel"><span className="upload-symbol">↥</span><div><h3>Have the video file?</h3>
      <p>Upload it to continue this same analysis. Spoken English · up to 100 seconds · 100 MB.</p>
      <label className={`button upload-button ${uploading ? 'disabled' : ''}`}>{uploading ? 'Uploading…' : 'Choose video'}
        <input aria-label="Upload video" type="file" accept="video/*" disabled={uploading} onChange={e => void upload(e.target.files?.[0])} /></label></div></div> : null}
    {error ? <p className="error" role="alert">{error}</p> : null}
    {value.result.video?.status === 'rendering' || value.result.video?.status === 'pending' ? <section className="video-pending"><div className="explainer-heading"><Scanner active={!scannerPaused} /><div><span className="eyebrow">NEXT UP · YOUR EXPLAINER</span><h3>Your findings.<br />In a short video.</h3></div></div><p>Your assessment is ready. We’re preparing a captioned explanation.</p><p className="render-status" role="status">Creating video: {value.result.video.stage || 'preparing'}…</p><p>Read the findings below while your video comes together.</p><button className="text-button" aria-pressed={scannerPaused} onClick={() => setScannerPaused(v => !v)}>{scannerPaused ? 'Resume scanner animation' : 'Pause scanner animation'}</button></section> : null}
    {value.result.video?.status === 'ready' ? <section id="generated-video" className="generated-video" aria-label="Generated fact-check video">
      <div><span className="eyebrow">YOUR FACT-CHECK VIDEO</span><h3>Evidence, ready to watch.</h3>
        <p>One selected claim, with its sources and limitations. Explanations can run up to two minutes. Explore all assessed claims below.</p>
        <a className="button" href={`/api/cases/${value.id}/video?download=true`}>Download MP4 ↓</a>{' '}
        <a className="button secondary" href={`/api/cases/${value.id}/video/sources`}>Video sources ↓</a>
      </div>
      {value.result.video.selected_claim ? <p><b>Selected claim:</b> {value.result.video.selected_claim}</p> : null}
      <p>AI-generated narration. {value.result.video.caption_timing === 'whisper' ? 'Narration captions aligned to generated speech.' : 'Caption timings are approximate.'} Source excerpts are reproduced text, not original page captures.</p>
      <a href={`/api/cases/${value.id}/video/captions`}>Download captions ↓</a>
      {videoError && <p className="error" role="alert">The video could not load. It may have expired after 24 hours. Your written findings are still available.</p>}
      <video controls playsInline preload="metadata" onError={() => setVideoError(true)} src={`/api/cases/${value.id}/video`}>
        <track kind="captions" src={`/api/cases/${value.id}/video/captions`} srcLang="en" label="English" default />
      </video>
    </section> : null}
    {value.result.video?.status === 'failed' ? <p className="error">{value.result.video.error}</p> : null}
    {(value.status === 'incomplete' || (value.status === 'complete' && !value.result.video && value.result.model_mode === 'live')) ?
      <button className="button secondary" disabled={retrying} onClick={async () => {
        setRetrying(true); setError('');
        try { onUpdate(await api<Case>(`/api/cases/${value.id}/retry`, { method: 'POST' })); }
        catch (e) { setError((e as Error).message); }
        finally { setRetrying(false); }
      }}>{retrying ? 'Resuming…' : value.result.video?.status === 'failed' ? 'Retry video generation' : 'Retry analysis and create video'}</button> : null}
    {value.result.outcome ? <div className="notice">{value.result.outcome}</div> : null}
    {value.result.analysis?.omitted_claims ? <p className="notice">{value.result.analysis.omitted_claims} additional claim(s) were omitted from this bounded analysis.</p> : null}
    {items.length ? <ClaimCarousel count={items.length}>{items.map((item, i) => <Evidence key={item.claim.id} item={item} index={i} mock={value.result.model_mode === 'mock'} />)}</ClaimCarousel> : null}
    <Authorship value={value.result.detection} waiting={!finished(value.status)} hasTranscript={!!value.result.analysis?.transcript.length} />
    {value.result.analysis?.transcript.length ? <details className="transcript"><summary>Read the transcript</summary>
      {value.result.analysis.transcript.map((s, i) => <p key={i}><span>{Math.floor(s.start)}s</span>{s.text}</p>)}</details> : null}
    {finished(value.status) ? <><ShareResult value={value} /><div className="result-footer"><p>Evidence is contextual. This search is limited and is not personal medical advice.</p>
      <a className="button secondary" href={`/api/cases/${value.id}/replay`}>Download offline replay ↓</a></div></> : null}
    {videoNotice && <div className="ready-nudge" role="status"><a href="#generated-video" onClick={() => setVideoNotice(false)}>Your explanation is ready. Watch ↓</a><button aria-label="Dismiss video notification" onClick={() => setVideoNotice(false)}>×</button></div>}
  </section>;
}

export default function App() {
  const [tab, setTab] = useState<'check' | 'observatory'>('check');
  const [url, setUrl] = useState('');
  const [caseValue, setCase] = useState<Case | null>(null);
  const [caseId, setCaseId] = useState(() => new URLSearchParams(location.search).get('case'));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [connection, setConnection] = useState('');
  const [config, setConfig] = useState<{ model_mode: string } | null>(null);
  const [how, setHow] = useState(false);
  const [revision, setRevision] = useState(0);
  const [scrollProgress, setScrollProgress] = useState(0);
  const submittingRef = useRef(false);
  const sharedStarted = useRef(false);
  const activeCase = useRef(caseId);
  const request = useRef<AbortController | null>(null);
  activeCase.current = caseId;

  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    const update = () => setScrollProgress(Math.min(1, window.scrollY / Math.max(1, document.documentElement.scrollHeight - window.innerHeight)));
    window.addEventListener('scroll', update, { passive: true });
    window.addEventListener('resize', update); update();
    return () => { window.removeEventListener('scroll', update); window.removeEventListener('resize', update); };
  }, [caseValue, tab]);

  useEffect(() => { void api<{ model_mode: string }>('/api/config').then(setConfig).catch(() => setConnection('Backend unavailable')); }, []);
  useEffect(() => {
    if (!caseId) return;
    let disposed = false;
    let source: EventSource | null = null;
    const controller = new AbortController();
    void api<Case>(`/api/cases/${caseId}`, { signal: controller.signal }).then(c => {
      if (disposed) return;
      if (activeCase.current !== caseId) return;
      setCase(previous => previous?.id === c.id && previous.sequence > c.sequence ? previous : c);
      if (finished(c.status)) return;
      source = new EventSource(`/api/cases/${caseId}/events?after=${c.sequence}`);
      source.addEventListener('case', event => {
        if (disposed || activeCase.current !== caseId) return;
        try { const incoming = JSON.parse((event as MessageEvent).data) as Case;
          if (incoming.id !== caseId) return;
          setCase(previous => !previous || incoming.sequence >= previous.sequence ? incoming : previous);
          setConnection('');
        } catch { setConnection('Could not read an update. Reconnecting…'); }
      });
      source.addEventListener('end', () => { source?.close(); setConnection(''); });
      source.onopen = () => setConnection('');
      source.onerror = () => setConnection('Connection interrupted. Reconnecting to saved progress…');
    }).catch(e => { if (!disposed && activeCase.current === caseId) setError(e.message); });
    return () => { disposed = true; controller.abort(); source?.close(); };
  }, [caseId, revision]);

  function updateCase(c: Case) {
    if (activeCase.current !== c.id) return;
    setCase(previous => previous && previous.sequence > c.sequence ? previous : c);
    setRevision(v => v + 1);
  }

  async function start(sourceUrl: string) {
    if (submittingRef.current) return;
    submittingRef.current = true;
    const controller = new AbortController(); request.current = controller;
    setError(''); setSubmitting(true);
    try {
      const c = await api<Case>('/api/cases', { method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_url: sourceUrl.trim() }) });
      if (controller.signal.aborted) return;
      activeCase.current = c.id; setConnection('');
      setCase(c); setCaseId(c.id); history.replaceState(null, '', `?case=${c.id}`);
      window.scrollTo({ top: 0 });
    } catch (e) { if (!controller.signal.aborted) setError((e as Error).message); }
    finally { submittingRef.current = false; if (!controller.signal.aborted) setSubmitting(false); }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    await start(url);
  }

  // A shared link arrives as ?url=… from the iPhone share-sheet shortcut, a QR code or a
  // bookmarklet. Fill the box and start the check without a tap, unless a case is already open.
  useEffect(() => {
    const shared = new URLSearchParams(location.search).get('url');
    if (!shared || caseId || sharedStarted.current) return;
    sharedStarted.current = true;
    setUrl(shared);
    // Defer until Strict Mode's setup/cleanup probe has finished.
    const timer = setTimeout(() => void start(shared), 0);
    return () => { clearTimeout(timer); sharedStarted.current = false; };
  }, []);

  return <><a className="skip-link" href="#main">Skip to content</a><div className="desktop-note">MEDBOT / YOUR RESEARCH COMPANION</div><div className="app-shell"><div className="mesh" aria-hidden="true" /><header className="site-header"><a href="/" className="brand" aria-label="MedBot home"><span className="logo-pill" aria-hidden="true">m</span>medbot<span className="brand-period">.</span></a>
    {caseValue && finished(caseValue.status) ? <a className="header-share" href="#share-results">Share ↗</a> : <button className="text-button" onClick={() => setHow(true)}>How it works ↗</button>}</header>
    <div className="navigation-row">
    <nav aria-label="Main navigation"><button className={tab === 'check' ? 'selected' : ''} onClick={() => setTab('check')}>Check a Reel</button>
      <button className={tab === 'observatory' ? 'selected' : ''} onClick={() => setTab('observatory')}>Observatory</button></nav>
    </div>
    <main id="main">{tab === 'check' ? <><section className={`hero ${caseValue ? 'compact' : ''}`}>
      <div className="hero-copy">{!caseValue && <><span className="eyebrow"><span className="blue-dot" /> YOUR RESEARCH COMPANION</span>
        <h1>Big claims.<br />Let’s look<br /><em>closer.</em><span className="hero-asterisk" aria-hidden="true">✳</span></h1>
        <p className="hero-description">Health advice moves fast.<br />Give it a little more context.</p>
        <div className="platforms" aria-label="Supported platforms"><span>◎ Instagram Reels</span><span>▷ YouTube Shorts</span></div></>}
        <details className={`intake ${caseValue ? 'intake-result' : ''}`} open={!caseValue} key={caseValue?.id || 'home'}><summary>Check another video ↗</summary>
        <form onSubmit={submit} className="link-form"><label htmlFor="reel-url">Start with an Instagram Reel or YouTube Short</label>
          <div className="input-row"><span className="link-icon" aria-hidden="true">↗</span><input id="reel-url" type="url" inputMode="url" autoCapitalize="none" autoComplete="off" spellCheck={false} maxLength={2048} required aria-describedby="duration-help" placeholder="Paste your video link" value={url} onChange={e => setUrl(e.target.value)} />
            <button type="submit" disabled={submitting}>{submitting ? 'Starting…' : 'Check the evidence'}<span aria-hidden="true">↗</span></button></div>
          <div className="form-caption" id="duration-help"><b>Spoken English · Up to 100 seconds</b><span>Up to 3 claims, with sources and limitations.</span></div>
        </form></details>{error ? <p className="error" role="alert">{error}</p> : null}
        <div className="mode-line"><span className="status-dot" />{(caseValue?.result.model_mode || config?.model_mode) ? (caseValue?.result.model_mode || config?.model_mode) === 'mock' ? 'Infrastructure preview · mock AI adapters' : 'Live model pipeline' : 'Connecting to pipeline…'}
          <span className="mode-divider" />No account required</div>
      </div>
    </section>
    {connection ? <p className="notice" role="status">{connection}</p> : null}
    {caseId && !caseValue && !error ? <p role="status">Opening your saved check…</p> : null}
    {caseValue ? <CaseView key={caseValue.id} value={caseValue} onUpdate={updateCase} /> : <><section className="how-card"><div><span className="eyebrow">LESS GUESSWORK</span><h2>A second look.<br />Not a second opinion.</h2><p>Understand the claim.<br />See what backs it up.</p><button className="text-button" onClick={() => setHow(true)}>Meet MedBot ↗</button></div><Scanner /></section><section className="method"><div className="method-heading"><span className="eyebrow">HOW WE CHECK</span><h2>From your feed<br />to the evidence.</h2></div>
      <div className="method-item"><span className="step-number">01</span><h3>Hear the claim</h3><p>Extract the central health claims from what’s actually said in the video.</p></div>
      <div className="method-item"><span className="step-number">02</span><h3>Find the research</h3><p>Search medical literature and retrieve the passages that matter.</p></div>
      <div className="method-item"><span className="step-number">03</span><h3>Show the evidence</h3><p>A sourced finding, with uncertainty and limitations left in.</p></div>
    </section><TopicExamples /></>}</> : <Suspense fallback={<p>Loading observatory…</p>}><Dashboard /></Suspense>}</main>
    <footer className="site-footer"><b className="footer-brand">medbot<span>.</span></b><span>A research companion.<br />Not personal medical advice.</span><div><span>Search by <b>Elasticsearch</b></span><span>Traced with <b>Sentry</b></span></div></footer></div>
    <div className="reading-progress" aria-hidden="true"><span style={{ transform: `scaleY(${scrollProgress})` }} /></div>
    {how && <Sheet title="From a claim to a clearer picture." onClose={() => setHow(false)}><ol className="how-list"><li><b>Paste a short video.</b><p>A public Instagram Reel or YouTube Short, in English and up to 100 seconds.</p></li><li><b>Follow the evidence.</b><p>MedBot extracts spoken claims, searches Europe PMC and MedlinePlus, and uses Elasticsearch to retrieve passages.</p></li><li><b>Keep the context.</b><p>Read the saved finding, exact quotations and limitations. A video explains one selected claim when generation succeeds.</p></li></ol><p className="notice">This is a bounded search, not a comprehensive medical review. Avoid sharing sensitive personal information.</p></Sheet>}
  </>;
}
