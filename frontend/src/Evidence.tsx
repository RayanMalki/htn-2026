import type { ClaimResult, Passage } from './types';

function safeSource(url: string) {
  try { const parsed = new URL(url); return parsed.protocol === 'https:' && ['europepmc.org', 'medlineplus.gov', 'www.medlineplus.gov'].includes(parsed.hostname) ? url : undefined; }
  catch { return undefined; }
}

function Paper({ passage, quote }: { passage: Passage; quote?: string }) {
  const text = quote || passage.text;
  const position = passage.context.indexOf(text, passage.start);
  const before = position >= 0 ? passage.context.slice(Math.max(0, position - 180), position) : '';
  const after = position >= 0 ? passage.context.slice(position + text.length, position + text.length + 180) : '';
  return <details className="paper">
    <summary>
      <span className="paper-icon" aria-hidden="true">▤</span>
      <span className="paper-title">{passage.title}<span className="paper-meta">
        {passage.published?.slice(0, 4) || 'Date unknown'} <span>·</span> {passage.study_types.slice(0, 2).join(', ') || 'Study type unknown'}
      </span></span>
      <span className={`access ${passage.access_type}`}>{({ full_text: 'Full text', abstract_only: 'Abstract only', summary: 'Health summary' })[passage.access_type]}</span>
      <span className="expand" aria-hidden="true">+</span>
    </summary>
    <div className="paper-body"><span className="eyebrow">{passage.section} · exact source passage</span>
      <blockquote>{position > 180 ? '…' : ''}{before}<mark>{text}</mark>{after}{position + text.length + 180 < passage.context.length ? '…' : ''}</blockquote>
      <a href={safeSource(passage.source_url)} target="_blank" rel="noreferrer">{passage.access_type === 'summary' ? 'Read the health topic' : 'Read the original paper'} ↗</a>
      <small>Offsets {passage.start}–{passage.end} in the stored source paragraph. {quote ? 'Highlighted quotation cited in the verdict.' : 'Retrieved passage; relevance alone does not establish support.'}</small>
    </div>
  </details>;
}

export default function Evidence({ item, index, mock }: { item: ClaimResult; index: number; mock: boolean }) {
  const verdict = item.verdict;
  const label = mock && verdict ? 'Prepared judgment' : verdict ? ({ supports: 'Supported by retrieved evidence', contradicts: 'Contradicted by retrieved evidence', uncertain: 'Evidence is uncertain' })[verdict.label] : item.status === 'incomplete' ? 'Analysis incomplete' : 'Research in progress';
  return <article className="claim-card">
    <div className="claim-top"><span className="eyebrow">CLAIM {String(index + 1).padStart(2, '0')}</span>
      <span className="timestamp">{Math.floor(item.claim.start)}–{Math.ceil(item.claim.end)} sec</span></div>
    <h3>{item.claim.text}</h3>
    <div className={`verdict ${mock ? 'uncertain' : verdict?.label || 'pending'}`}><span className="verdict-dot" />{label}</div>
    {verdict ? <p className="finding">{verdict.explanation}</p> : <p className="finding">{item.error || 'Discovering papers and checking their relevance to this claim.'}</p>}
    {item.provenance ? <div className="retrieval-line">
      <span>{item.provenance.sources_found ?? item.provenance.papers_found ?? 0} sources discovered</span><span>·</span>
      {item.provenance.retrieval_mode ? <span className={item.provenance.retrieval_mode === 'keyword_only' ? 'degraded' : ''}>
        {item.provenance.retrieval_mode === 'hybrid' ? 'Elastic hybrid retrieval' : 'Keyword only · degraded retrieval'}</span> : <span>Retrieval not completed</span>}
    </div> : null}
    {item.provenance?.provider_failures?.map(failure => <p className="degraded" key={failure.provider}>
      {failure.provider} unavailable. {failure.provider === 'Europe PMC'
        ? 'Required literature research failed; no verdict was assigned.'
        : 'Supplemental health summaries could not be checked.'}
    </p>)}
    {item.evidence?.length ? <div className="papers">{item.evidence.map(p => <Paper key={p.id} passage={p}
      quote={verdict?.citations.find(c => c.passage_id === p.id)?.quote} />)}</div> : null}
    {item.status === 'incomplete' && item.discovered_sources?.length ? <details className="limitations"><summary>Sources discovered before the interruption</summary>
      <p>These sources were discovered but not successfully ranked or assessed. No verdict is based on them.</p>
      <ul>{item.discovered_sources.map(p => <li key={p.source_url}><a href={safeSource(p.source_url)} target="_blank" rel="noreferrer">{p.title} ↗</a></li>)}</ul></details> : null}
    {verdict?.limitations.length ? <details className="limitations"><summary>Limitations of this finding</summary>
      <ul>{verdict.limitations.map((v, i) => <li key={i}>{v}</li>)}</ul></details> : null}
    {item.provenance ? <details className="provenance"><summary>Research trail</summary><p>{item.provenance.provider} · {item.provenance.searched_at}</p>
      {(item.provenance.providers || [item.provenance]).map(provider => <p key={provider.provider}>
        {provider.provider}: <code>{provider.query}</code></p>)}<p>{item.provenance.cache_hits ?? 0} papers reused from the source cache.</p></details> : null}
  </article>;
}
