"""
Captions stage: word timings in, short caption pages out.

TikTok-style captions show two to four words at a time, in reading order, timed to
the voice. Pages break early at sentence ends and commas so a thought does not run
across a page boundary, and a number is never split from its unit ("446 to 477
nanometres" stays together), because a page that says "477" alone means nothing.

Each page is {"start", "end", "text"} in seconds and plain text, which is all the
compose stage needs to draw them.
"""

from __future__ import annotations

import re

from app.video.plan import RenderPlan, Word

MAX_WORDS = 4
MIN_WORDS = 2

UNITS = {
    "nm", "nanometres", "nanometers", "mg", "g", "kg", "mcg", "µg", "ug", "iu", "ml", "l", "%",
    "percent", "seconds", "minutes", "hours", "days", "weeks", "months", "years", "times",
    "adults", "participants", "patients", "people", "subjects", "trials", "studies",
}
_NUMBER = re.compile(r"^[\d][\d,.]*$")
_RANGE_JOINERS = {"to", "and", "or"}


def _is_number(token: str) -> bool:
    return bool(_NUMBER.match(token.strip(".,;:!?")))


def _is_unit(token: str) -> bool:
    return token.strip(".,;:!?").lower() in UNITS


def _groups(words: list[Word]) -> list[list[Word]]:
    """Glue tokens that must never be separated: a number and its unit, and a range
    like '446 to 477 nanometres'. Each group then behaves as one token when paging."""
    groups: list[list[Word]] = []
    i = 0
    while i < len(words):
        group = [words[i]]
        j = i + 1
        # number, then optional "to 477", then optional unit
        if _is_number(words[i].text):
            if j + 1 < len(words) and words[j].text.lower() in _RANGE_JOINERS and _is_number(words[j + 1].text):
                group += [words[j], words[j + 1]]
                j += 2
            if j < len(words) and _is_unit(words[j].text):
                group.append(words[j])
                j += 1
        groups.append(group)
        i = j
    return groups


def _ends_sentence(token: str) -> bool:
    return token.rstrip()[-1:] in ".!?"


def _ends_clause(token: str) -> bool:
    return token.rstrip()[-1:] in ",;:"


def pages(plan: RenderPlan) -> list[dict]:
    """Two to four words a page, honoring punctuation and never orphaning a unit."""
    if not plan.voice or not plan.voice.words:
        return []
    out: list[dict] = []
    page: list[Word] = []

    def flush():
        if page:
            out.append({"start": page[0].start, "end": page[-1].end,
                        "text": " ".join(w.text for w in page)})
            page.clear()

    for group in _groups(plan.voice.words):
        if page and len(page) + len(group) > MAX_WORDS:
            flush()
        page.extend(group)
        last = page[-1].text
        if _ends_sentence(last) or (_ends_clause(last) and len(page) >= MIN_WORDS) or len(page) >= MAX_WORDS:
            flush()
    flush()

    # A trailing one-word page reads as a stutter, fold it into the page before.
    if len(out) >= 2 and len(out[-1]["text"].split()) == 1 and len(out[-2]["text"].split()) < MAX_WORDS:
        out[-2] = {"start": out[-2]["start"], "end": out[-1]["end"],
                   "text": out[-2]["text"] + " " + out[-1]["text"]}
        out.pop()
    return out
