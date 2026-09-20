import type { Detection } from './types';

const HEADLINE: Record<string, string> = {
  AI_ONLY: 'Possible AI-written text', HUMAN_ONLY: 'No strong AI-text signal',
  MIXED: 'Possible mix of human and AI text',
};
const SUBCLASS: Record<string, string> = {
  pure_ai: 'written straight out of a model, not reworked',
  ai_paraphrased: 'put through a paraphrasing or humanising tool afterwards',
  concatenated: 'human and machine passages stitched together',
  polished: 'written by a person, then smoothed over by a model',
};

function Brand() {
  return <div className="gptzero-brand"><b>▣ GPTZero</b><span>TEXT AUTHENTICITY</span></div>;
}

function probabilityLabel(value: number) {
  if (value > 0 && value < 0.001) return '<0.1%';
  if (value < 1 && value > 0.999) return '>99.9%';
  return `${(value * 100).toFixed(1)}%`;
}

export default function Authorship({ value, waiting = false, hasTranscript = false }: { value?: Detection; waiting?: boolean; hasTranscript?: boolean }) {
  const scan = value?.verbatim;
  if (!value || value.status !== 'scored' || !scan) {
    const pending = !value && waiting;
    const note = value?.note?.includes('GPTZERO_API_KEY') ? 'This check has not been enabled yet. Your medical evidence check is unaffected.' : value?.note || 'No authorship reading was taken for this video.';
    return <section className="authorship quiet" aria-label="Script authorship"><Brand />
      <h3>Could the transcript be AI-written?</h3><p className="authorship-intro">We check the transcript automatically with GPTZero when it’s available.</p>
      {pending ? <p className="authorship-state" role="status">{hasTranscript ? 'Waiting for the authorship result' : 'Waiting for the transcript'}</p> : <details className="authorship-state"><summary>Authorship check unavailable</summary><p>{note}</p></details>}
      <p className="authorship-why">AI-written does not mean inaccurate. This check stays separate from the medical evidence.</p>
    </section>;
  }
  const limit = value.script_threshold;
  const scripted = scan.sentences.filter(s => s.generated_prob >= limit).length;
  const total = scan.sentences.length;
  const classification = scan.document_classification || '';
  const headline = HEADLINE[classification] || 'Authorship is inconclusive';
  const tone = classification === 'HUMAN_ONLY' ? 'human' : classification === 'MIXED' ? 'mixed' : classification === 'AI_ONLY' ? 'ai' : 'unknown';
  const probabilities = [
    { label: 'Human', value: scan.human_probability, tone: 'human' },
    { label: 'Mixed', value: scan.mixed_probability, tone: 'mixed' },
    { label: 'AI', value: scan.ai_probability, tone: 'ai' },
  ];
  const hasProbabilities = probabilities.every(p => typeof p.value === 'number' && Number.isFinite(p.value) && p.value >= 0 && p.value <= 1)
    && Math.abs(probabilities.reduce((sum, p) => sum + (p.value ?? 0), 0) - 1) < 0.02;

  return <section className="authorship" aria-label="Script authorship">
    <Brand />
    <div className="authorship-head">
      <div><span className="eyebrow">TRANSCRIPT ANALYSIS</span>
        <h3 className={`authorship-verdict ${tone}`}>{headline}</h3>
        {scan.subclass && SUBCLASS[scan.subclass.predicted_class]
          ? <p className="authorship-subclass">Detector interpretation, not a verified fact: {SUBCLASS[scan.subclass.predicted_class]}
            {scan.subclass.confidence_category
              ? <span className="subtle"> · {scan.subclass.confidence_category} confidence</span> : null}</p>
          : null}</div>
      <span className="authorship-source">{value.provider}
        {value.detector_version ? ` · ${value.detector_version}` : ''}</span>
    </div>

    {hasProbabilities && <div className="authorship-probabilities" aria-label="GPTZero document probabilities">
      <div className="probability-bar" aria-hidden="true">{probabilities.map(p => <span key={p.tone} className={p.tone} style={{ flexGrow: p.value ?? 0 }} />)}</div>
      <div className="probability-labels">{probabilities.map(p => <span key={p.tone}><i className={p.tone} />{p.label} <b>{probabilityLabel(p.value ?? 0)}</b></span>)}</div>
      <p className="detector-confidence">Detector confidence: <b>{scan.confidence_category || 'Not provided'}</b></p>
      {['low', 'medium', 'high'].includes(scan.confidence_category || '') && <meter aria-label="GPTZero classification confidence" min={0} max={3} value={['low', 'medium', 'high'].indexOf(scan.confidence_category!) + 1}>{scan.confidence_category}</meter>}
    </div>}

    {value.prepared_transcript ? <p className="authorship-note"><b>Mock model mode</b>
      This reading was taken over a prepared transcript, not speech from this video.</p> : null}

    {total ? <>
      <p className="authorship-count"><strong>{scripted}</strong> of {total} sentences flagged by the AI-text detector{scan.confidence_category
          ? `, at ${scan.confidence_category} confidence` : ''}.</p>
      <details><summary>See the sentence-level signals</summary><ol className="sentence-map" aria-label="Transcript by sentence">
        {scan.sentences.map((s, i) => <li key={i}
          className={s.generated_prob >= limit ? 'scripted' : 'spontaneous'}>
          <span className="sentence-score" aria-label={`Detector score ${Math.round(s.generated_prob * 100)} out of 100`}>{Math.round(s.generated_prob * 100)}</span>
          <span className="sentence-text">{s.text}</span>
        </li>)}
      </ol>
      <p className="sentence-legend">
        <span className="swatch scripted" /> flagged
        <span className="swatch spontaneous" /> not flagged
        <span className="subtle">UI threshold {Math.round(limit * 100)}/100 · not a truth score</span>
      </p></details>
    </> : <p className="authorship-count">{scan.summary}</p>}

    <div className="hallucination-state"><b>Hallucination check</b><span>Not run</span><p>This GPTZero result checks writing patterns. It has not verified factual claims or citations.</p></div>
    <p className="authorship-why">AI-text signals are not a fact check. It does not change the medical finding.</p>
    <details className="detector-method"><summary>How to read this signal</summary><p>GPTZero estimates authorship patterns in the transcribed speech. It cannot prove who wrote it. Transcription errors and short clips can affect results. The probabilities describe document classes, not the percentage of words written by AI. GPTZero hallucination detection is not enabled.</p><p>Scanned {value.scanned_at ? new Date(value.scanned_at).toLocaleString() : 'at an unknown time'} · {scan.characters} transcript characters.</p></details>

    {value.fillers_removed ? <details className="authorship-removed"><summary>Speech details</summary><p>{value.fillers_removed} filler
      words counted ({Math.round(value.filler_ratio * 100)}% of the speech):
      {' '}{value.removed_examples.map(w => <code key={w}>{w}</code>)}</p></details> : null}
    {value.note ? <p className="authorship-note">{value.note}</p> : null}
  </section>;
}
