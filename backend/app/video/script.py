"""Build a one-claim script only from validated saved findings and exact excerpts."""
import re
from pathlib import Path

from app.schemas import Claim, Passage, Verdict, validate_verdict
from app.video.plan import Badge, Card, Evidence, Finding, RenderPlan, Scene

LABELS = {'supports': 'Supported by retrieved evidence', 'contradicts': 'Contradicted by retrieved evidence',
          'uncertain': 'Evidence is uncertain'}
WORDS_PER_SECOND = 2.6


class ScriptBudgetError(ValueError):
    pass


def eligible_claims(case: dict):
    result = case['result']
    if result.get('model_mode') != 'live':
        raise ValueError('Narrated medical videos require live analysis')
    expected = result.get('analysis', {}).get('claims', [])
    if not expected:
        raise ValueError('No assessed claims to render')
    claims = []
    for raw in expected:
        claim = Claim.model_validate(raw)
        item = result.get('claims', {}).get(claim.id, {})
        if item.get('status') != 'complete' or not item.get('verdict'):
            raise ValueError('All assessed claims must have validated complete verdicts before rendering')
        passages = [Passage.model_validate(p) for p in item.get('evidence', [])]
        verdict = validate_verdict(Verdict.model_validate(item['verdict']), passages)
        claims.append((claim, verdict, passages))
    return sorted(claims, key=lambda row: (row[0].start, row[0].id))


def excerpt(quote: str) -> str:
    if len(quote) <= 500:
        return quote
    # Display a complete sentence that is an exact slice. Never clip a qualification mid-sentence.
    sentences = re.split(r'(?<=[.!?])\s+', quote)
    return next((s for s in sentences if 20 <= len(s) <= 500), '')


def build_plan(case: dict, out_dir: Path, *, source_clip: str | None = None) -> RenderPlan:
    assessed = eligible_claims(case)
    claim, verdict, passages = next((row for row in assessed if row[1].label == 'contradicts'), assessed[0])
    by_id = {p.id: p for p in passages}
    refs = []
    for citation in verdict.citations:
        p = by_id[citation.passage_id]
        refs.append(Evidence(id=f'E{len(refs) + 1}', claim_id=claim.id, passage_id=p.id, paper_id=p.paper_id,
                             paper=p.title, provider=p.provider, source_kind=p.source_kind, access=p.access_type,
                             quote=citation.quote, url=p.source_url))
    papers = {e.paper_id for e in refs if e.source_kind == 'research_paper'}
    summaries = {e.paper_id for e in refs if e.source_kind != 'research_paper'}
    finding = Finding(label=verdict.label, sentence=verdict.explanation, limitations=verdict.limitations,
                      papers=len(papers), summaries=len(summaries))
    plan = RenderPlan(case_id=case['id'], selected_claim_id=claim.id, claim=claim.text,
                      evidence=refs, finding=finding)
    # Use the whole timestamped claim only when it fits the short opening. Otherwise
    # use the labeled claim card; a fragment could reverse the speaker's meaning.
    if source_clip and Path(source_clip).is_file() and 0 < claim.end - claim.start <= 8:
        plan.source_clip = str(Path(source_clip).resolve())
        plan.source_start = claim.start
        plan.source_duration = claim.end - claim.start
        segments = case['result'].get('analysis', {}).get('transcript', [])
        plan.source_transcript = ' '.join(s['text'] for s in segments
                                         if s['start'] >= claim.start and s['end'] <= claim.end)
    t = 0.0

    def add(kind, narration, card, duration=None, transition='fade'):
        nonlocal t
        seconds = duration if duration is not None else max(1.5, len(narration.split()) / WORDS_PER_SECOND)
        plan.scenes.append(Scene(kind=kind, start=t, end=t + seconds, narration=narration,
                                 card=card, transition_in=transition))
        t += seconds

    if plan.source_clip:
        add('clip', '', Card(kind='clip', title='Original claim excerpt'), plan.source_duration, 'none')
    add('claim', f'This voice is AI generated. We checked one claim: {claim.text}',
        Card(kind='claim', eyebrow='SELECTED CLAIM', title=claim.text,
             footer='One claim assessed here. All findings are linked in the app.'))
    seen = set()
    for ev in refs:
        quote = excerpt(ev.quote)
        if ev.paper_id in seen or not quote or len(seen) >= 2:
            continue
        seen.add(ev.paper_id)
        access = {'full_text': 'Full text available', 'abstract_only': 'Abstract only',
                  'summary': 'Health summary'}[ev.access]
        add('paper', '', Card(kind='paper', eyebrow='SOURCE EXCERPT • NOT A PAGE CAPTURE', title=ev.paper,
                             body=[quote], highlight=quote, evidence_id=ev.id,
                             badges=[Badge(label='Source', value=ev.source_kind.replace('_', ' ')),
                                     Badge(label='Access', value=access)],
                             footer=f'{ev.id} • {ev.paper_id} • Full quotation and link in sources'),
            duration=4, transition='smoothup')
    add('finding', f'{LABELS[verdict.label]}. {verdict.explanation}',
        Card(kind='finding', eyebrow=LABELS[verdict.label], title=verdict.explanation,
             footer=f'{len(papers)} unique papers; {len(summaries)} health summaries cited.'), transition='circleopen')
    for limitation in verdict.limitations:
        add('finding', limitation, Card(kind='finding', eyebrow='LIMITATION', title=limitation))
    close = 'A limited search, not personalized medical advice. Read the linked sources and all findings in the app.'
    omitted = case['result'].get('analysis', {}).get('omitted_claims', 0)
    if omitted:
        close += (f' {omitted} additional claim was not assessed.' if omitted == 1
                  else f' {omitted} additional claims were not assessed.')
    add('close', close, Card(kind='close', eyebrow='HYPECHECK', title='Read the evidence in context.',
                            body=[close]), transition='fadeblack')
    if t > 60:
        # Evidence reading time is optional; medical wording and limitations are not.
        plan.scenes = [s for s in plan.scenes if s.kind != 'paper']
        retime(plan)
    if plan.duration > 60:
        raise ScriptBudgetError('Essential findings and limitations exceed the 60-second script budget.')
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    plan.save(Path(out_dir) / 'plan.json')
    return plan


def retime(plan):
    t = 0.0
    for scene in plan.scenes:
        length = scene.end - scene.start
        scene.start, scene.end = t, t + length
        t += length
