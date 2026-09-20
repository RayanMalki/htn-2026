import { lazy, Suspense, useEffect, useState, type FormEvent } from 'react';
import { api, finished, seconds } from './api';
import Evidence from './Evidence';
import type { Case, ClaimResult } from './types';

const Dashboard = lazy(() => import('./Dashboard'));
const stages = ['queued', 'downloading', 'transcribing', 'researching', 'judging', 'rendering', 'complete'];
const labels: Record<string, string> = { queued: 'Queued', downloading: 'Reading the video', rendering: 'Creating your video', transcribing: 'Finding spoken claims', researching: 'Searching the literature', judging: 'Checking the evidence', complete: 'Analysis complete', awaiting_upload: 'Video upload needed', incomplete: 'Analysis incomplete', no_claims: 'No spoken medical claims' };

function PulseLogo() {
  return <svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M3 17h6l4-10 6 19 4-9h6" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

function CaseView({ value, onUpdate }: { value: Case; onUpdate: (c: Case) => void }) {
  const [tick, setTick] = useState(Date.now());
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [retrying, setRetrying] = useState(false);
  useEffect(() => {
    if (finished(value.status) || value.status === 'awaiting_upload') return;
    const timer = setInterval(() => setTick(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [value.status]);
  const elapsed = finished(value.status) || value.status === 'awaiting_upload'
    ? value.result.timings?.total || 0
    : (value.result.timings?.total || 0) + Math.max(0, (tick - Date.parse(value.result.submitted_at || value.created_at)) / 1000);
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
    <div className="section-heading"><div><span className="eyebrow">YOUR EVIDENCE TRAIL</span><h2>{labels[value.status]}</h2></div>
      <div className="elapsed"><span className={finished(value.status) ? 'status-dot' : 'status-dot live'} />
        {seconds(elapsed)}<span className="subtle"> / 90s target</span></div></div>
    <a className="source-link" href={value.source_url} target="_blank" rel="noreferrer">Original video ↗</a>
    <ol className="progress-stages" aria-label="Pipeline progress">{stages.slice(1).map((s, i) => <li key={s}
      className={`${activeIndex > i + 1 || value.status === 'complete' ? 'done' : ''} ${activeIndex === i + 1 ? 'active' : ''}`}>
      <span>{activeIndex > i + 1 || value.status === 'complete' ? '✓' : i + 1}</span>{['Read video', 'Extract claims', 'Find research', 'Check evidence', 'Create video', 'Results'][i]}</li>)}</ol>
    {value.result.model_mode === 'mock' ? <div className="notice"><b>Mock model mode</b> The claim and judgment are prepared inputs. Literature retrieval is real when configured. This is not an analysis of the submitted video.</div> : null}
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
    {value.result.video?.status === 'ready' ? <section className="generated-video" aria-label="Generated fact-check video">
      <div><span className="eyebrow">YOUR FACT-CHECK VIDEO</span><h3>Evidence, ready to watch.</h3>
        <p>AI-generated narration. Captions have approximate timing. Sources and limitations are included.</p>
        <a className="button" href={`/api/cases/${value.id}/video?download=true`}>Download MP4 ↓</a>{' '}
        <a className="button secondary" href={`/api/cases/${value.id}/video/sources`}>Video sources ↓</a>
      </div>
      <video controls playsInline preload="metadata" src={`/api/cases/${value.id}/video`}>
        <track kind="captions" src={`/api/cases/${value.id}/video/captions`} srcLang="en" label="English" default />
      </video>
    </section> : null}
    {value.result.video?.status === 'failed' ? <p className="error">{value.result.video.error}</p> : null}
    {value.status === 'incomplete' || (value.status === 'complete' && !value.result.video) ?
      <button className="button secondary" disabled={retrying} onClick={async () => {
        setRetrying(true); setError('');
        try { await api<Case>(`/api/cases/${value.id}/retry`, { method: 'POST' }); window.location.reload(); }
        catch (e) { setError((e as Error).message); setRetrying(false); }
      }}>{retrying ? 'Resuming…' : 'Retry analysis and create video'}</button> : null}
    {value.result.outcome ? <div className="notice">{value.result.outcome}</div> : null}
    {items.length ? <div className="claims-list">{items.map((item, i) => <Evidence key={item.claim.id} item={item} index={i} mock={value.result.model_mode === 'mock'} />)}</div> : null}
    {value.result.analysis?.omitted_claims ? <p className="notice">{value.result.analysis.omitted_claims} additional claim(s) were omitted from this bounded analysis.</p> : null}
    {value.result.analysis?.transcript.length ? <details className="transcript"><summary>Read the transcript</summary>
      {value.result.analysis.transcript.map((s, i) => <p key={i}><span>{Math.floor(s.start)}s</span>{s.text}</p>)}</details> : null}
    {finished(value.status) ? <div className="result-footer"><p>Evidence is contextual. This search is limited and is not personal medical advice.</p>
      <a className="button secondary" href={`/api/cases/${value.id}/replay`}>Download offline replay ↓</a></div> : null}
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

  useEffect(() => { void api<{ model_mode: string }>('/api/config').then(setConfig).catch(() => setConnection('Backend unavailable')); }, []);
  useEffect(() => {
    if (!caseId) return;
    let disposed = false;
    let source: EventSource | null = null;
    const controller = new AbortController();
    void api<Case>(`/api/cases/${caseId}`, { signal: controller.signal }).then(c => {
      if (disposed) return;
      setCase(c);
      if (finished(c.status)) return;
      source = new EventSource(`/api/cases/${caseId}/events?after=${c.sequence}`);
      source.addEventListener('case', event => {
        try { const incoming = JSON.parse((event as MessageEvent).data) as Case;
          setCase(previous => !previous || incoming.sequence >= previous.sequence ? incoming : previous);
          setConnection('');
        } catch { setConnection('Could not read an update. Reconnecting…'); }
      });
      source.addEventListener('end', () => { source?.close(); setConnection(''); });
      source.onopen = () => setConnection('');
      source.onerror = () => setConnection('Connection interrupted. Reconnecting to saved progress…');
    }).catch(e => { if (!disposed) setError(e.message); });
    return () => { disposed = true; controller.abort(); source?.close(); };
  }, [caseId]);

  async function submit(event: FormEvent) {
    event.preventDefault(); setError(''); setSubmitting(true);
    try {
      const c = await api<Case>('/api/cases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source_url: url }) });
      setCase(c); setCaseId(c.id); history.replaceState(null, '', `?case=${c.id}`);
    } catch (e) { setError((e as Error).message); }
    finally { setSubmitting(false); }
  }

  return <><header className="site-header"><a href="/" className="brand"><span className="brand-mark"><PulseLogo /></span>hypecheck<span className="brand-period">.</span></a>
    <nav aria-label="Main navigation"><button className={tab === 'check' ? 'selected' : ''} onClick={() => setTab('check')}>Check a Reel</button>
      <button className={tab === 'observatory' ? 'selected' : ''} onClick={() => setTab('observatory')}>Observatory</button></nav>
    <span className="edition">HTN 2026 <span> / </span> Research preview</span></header>
    <main>{tab === 'check' ? <><section className={`hero ${caseValue ? 'compact' : ''}`}>
      <div className="hero-copy"><span className="eyebrow"><span className="tiny-star">✳</span> HEALTH CLAIMS, WITH RECEIPTS</span>
        <h1>Your feed moves fast.<br /><em>Evidence matters.</em></h1>
        <p className="hero-description">Follow a health claim from an Instagram Reel or YouTube Short to the medical research. See what the evidence says—and exactly where it says it.</p>
        <form onSubmit={submit} className="link-form"><label htmlFor="reel-url">Start with an Instagram Reel or YouTube Short</label>
          <div className="input-row"><span className="link-icon" aria-hidden="true">↗</span><input id="reel-url" type="url" required placeholder="https://www.youtube.com/shorts/…" value={url} onChange={e => setUrl(e.target.value)} />
            <button type="submit" disabled={submitting}>{submitting ? 'Starting…' : 'Check the evidence'}<span aria-hidden="true">↗</span></button></div>
          <div className="form-caption"><span>Spoken English · Up to 100 seconds</span><span>3 claims. Sources included.</span></div>
        </form>{error ? <p className="error" role="alert">{error}</p> : null}
        <div className="mode-line"><span className="status-dot" />{config ? config.model_mode === 'mock' ? 'Infrastructure preview · mock AI adapters' : 'Live model pipeline' : 'Connecting to pipeline…'}
          <span className="mode-divider" />No account required</div>
      </div>
      {!caseValue ? <div className="research-illustration" aria-label="Video to claim to research workflow">
        <div className="orbit orbit-one" /><div className="orbit orbit-two" />
        <div className="mini-reel"><span className="eyebrow">FROM YOUR FEED</span><div className="reel-wave"><i /><i /><i /><i /><i /><i /><i /><i /><i /></div><span>One spoken claim</span><div className="play-symbol">▶</div></div>
        <div className="connector connector-one" /><span className="scan-dot">✦</span>
        <div className="mini-paper"><div className="mini-paper-head"><span>RESEARCH, IN CONTEXT</span><span>↗</span></div><h3>Go beyond<br />the headline.</h3><div className="paper-line long" /><div className="paper-highlight" /><div className="paper-line" /><div className="paper-line long" /><div className="paper-line short" /><div className="paper-bottom">Original source <span>✓</span></div></div>
        <span className="illustration-caption">A clear trail from claim to source.</span>
      </div> : null}
    </section>
    {connection ? <p className="notice" role="status">{connection}</p> : null}
    {caseValue ? <CaseView value={caseValue} onUpdate={setCase} /> : <section className="method"><div className="method-heading"><span className="eyebrow">HOW WE CHECK</span><h2>Less guesswork.<br />More context.</h2></div>
      <div className="method-item"><span className="step-number">01</span><h3>Hear the claim</h3><p>Extract the central health claims from what’s actually said in the video.</p></div>
      <div className="method-item"><span className="step-number">02</span><h3>Find the research</h3><p>Search medical literature and retrieve the passages that matter.</p></div>
      <div className="method-item"><span className="step-number">03</span><h3>Show the evidence</h3><p>A sourced finding, with uncertainty and limitations left in.</p></div>
    </section>}</> : <Suspense fallback={<p>Loading observatory…</p>}><Dashboard /></Suspense>}</main>
    <footer className="site-footer"><span>Built for curiosity. Grounded in research.</span><div><span>Search by <b>Elasticsearch</b></span><span>Traced with <b>Sentry</b></span></div><span>Hack the North 2026</span></footer></>;
}
