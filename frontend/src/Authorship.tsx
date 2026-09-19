import type { Detection, Scan } from './types';

const LABEL: Record<string, string> = {
  human: 'Written by a person', ai: 'Written by a machine', mixed: 'Mixed authorship',
};

function Reading({ scan, caption, hint }: { scan: Scan; caption: string; hint: string }) {
  const percent = scan.ai_probability === null ? null : Math.round(scan.ai_probability * 100);
  return <div className={`reading ${scan.predicted_class || 'unknown'}`}>
    <span className="eyebrow">{caption}</span>
    <strong>{LABEL[scan.predicted_class || ''] || 'No reading'}</strong>
    {percent === null ? null : <span className="reading-figure">{percent}<i>% machine</i></span>}
    <small>{hint}</small>
    <small className="reading-meta">{scan.characters} characters
      {scan.confidence_category ? ` · ${scan.confidence_category} confidence` : ''}</small>
  </div>;
}

export default function Authorship({ value }: { value: Detection }) {
  if (value.status !== 'scored' || !value.verbatim) {
    return <details className="authorship quiet">
      <summary>Authorship check unavailable</summary>
      <p>{value.note || 'No authorship reading was taken for this video.'}</p>
    </details>;
  }
  const { verbatim, cleaned } = value;
  const shifted = cleaned && cleaned.predicted_class !== verbatim.predicted_class;
  return <section className="authorship" aria-label="Script authorship">
    <div className="authorship-head">
      <div><span className="eyebrow">WHO WROTE THE SCRIPT</span>
        <h3>{shifted ? 'The delivery and the script disagree' : 'Two readings of the same speech'}</h3></div>
      <span className="authorship-source">{value.provider}
        {value.detector_version ? ` · ${value.detector_version}` : ''}</span>
    </div>
    {value.prepared_transcript ? <p className="authorship-note"><b>Mock model mode</b>
      This reading was taken over a prepared transcript, not speech from this video.</p> : null}
    <div className="readings">
      <Reading scan={verbatim} caption="AS SPOKEN" hint="Everything that was said, disfluencies included." />
      {cleaned ? <Reading scan={cleaned} caption="SCRIPT ONLY"
        hint={`${value.fillers_removed} filler words removed (${Math.round(value.filler_ratio * 100)}% of the speech).`} />
        : null}
    </div>
    <p className="authorship-why">Spoken delivery reads as human whoever wrote the words, so the script is
      read a second time with the fillers taken out. Removal is imperfect, which is why the spoken reading
      stays on screen. This measures authorship, not whether the claims are true.</p>
    {value.removed_examples.length ? <p className="authorship-removed">Removed:
      {' '}{value.removed_examples.map(w => <code key={w}>{w}</code>)}</p> : null}
    {value.note ? <p className="authorship-note">{value.note}</p> : null}
    {cleaned?.top_sentences.length ? <details className="limitations">
      <summary>Sentences the detector scored highest</summary>
      <ul>{cleaned.top_sentences.map((s, i) => <li key={i}>
        <b>{Math.round(s.generated_prob * 100)}%</b> {s.text}</li>)}</ul></details> : null}
  </section>;
}
