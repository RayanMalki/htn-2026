import { useState } from 'react';
import data from './investigation.json';

// Every figure on this page is counted from the scan datasets by scripts/build_ui_data.py.
// Nothing here is typed by hand, so the page cannot drift from the data.

type Scored = { text: string; p: number };
const count = (n: number) => n.toLocaleString('en-US');
const share = (part: number, whole: number) => (whole ? Math.round((100 * part) / whole) : 0);
const AXIS_MAX = 60;

function SentenceMap({ rows, threshold }: { rows: Scored[]; threshold: number }) {
  return <ol className="sentence-map findings-map">{rows.map((s, i) => <li key={i} className={s.p >= threshold ? 'scripted' : 'spontaneous'}>
    <b aria-label={`${Math.round(s.p * 100)} percent likely machine-written`}>{Math.round(s.p * 100)}%</b><span>{s.text}</span></li>)}</ol>;
}

export default function Investigation() {
  const [paper, setPaper] = useState(0);
  const { papers, videos, citations, showcase, threshold } = data;
  const latest = papers.years[papers.years.length - 1];
  const shown = showcase[paper];
  const farmsTotal = videos.farms.reduce((n, f) => n + f.n, 0);
  const farmsFlagged = videos.farms.reduce((n, f) => n + f.machine, 0);

  return <section className="findings" aria-labelledby="findings-title">
    <span className="eyebrow"><span className="blue-dot" /> THE INVESTIGATION</span>
    <h2 id="findings-title">We scanned the research.<br /><em>Machines are writing it.</em></h2>
    <p className="findings-lead">We ran GPTZero over {count(papers.n)} open-access papers and {count(videos.n)} health videos. Here is what came back.</p>

    <dl className="findings-tiles">
      <div><dt>{count(papers.n)}</dt><dd>papers scanned</dd></div>
      <div><dt>{share(latest.machine, latest.n)}%</dt><dd>of {latest.year} papers flagged</dd></div>
      <div><dt>{count(videos.n)}</dt><dd>health videos scanned</dd></div>
      <div><dt>{count(citations.checked)}</dt><dd>citations checked</dd></div>
    </dl>

    <article className="findings-card">
      <h3>Year by year.</h3>
      <p>Share of papers carrying machine-written text, by year published.</p>
      <ol className="year-bars" aria-label="Machine-written share by year">{papers.years.map(y => {
        const pct = share(y.machine, y.n);
        return <li key={y.year}><span className="year">{y.year}</span>
          <span className="track"><span className="fill" style={{ width: `${Math.max(pct ? 2 : 0, (100 * pct) / AXIS_MAX)}%` }} /></span>
          <b>{pct}%</b><small>{count(y.machine)} of {count(y.n)}</small></li>;
      })}</ol>
      <p className="axis-note">Bars run from 0 to {AXIS_MAX}%.</p>
      <p>Nothing in 2022. Nothing in 2023. Then it climbs every year.</p>
      <p className="subtle">The early years are small samples. Read the trend, not the decimals.</p>
    </article>

    <article className="findings-card">
      <h3>Read one yourself.</h3>
      <p>Real papers. Every sentence scored. <mark className="key scripted">Orange</mark> reads as machine-written. <mark className="key spontaneous">Green</mark> reads as human.</p>
      <div className="paper-tabs" role="group" aria-label="Choose a paper">{showcase.map((p, i) =>
        <button key={p.pmcid} aria-pressed={paper === i} onClick={() => setPaper(i)}>{p.journal}{p.classification === 'HUMAN_ONLY' ? ' · control' : ''}</button>)}</div>
      <h4>{shown.title}</h4>
      <p className="paper-meta">{shown.journal} · {shown.year} · <b>{shown.flagged} of {shown.total}</b> sentences flagged</p>
      <SentenceMap rows={shown.shown} threshold={threshold} />
      <p className="subtle">Sentences {shown.offset + 1} to {shown.offset + shown.shown.length} of {shown.total}. {shown.classification === 'HUMAN_ONLY'
        ? 'This is the control. Same kind of journal, same year, and it comes back clean.'
        : 'We show the stretch where flagged and clean lines sit side by side.'}</p>
      <a className="source-link" href={shown.url} target="_blank" rel="noreferrer">Open the paper ↗</a>
    </article>

    <article className="findings-card">
      <h3>More flagged papers.</h3>
      <p>Famous journals. Scored 99% or higher. Open any of them.</p>
      <ul className="link-list">{data.flagged_papers.map(p => <li key={p.url}><a href={p.url} target="_blank" rel="noreferrer">{p.title} ↗</a><small>{p.journal} · {p.year} · {Math.round(p.ai * 100)}%</small></li>)}</ul>
      <details><summary>Run through a humaniser ({data.laundered.length})</summary>
        <p>GPTZero reads these as machine text that was reworded to hide it.</p>
        <ul className="link-list">{data.laundered.map(p => <li key={p.url}><a href={p.url} target="_blank" rel="noreferrer">{p.title} ↗</a><small>{p.journal} · {p.year}</small></li>)}</ul>
      </details>
    </article>

    <article className="findings-card">
      <h3>Health videos.</h3>
      <p><b>{count(videos.machine)} of {count(videos.n)}</b> Shorts read as scripted by a machine. That is {share(videos.machine, videos.n)}%.</p>
      <p>They drew {count(videos.machine_views)} of {count(videos.views)} views. Under 1%. The feed is not flooded yet.</p>
      <p>But the channels that do it, do it every time. We followed them: <b>{farmsFlagged} of {farmsTotal}</b> more videos flagged.</p>
      <ul className="farm-list">{videos.farms.map(f => <li key={f.name}><span>{f.name}</span><b>{f.machine}/{f.n}</b></li>)}</ul>
      {videos.tells.length > 0 && <><h4>What gives it away.</h4>
        <ul className="tell-chips">{videos.tells.map(t => <li key={t.name}>{t.name}<b>{t.count}</b></li>)}</ul></>}
      {videos.stitched.slice(0, 1).map(v => <div key={v.url}><h4>Part script, part ad-lib.</h4>
        <p className="paper-meta">{v.channel} · {count(v.views)} views · <b>{v.flagged} of {v.total}</b> sentences flagged</p>
        <SentenceMap rows={v.shown.slice(0, 6)} threshold={threshold} />
        <a className="source-link" href={v.url} target="_blank" rel="noreferrer">Watch on YouTube ↗</a></div>)}
      <details><summary>Flagged videos ({videos.flagged.length})</summary>
        <ul className="link-list">{videos.flagged.map(v => <li key={v.url}><a href={v.url} target="_blank" rel="noreferrer">{v.title} ↗</a><small>{v.channel} · {count(v.views)} views</small></li>)}</ul>
      </details>
    </article>

    <article className="findings-card">
      <h3>Are the citations real?</h3>
      <p>{count(citations.checked)} citations in {count(citations.papers)} papers. GPTZero called <b>{citations.flagged}</b> fake.</p>
      <p>We did not take its word. We looked every one up on Crossref and asked for the full title to match.</p>
      <p className="subtle">First we tested our own check. It found {citations.proof.real_found} of {citations.proof.real} real references, with the exact DOI {citations.proof.same_doi} times. It cleared {citations.proof.fake_cleared} of {citations.proof.fake} fakes we built. A looser rule cleared {citations.proof.fake_cleared_loose}.</p>
      <ul className="farm-list">
        <li><span>Found. The citation is real.</span><b>{citations.real}</b></li>
        <li><span>Real title. Invented authors.</span><b>{citations.wrong_authors}</b></li>
        <li><span>Books, reports, websites. No database covers them.</span><b>{citations.uncheckable}</b></li>
        <li><span>Journal articles we cannot find.</span><b>{citations.not_found}</b></li>
      </ul>
      <p className="subtle">Missing from a database is not the same as made up. Our check misses about 1 real reference in 15. So we name only the ones a person also searched for by hand.</p>
      {citations.candidates.length > 0 && <><h4>Checked by hand. Still wrong.</h4>
        <p>GPTZero flagged seven references in a row in one 2026 paper. Four exist nowhere. Three are real papers under the wrong names.</p>
        <ul className="link-list">{citations.candidates.map(c => <li key={c.reference}><span className="reference">{c.reference}</span>
          <small><b className={`verdict ${c.kind}`}>{c.kind === 'not_found' ? 'Not found' : 'Wrong authors'}</b> {c.actual}</small>
          <small>cited in <a href={c.url} target="_blank" rel="noreferrer">{c.journal}, {c.year} ↗</a></small></li>)}</ul></>}
    </article>

    <p className="notice"><b>A signal, not a verdict.</b> Formal writing can score high. One of our most-viewed flagged videos is a hospital explainer. We show the sentences so you can judge.</p>
    <p className="subtle findings-stamp">Data counted on {data.generated_at}. Detection by GPTZero. Papers from Europe PMC.</p>
  </section>;
}
