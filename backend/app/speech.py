"""Disfluency removal, so a detector judges the script rather than the delivery.

Spoken delivery carries fillers and self-repairs that read as unmistakably human.
A machine-written script performed aloud therefore scores human on delivery alone.
Removing the fillers asks the narrower question: was the underlying script written
by a machine? Removal is lossy, so callers score the verbatim text as well and
report the pair; the verbatim reading remains the honest one.
"""

import re

# Vocalised noise. Removing these never changes meaning.
SOUNDS = {
    "um", "umm", "ummm", "uh", "uhh", "uhhh", "uhm", "hm", "hmm", "hmmm",
    "mm", "mmm", "mhm", "mmhm", "er", "err", "erm", "ah", "ahh", "aah", "eh", "huh",
}

# Discourse markers with no propositional content in speech.
MARKERS = {
    "basically", "essentially", "literally", "actually", "honestly", "obviously",
    "seriously", "frankly", "truthfully", "anyway", "anyways", "alright",
}

# Longest first, so "you know what i mean" is consumed before "you know".
PHRASES = [
    "you know what i mean", "you know what im saying", "or something like that",
    "and things like that", "and stuff like that", "at the end of the day",
    "if that makes sense", "like i said", "and all that", "or whatever",
    "you know", "i mean", "kind of", "sort of", "kinda", "sorta",
]

# "kind of" and "sort of" are ordinary noun phrases after these words.
OF_KEEPERS = {
    "what", "which", "whatever", "any", "some", "every", "each", "this", "that",
    "the", "a", "one", "another", "other", "different", "same", "certain", "new",
}

# "like" is also a verb, preposition and comparator. These precede the real uses.
LIKE_KEEPERS = {
    "i", "you", "we", "they", "he", "she", "it", "who", "that", "people",
    "would", "do", "dont", "does", "doesnt", "did", "didnt", "will", "wont",
    "look", "looks", "looked", "looking", "sound", "sounds", "sounded",
    "feel", "feels", "felt", "seem", "seems", "seemed", "taste", "tastes",
    "smell", "smells", "act", "acts", "work", "works", "is", "was", "are",
    "were", "be", "been", "being", "just", "much", "more", "exactly",
    "something", "anything", "nothing", "things", "someone", "somebody",
}

WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
STUTTER = re.compile(r"\b[A-Za-z]{1,3}-(?=\s|$)")
REPEAT = re.compile(r"\b([A-Za-z]{1,12})(\s*[,]?\s+\1\b)+", re.IGNORECASE)


def _key(word: str) -> str:
    return re.sub(r"['’]", "", word).lower()


def _previous_word(text: str, index: int) -> str:
    found = None
    for match in WORD.finditer(text, 0, index):
        found = match
    return _key(found.group(0)) if found else ""


def _after_comma(text: str, index: int) -> bool:
    cursor = index - 1
    while cursor >= 0 and text[cursor].isspace():
        cursor -= 1
    return cursor >= 0 and text[cursor] == ","


def _tidy(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,;:])(\s*[,.;:!?])+", r"\1", text)
    text = re.sub(r"([.!?])\s*[,;:]+", r"\1", text)
    # Removing a one-word sentence such as "Basically." leaves its full stop orphaned.
    text = re.sub(r"([.!?])(\s*[.!?])+", r"\1", text)
    text = re.sub(r"(^|(?<=[.!?])\s*)[,;:]+\s*", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return (text[0].upper() + text[1:]) if text else text


def strip_fillers(text: str) -> tuple[str, list[str]]:
    """Return the text with speech fillers removed, plus what was removed.

    Paragraph breaks survive, because the detector scores per paragraph.
    """
    removed: list[str] = []
    blocks = []
    for block in re.split(r"\n\s*\n", text):
        if not block.strip():
            continue
        cleaned, dropped = _strip_block(block)
        removed.extend(dropped)
        if cleaned:
            blocks.append(cleaned)
    return "\n\n".join(blocks), removed


def _strip_block(text: str) -> tuple[str, list[str]]:
    removed: list[str] = []
    working = text

    for phrase in PHRASES:
        pattern = re.compile(r"\b" + r"[\s,]+".join(map(re.escape, phrase.split())) + r"\b", re.IGNORECASE)

        def drop(match: re.Match) -> str:
            if phrase in {"kind of", "sort of"} and _previous_word(match.string, match.start()) in OF_KEEPERS:
                return match.group(0)
            removed.append(match.group(0).strip())
            return " "

        working = pattern.sub(drop, working)

    def drop_word(match: re.Match) -> str:
        word = _key(match.group(0))
        if word in SOUNDS or word in MARKERS:
            removed.append(match.group(0))
            return " "
        # A comma before "like" marks it as filler even after a verb: "it is, like, huge".
        if word == "like" and (_after_comma(match.string, match.start())
                               or _previous_word(match.string, match.start()) not in LIKE_KEEPERS):
            removed.append(match.group(0))
            return " "
        return match.group(0)

    working = WORD.sub(drop_word, working)

    # Immediate repetition of a word is a self-repair rather than emphasis.
    def drop_repeat(match: re.Match) -> str:
        removed.extend(match.group(0).split()[1:])
        return match.group(1)

    working = REPEAT.sub(drop_repeat, working)
    working = STUTTER.sub(lambda m: removed.append(m.group(0)) or " ", working)
    return _tidy(working), removed
