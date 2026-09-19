"""
Script stage: a finished case in, a RenderPlan with scenes, evidence and finding out.

The shape is a stitch. The original clip plays, the claim freezes on screen, then
one scene per paper that carries the verdict with its exact quoted sentence, then
the finding, then a close. The narration is scientific but argumentative against
the video, never sneering, and it gives the creator credit first wherever the
evidence supports them, before it corrects them. That order is what makes a
correction land instead of reading as a takedown.

Every factual narration sentence names the evidence it rests on, like [E3]. Those
tags are for the page and the citation checker, the voice stage strips them before
speaking. No model is called here, so this needs no key: the words come from
templates over the stored verdict, its verbatim citations and the passages behind
them. Scene times are estimates from word count at about 2.6 words a second, and
the voice stage replaces them with the real audio.

The stored case shape this reads is what pipeline.py writes: result["claims"] is a
dict keyed by claim id, each with "claim", "evidence" (Passage dumps), "verdict"
(label, explanation, citations of passage_id plus quote, limitations) and "status".
"""

from __future__ import annotations

import re
from pathlib import Path

from app.video.plan import Badge, Card, Evidence, Finding, RenderPlan, Scene

WORDS_PER_SECOND = 2.6
MIN_SECONDS = 45.0
MAX_SECONDS = 60.0
CLIP_SECONDS = 4.0          # the original plays before the freeze
MAX_PAPER_SCENES = 3        # keeps the whole thing inside a minute

# Europe PMC publication types, best design first. The first match wins.
DESIGN_RANK = [
    ("Meta-Analysis", "Meta-analysis"),
    ("Systematic Review", "Systematic review"),
    ("Randomized Controlled Trial", "Randomized controlled trial"),
    ("Clinical Trial", "Clinical trial"),
    ("Observational Study", "Observational study"),
    ("Comparative Study", "Comparative study"),
    ("Review", "Review"),
    ("Case Reports", "Case report"),
]

STANCE_FROM_VERDICT = {"supports": "supports", "contradicts": "contradicts", "uncertain": "unclear"}
ACCESS_FROM_PASSAGE = {"full_text": "full_text", "abstract_only": "abstract_only", "summary": "abstract_only"}

_PEOPLE = re.compile(
    r"\b(\d{1,3}(?:,\d{3})+|\d+)\s+(adults|participants|patients|people|subjects|women|men|children|"
    r"volunteers|individuals)\b", re.IGNORECASE)
_N_EQUALS = re.compile(r"\bn\s*=\s*(\d[\d,]*)", re.IGNORECASE)
_YEAR = re.compile(r"(19|20)\d{2}")


def _year(published: str | None) -> int | None:
    match = _YEAR.search(published or "")
    return int(match.group(0)) if match else None


def _design(study_types: list[str]) -> str | None:
    lowered = [t.lower() for t in study_types or []]
    for key, label in DESIGN_RANK:
        if any(key.lower() in t for t in lowered):
            return label
    return study_types[0][:60] if study_types else None


def _people(text: str) -> str | None:
    match = _PEOPLE.search(text)
    if match:
        return f"{match.group(1)} {match.group(2).lower()}"
    match = _N_EQUALS.search(text)
    if match:
        return f"n = {match.group(1)}"
    return None


def _short_cite(title: str, year: int | None) -> str:
    words = title.split()
    head = " ".join(words[:6]) + ("..." if len(words) > 6 else "")
    return f"{head} ({year})" if year else head


def _identifier(passage: dict) -> str:
    paper_id = passage.get("paper_id") or ""
    if paper_id.startswith("PMC"):
        return paper_id
    if passage.get("external_id"):
        return str(passage["external_id"])
    return paper_id[:40]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def _seconds(words: int) -> float:
    return words / WORDS_PER_SECOND


def _count_words(text: str) -> int:
    return len(re.sub(r"\[E\d+\]", "", text).split())


def _claims_by_stance(result: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Complete claims split into supported, contradicted and unclear, in claim id order."""
    supported, contradicted, unclear = [], [], []
    for claim_id in sorted(result.get("claims", {})):
        item = result["claims"][claim_id]
        if item.get("status") != "complete" or not item.get("verdict"):
            continue
        label = item["verdict"].get("label")
        bucket = {"supports": supported, "contradicts": contradicted, "uncertain": unclear}.get(label)
        if bucket is not None:
            bucket.append(item)
    return supported, contradicted, unclear


def _evidence_for(item: dict, start_index: int) -> list[tuple[Evidence, dict]]:
    """One Evidence per verbatim citation on the verdict, paired with its passage."""
    passages = {p["id"]: p for p in item.get("evidence", []) if not p.get("known_retracted")}
    stance = STANCE_FROM_VERDICT.get(item["verdict"].get("label"), "unclear")
    out = []
    for n, citation in enumerate(item["verdict"].get("citations", []), start=start_index):
        passage = passages.get(citation.get("passage_id"))
        if not passage:
            continue
        year = _year(passage.get("published"))
        out.append((Evidence(
            id=f"E{n}",
            paper=_short_cite(passage.get("title") or "Untitled", year)[:200],
            stance=stance,
            access=ACCESS_FROM_PASSAGE.get(passage.get("access_type"), "abstract_only"),
            quote=citation["quote"][:600],
            design=_design(passage.get("study_types") or []),
            people=_people(passage.get("text", "") + " " + passage.get("context", "")),
            year=year,
            url=passage.get("source_url"),
        ), passage))
    return out


def _paper_card(ev: Evidence, passage: dict) -> Card:
    badges = []
    if ev.design:
        badges.append(Badge(label="Study design", value=ev.design))
    if ev.people:
        badges.append(Badge(label="People", value=ev.people))
    if ev.year:
        badges.append(Badge(label="Year", value=str(ev.year)))
    badges.append(Badge(label="Read", value="Full text" if ev.access == "full_text" else "Abstract only"))
    section = (passage.get("section") or "").strip()
    return Card(
        kind="paper",
        eyebrow=section.upper()[:60] if section else None,
        title=(passage.get("title") or "Untitled")[:200],
        body=[passage.get("context", "")[:1200]] if passage.get("context") else [],
        highlight=ev.quote,
        highlight_section=section.upper()[:40] if section else None,
        badges=badges[:6],
        footer=" · ".join(x for x in [str(ev.year) if ev.year else None, _identifier(passage)] if x)[:200],
        evidence_id=ev.id,
    )


def _finding(supported: list, contradicted: list, unclear: list, evidence: list[Evidence]) -> Finding:
    counts = {
        "supports": sum(1 for e in evidence if e.stance == "supports"),
        "contradicts": sum(1 for e in evidence if e.stance == "contradicts"),
        "unclear": sum(1 for e in evidence if e.stance == "unclear"),
    }
    full = sum(1 for e in evidence if e.access == "full_text")
    if not evidence:
        label, sentence = "insufficient", "The research we could find does not settle this claim either way."
    elif supported and contradicted:
        label = "mixed"
        sentence = "Part of this holds up and the main conclusion does not."
    elif contradicted:
        label = "contradicted"
        sentence = "The studies do not support the main claim in this video."
    elif supported:
        label = "supported"
        sentence = "The studies back what this video says."
    else:
        label = "unclear"
        sentence = "The studies that exist do not settle this claim, and nobody knows yet."
    return Finding(label=label, sentence=sentence, full_text=full, abstract_only=len(evidence) - full, **counts)


def build_plan(case: dict, out_dir: Path) -> RenderPlan:
    """A finished case in, a plan with scenes, evidence and finding filled and voice empty."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = case.get("result") or {}
    supported, contradicted, unclear = _claims_by_stance(result)
    ordered = supported + contradicted + unclear
    if not ordered:
        raise ValueError("The case has no complete claim with a verdict, nothing to narrate.")

    # The rebuttal targets the contradicted claim when there is one. Otherwise the
    # video is a "this checks out" or a "nobody knows" video, and the first claim leads.
    target = contradicted[0] if contradicted else ordered[0]
    claim_text = target["claim"]["text"].strip()
    creator = (result.get("media") or {}).get("uploader")

    evidence: list[Evidence] = []
    credit_pairs: list[tuple[Evidence, dict]] = []
    correction_pairs: list[tuple[Evidence, dict]] = []
    for item in supported[:1]:
        pairs = _evidence_for(item, len(evidence) + 1)
        credit_pairs.extend(pairs)
        evidence.extend(e for e, _ in pairs)
    if contradicted:
        pairs = _evidence_for(target, len(evidence) + 1)
        correction_pairs.extend(pairs)
        evidence.extend(e for e, _ in pairs)
    elif not supported:
        pairs = _evidence_for(target, len(evidence) + 1)
        correction_pairs.extend(pairs)
        evidence.extend(e for e, _ in pairs)
    finding = _finding(supported, contradicted, unclear, evidence)

    scenes: list[Scene] = []
    t = 0.0

    def add(kind, narration, card, transition="fade", fixed=None):
        nonlocal t
        spoken = max(_seconds(_count_words(narration)), 1.5)
        length = max(fixed, spoken) if fixed is not None else spoken
        scenes.append(Scene(kind=kind, start=round(t, 3), end=round(t + length, 3), narration=narration,
                            card=card, transition_in=transition))
        t += length

    # 1. The clip plays. The hook is a question, not a verdict.
    hook = "Let's check that against the research."
    add("clip", hook, Card(kind="clip", eyebrow="STITCH INCOMING", title=claim_text[:200],
                           footer=(f"@{creator}" if creator else None)), transition="none", fixed=CLIP_SECONDS)

    # 2. Freeze on the claim.
    span = _claim_span(result, target)
    add("claim", "Here is the claim, in the creator's own words.",
        Card(kind="claim", eyebrow="THE CLAIM", title=claim_text[:200], body=[span] if span else []),
        transition="fade")

    # 3. Credit first, where the evidence backs them. The quote is trimmed hard here,
    #    the credit is a nod, the correction is where the full sentence belongs.
    if credit_pairs:
        ev, passage = credit_pairs[0]
        line = (f"First, the part that holds up. A {_design_phrase(ev, people=False)} found that "
                f"{_lower_first(_trim_quote(ev.quote, 110))} [{ev.id}]. On that point, the video is right.")
        add("paper", line, _paper_card(ev, passage), transition="smoothup")

    # 4. The correction, one scene per paper, strongest first, capped to fit the minute.
    #    The first paper gets its full sentence, that is the signature shot. Later
    #    papers get a shorter cut, they are there to show it is not one study.
    correction_pairs = correction_pairs[:MAX_PAPER_SCENES]
    for n, (ev, passage) in enumerate(correction_pairs):
        quote = _lower_first(_trim_quote(ev.quote, 175 if n == 0 else 100))
        if contradicted:
            opener = "But here is what the video skips." if n == 0 else "And it is not one study."
            line = f"{opener} A {_design_phrase(ev)} found that {quote} [{ev.id}]."
        elif supported:
            line = f"A {_design_phrase(ev)} found that {quote} [{ev.id}]."
        else:
            line = f"The closest study, a {_design_phrase(ev)}, found that {quote} [{ev.id}]. That does not settle it."
        add("paper", line, _paper_card(ev, passage), transition="smoothup" if n == 0 else "slideleft")

    # 5. The finding, as information.
    strongest = _strongest(evidence, "contradicts") or _strongest(evidence, "supports") or (evidence[0] if evidence else None)
    tag = f" [{strongest.id}]" if strongest else ""
    counts = _counts_phrase(finding)
    add("finding", f"{finding.sentence}{tag} {counts}",
        Card(kind="finding", eyebrow="WHAT THE RESEARCH FOUND", title=finding.sentence[:200],
             body=[counts, _access_phrase(finding)]), transition="circleopen")

    # 6. Close.
    others = max(len(ordered) - 1, 0)
    close_line = _close_line(finding, others)
    add("close", close_line, Card(kind="close", eyebrow="HYPECHECK", title=_takeaway(finding)[:200],
                                  footer=f"{len(evidence)} studies checked, {finding.full_text} read in full"),
        transition="fadeblack")

    _fit_to_band(scenes)
    plan = RenderPlan(case_id=str(case.get("id") or "case"), claim=claim_text[:300], creator=creator,
                      scenes=scenes, evidence=evidence, finding=finding)
    plan.save(out_dir / "plan.json")
    return plan


def _claim_span(result: dict, item: dict) -> str | None:
    """The transcript text spoken while the claim was made, for the claim card."""
    claim = item["claim"]
    segments = (result.get("analysis") or {}).get("transcript") or []
    inside = [s["text"].strip() for s in segments
              if s.get("end", 0) >= claim.get("start", 0) and s.get("start", 0) <= claim.get("end", 0)]
    text = " ".join(inside).strip()
    return text[:400] if text else None


def _design_phrase(ev: Evidence, people: bool = True) -> str:
    design = (ev.design or "study").lower()
    year = f" from {ev.year}" if ev.year else ""
    who = f" of {ev.people}" if people and ev.people and not ev.people.startswith("n =") else ""
    return f"{design}{who}{year}"


def _trim_quote(quote: str, limit: int = 160) -> str:
    """Shorten a quote for narration without an ellipsis, which a voice would read
    aloud and a sentence splitter would trip on. Prefer cutting at a clause boundary
    in the back half of the allowance, else at a word."""
    q = " ".join(quote.split())
    if len(q) <= limit:
        return q.rstrip(".")
    head = q[:limit]
    clause = max(head.rfind(", "), head.rfind("; "), head.rfind(": "))
    cut = head[:clause] if clause > limit * 0.6 else head.rsplit(" ", 1)[0]
    return cut.rstrip(",;:. ")


def _lower_first(text: str) -> str:
    return text[0].lower() + text[1:] if text and not text[:2].isupper() else text


def _strongest(evidence: list[Evidence], stance: str) -> Evidence | None:
    rank = {label: i for i, (_, label) in enumerate(DESIGN_RANK)}
    side = [e for e in evidence if e.stance == stance]
    return min(side, key=lambda e: rank.get(e.design or "", len(rank))) if side else None


def _counts_phrase(f: Finding) -> str:
    parts = []
    if f.contradicts:
        parts.append(f"{f.contradicts} {'study contradicts' if f.contradicts == 1 else 'studies contradict'} it")
    if f.supports:
        parts.append(f"{f.supports} {'backs' if f.supports == 1 else 'back'} it")
    if f.unclear:
        parts.append(f"{f.unclear} {'is' if f.unclear == 1 else 'are'} unclear")
    return (", ".join(parts) + ".") if parts else "No study we found takes a side."


def _access_phrase(f: Finding) -> str:
    total = f.full_text + f.abstract_only
    if not total:
        return "No studies located."
    return f"{f.full_text} of {total} read in full, {f.abstract_only} from the abstract."


def _takeaway(f: Finding) -> str:
    return {
        "contradicted": "The research says otherwise.",
        "supported": "This one checks out.",
        "mixed": "Half right. Read the fine print.",
        "unclear": "The jury is still out.",
        "insufficient": "Not enough research to say.",
    }[f.label]


OTHERS_SENTENCE = " We checked {n} more {noun} from this video, the receipts are on the page."


def _close_line(f: Finding, others: int) -> str:
    base = {
        "contradicted": "Before you change what you do, read the studies, not the caption.",
        "supported": "Credit where it is due. This one holds up.",
        "mixed": "Take the good advice, drop the conclusion.",
        "unclear": "Anyone telling you this is settled is ahead of the evidence.",
        "insufficient": "When the research is thin, the honest answer is that we do not know yet.",
    }[f.label]
    if others:
        base += OTHERS_SENTENCE.format(n=others, noun="claim" if others == 1 else "claims")
    return base + " Sources in the description."


def _fit_to_band(scenes: list[Scene]) -> None:
    """Keep the estimated total between MIN_SECONDS and MAX_SECONDS. Over budget, drop
    the least essential words first: the "we checked more claims" aside, then the
    last correction paper, but never below one correction, and never the credit,
    because credit-then-correct is the whole shape. Under budget, pad the close. The
    voice stage corrects all of this to the real audio, this only keeps the script an
    honest length."""
    def total():
        return scenes[-1].end

    close = scenes[-1]
    if total() > MAX_SECONDS and "more claim" in close.narration:
        close.narration = re.sub(r" We checked \d+ more claims? from this video, the receipts are on the page\.", "",
                                 close.narration)
        _retime(scenes)
    while total() > MAX_SECONDS:
        corrections = [s for s in scenes if s.kind == "paper" and "holds up" not in s.narration]
        if len(corrections) <= 1:
            break
        scenes.remove(corrections[-1])
        _retime(scenes)
    if total() < MIN_SECONDS:
        pad = " Every sentence in this video is tied to a study you can open yourself."
        close.narration = (close.narration + pad)[:800]
        _retime(scenes)


def _retime(scenes: list[Scene]) -> None:
    t = 0.0
    for s in scenes:
        spoken = max(_seconds(_count_words(s.narration)), 1.5)
        length = max(CLIP_SECONDS, spoken) if s.kind == "clip" else spoken
        s.start, s.end = round(t, 3), round(t + length, 3)
        t += length
