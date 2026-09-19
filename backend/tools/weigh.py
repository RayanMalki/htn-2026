"""
The judging rules, as code. This is the piece that was only prose until now.

This morning the engine looked at the blue-light video, found one review sentence
that agreed with the creator, and said "supported". Weighing his own eight cited
studies, every one shows blue light suppresses melatonin. The honest verdict is
mixed. That gap is the single most important bug in the project, and these rules
close it:

  1. Count both sides. Never verdict on one paper.
  2. Weight by study design and by species. A human randomized trial outranks a
     human observational study outranks an animal study. Eight human studies are
     not outweighed by one mouse study, whatever it says.
  3. Abstain when the evidence is thin. Fewer than two usable studies, or every
     study unclear, means "insufficient", which is a real answer, not a failure.
  4. Say "mixed" when both sides carry real weight. That is different from
     "unclear", which means the studies themselves could not decide.

The verdict is information, never a number on the page. The weights below are
internal to ordering and thresholds and are not displayed. What the page shows is
the label plus the counts, and each study's badge.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Straight from the publication type Europe PMC reports. Cochrane reviews carry an
# explicit certainty rating, which is why they sit above a plain meta-analysis.
DESIGN_WEIGHT = {
    "cochrane": 1.00,
    "meta-analysis": 0.95,
    "systematic review": 0.90,
    "randomized controlled trial": 0.75,
    "clinical trial": 0.60,
    "observational": 0.40,
    "review": 0.30,
    "case report": 0.15,
    "editorial": 0.05,
    "unknown": 0.35,
}

SPECIES_WEIGHT = {"human": 1.0, "animal": 0.25, "in vitro": 0.10, "unknown": 0.5}

# Below this a study's vote is too weak to count toward "usable" for the abstain rule.
USABLE_FLOOR = 0.10
# A side needs at least this share of total weight to be called the winner outright.
# Between the two thresholds the answer is "mixed".
WIN_SHARE = 0.70
MIXED_SHARE = 0.30
MIN_USABLE = 2


@dataclass
class Study:
    id: str
    stance: str            # "supports" | "contradicts" | "unclear"
    design: str = "unknown"
    species: str = "human"
    access: str = "abstract_only"   # "full_text" | "free_needs_browser" | "abstract_only"
    retracted: bool = False
    year: int | None = None

    @property
    def weight(self) -> float:
        if self.retracted:
            return 0.0
        d = DESIGN_WEIGHT.get(self.design.lower(), DESIGN_WEIGHT["unknown"])
        s = SPECIES_WEIGHT.get(self.species.lower(), SPECIES_WEIGHT["unknown"])
        return round(d * s, 4)


@dataclass
class Verdict:
    label: str             # "supported" | "contradicted" | "mixed" | "unclear" | "insufficient"
    supports: int
    contradicts: int
    unclear: int
    usable: int
    retracted_ignored: int
    full_text: int
    abstract_only: int
    reason: str
    strongest_for: str | None = None
    strongest_against: str | None = None
    studies: list[Study] = field(default_factory=list)


def weigh(studies: list[Study]) -> Verdict:
    live = [s for s in studies if not s.retracted]
    retracted = len(studies) - len(live)
    usable = [s for s in live if s.weight >= USABLE_FLOOR and s.stance in ("supports", "contradicts", "unclear")]

    counts = {
        "supports": sum(1 for s in live if s.stance == "supports"),
        "contradicts": sum(1 for s in live if s.stance == "contradicts"),
        "unclear": sum(1 for s in live if s.stance == "unclear"),
    }
    access = {
        "full_text": sum(1 for s in live if s.access == "full_text"),
        "abstract_only": sum(1 for s in live if s.access != "full_text"),
    }

    def strongest(stance):
        side = [s for s in usable if s.stance == stance]
        return max(side, key=lambda s: s.weight).id if side else None

    base = dict(supports=counts["supports"], contradicts=counts["contradicts"], unclear=counts["unclear"],
                usable=len(usable), retracted_ignored=retracted,
                full_text=access["full_text"], abstract_only=access["abstract_only"],
                strongest_for=strongest("supports"), strongest_against=strongest("contradicts"),
                studies=studies)

    # Rule 3: abstain when thin.
    if len(usable) < MIN_USABLE:
        return Verdict(label="insufficient", reason=f"only {len(usable)} usable study, need {MIN_USABLE}", **base)
    decided = [s for s in usable if s.stance != "unclear"]
    if not decided:
        return Verdict(label="unclear", reason="every usable study is itself unclear", **base)

    # Rules 1 and 2: weighted vote across both sides.
    w_for = sum(s.weight for s in decided if s.stance == "supports")
    w_against = sum(s.weight for s in decided if s.stance == "contradicts")
    total = w_for + w_against
    share_for = w_for / total if total else 0.0

    # One-paper guard: a side with a single study cannot win outright, no matter its weight.
    n_for = sum(1 for s in decided if s.stance == "supports")
    n_against = sum(1 for s in decided if s.stance == "contradicts")

    if share_for >= WIN_SHARE and n_for >= 2:
        return Verdict(label="supported", reason=f"{share_for:.0%} of study weight supports, {n_for} studies", **base)
    if share_for <= MIXED_SHARE and n_against >= 2:
        return Verdict(label="contradicted", reason=f"{1 - share_for:.0%} of study weight contradicts, {n_against} studies", **base)
    # Rule 4: both sides carry weight, or the winning side is a single paper.
    return Verdict(label="mixed", reason=f"supports {share_for:.0%} vs contradicts {1 - share_for:.0%} of weight, {n_for} for and {n_against} against", **base)
