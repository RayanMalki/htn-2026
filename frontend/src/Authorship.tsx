import type { Detection } from './types';

const HEADLINE: Record<string, string> = {
  AI_ONLY: 'Read from a script', HUMAN_ONLY: "The creator's own words",
  MIXED: 'Partly read from a script',
};

export default function Authorship({ value }: { value: Detection }) {
  const scan = value.verbatim;
  if (value.status !== 'scored' || !scan) {
    return <details className="authorship quiet">
      <summary>Authorship check unavailable</summary>
      <p>{value.note || 'No authorship reading was taken for this video.'}</p>
    </details>;
  }
  const limit = value.script_threshold;
  const scripted = scan.sentences.filter(s => s.generated_prob >= limit).length;
  const total = scan.sentences.length;
  const classification = scan.document_classification || '';
  const headline = HEADLINE[classification]
    || (scan.ai_probability !== null && scan.ai_probability >= limit ? HEADLINE.AI_ONLY : HEADLINE.HUMAN_ONLY);
  const tone = classification === 'HUMAN_ONLY' ? 'human' : classification === 'MIXED' ? 'mixed' : 'ai';

  return <section className="authorship" aria-label="Script authorship">
    <div className="authorship-head">
      <div><span className="eyebrow">WHO WROTE THIS SCRIPT</span>
        <h3 className={`authorship-verdict ${tone}`}>{headline}</h3></div>
      <span className="authorship-source">{value.provider}
        {value.detector_version ? ` · ${value.detector_version}` : ''}</span>
    </div>

    {value.prepared_transcript ? <p className="authorship-note"><b>Mock model mode</b>
      This reading was taken over a prepared transcript, not speech from this video.</p> : null}

    {total ? <>
      <p className="authorship-count"><strong>{scripted}</strong> of {total} sentences read as
        written rather than spoken off the cuff{scan.confidence_category
          ? `, at ${scan.confidence_category} confidence` : ''}.</p>
      <ol className="sentence-map" aria-label="Transcript by sentence">
        {scan.sentences.map((s, i) => <li key={i}
          className={s.generated_prob >= limit ? 'scripted' : 'spontaneous'}>
          <span className="sentence-score">{Math.round(s.generated_prob * 100)}</span>
          <span className="sentence-text">{s.text}</span>
        </li>)}
      </ol>
      <p className="sentence-legend">
        <span className="swatch scripted" /> read from a script
        <span className="swatch spontaneous" /> the creator's own words
        <span className="subtle">threshold {Math.round(limit * 100)}</span>
      </p>
    </> : <p className="authorship-count">{scan.summary}</p>}

    <p className="authorship-why">This measures how the words were produced, not whether the claims
      are true. Speech that was genuinely improvised scores low even when it is wrong, and text
      reworded from a model still scores high. Detectors are trained mostly on written prose, so
      treat a single reading as a signal rather than a finding about a person.</p>

    {value.fillers_removed ? <p className="authorship-removed">{value.fillers_removed} filler
      words counted ({Math.round(value.filler_ratio * 100)}% of the speech):
      {' '}{value.removed_examples.map(w => <code key={w}>{w}</code>)}</p> : null}
    {value.note ? <p className="authorship-note">{value.note}</p> : null}
  </section>;
}
