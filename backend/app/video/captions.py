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


def write_ass(plan: RenderPlan, path):
    """Timed fragments burned by libass in the final encode, without PNG pages."""
    def stamp(t):
        cs = max(0, round(t * 100))
        return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'

    def escape(text):
        # Prevent source text from becoming ASS override commands.
        return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', ' ')

    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {plan.width}
PlayResY: {plan.height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,46,&H00FFFFFF,&H004AD5FF,&H00201614,&H80201614,-1,0,0,0,100,100,0,0,1,3,1,5,36,110,0,1
Style: Disclosure,DejaVu Sans,13,&H00FFFFFF,&H00FFFFFF,&H80201614,&H80201614,0,0,0,0,100,100,0,0,3,4,0,9,28,28,28,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = [f'Dialogue: 1,0:00:00.00,{stamp(plan.duration)},Disclosure,,0,0,0,,AI-generated voice']
    y = 760 if plan.brainrot else round(plan.height * .67)
    for page in pages(plan):
        text = escape(page['text'])
        words = text.split()
        # Emphasize one substantive word without changing or dropping the quote.
        if words:
            i = max(range(len(words)), key=lambda i: len(words[i]))
            words[i] = r'{\c&H4AD5FF&}' + words[i] + r'{\c&HFFFFFF&}'
        overlay = f'{{\\pos({round(plan.width * .45)},{y})\\fad(45,45)}}' + ' '.join(words)
        events.append(f"Dialogue: 0,{stamp(page['start'])},{stamp(page['end'])},Caption,,0,0,0,,{overlay}")
    if plan.source_clip and plan.source_transcript:
        # Source timestamps are coarse; keep this explicitly separate from aligned narration.
        text = escape(plan.source_transcript)
        events.append(f'Dialogue: 0,0:00:00.00,{stamp(plan.source_duration)},Caption,,0,0,0,,{{\\pos({round(plan.width * .45)},{y})}}{text}')
    path.write_text(header + '\n'.join(events) + '\n')
    return path
