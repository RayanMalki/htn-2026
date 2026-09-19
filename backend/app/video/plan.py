"""
The render plan: one JSON-serializable object that every video stage reads or writes.

The script stage fills `scenes` and `evidence` from a finished case. The voice stage
fills `voice` (an audio file plus word timings). The card stage fills each scene's
`card_png`. The compose stage turns all of it into an MP4. The post stage adds sound
effects and, when asked, the split-screen layer. Stages never call each other, they
only read and write this plan, so each one can be built, tested and swapped alone.

Sizes are vertical short-form: 720 by 1280 at 30 frames per second by default, which
renders fast on a laptop and looks identical to 1080 by 1920 on a phone. Nothing here
is a score. The finding is a sentence and a set of counts, never a number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

SceneKind = Literal["clip", "claim", "paper", "finding", "close"]
Transition = Literal["fade", "smoothup", "circleopen", "fadeblack", "slideleft", "slideup", "none"]


class Badge(BaseModel):
    """A small labelled block that lands beside a paper: study design, people, year."""

    label: str = Field(max_length=40)
    value: str = Field(max_length=80)


class Card(BaseModel):
    """What one scene shows. The card stage renders this to a PNG at the plan size."""

    kind: SceneKind
    eyebrow: str | None = Field(default=None, max_length=60)      # small caps line above the title
    title: str | None = Field(default=None, max_length=200)
    body: list[str] = Field(default_factory=list, max_length=12)  # paragraphs, plain text
    highlight: str | None = Field(default=None, max_length=600)   # the exact sentence to sweep-highlight
    highlight_section: str | None = Field(default=None, max_length=40)  # RESULTS, CONCLUSIONS
    badges: list[Badge] = Field(default_factory=list, max_length=6)
    footer: str | None = Field(default=None, max_length=200)      # journal, year, identifier
    evidence_id: str | None = Field(default=None, max_length=8)   # E1, E2, ties the scene to a citation


class Scene(BaseModel):
    kind: SceneKind
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    narration: str = Field(default="", max_length=800)   # what the voice says over this scene
    card: Card
    transition_in: Transition = "fade"
    card_png: str | None = None                          # filled by the card stage
    # For the paper scene: where the highlight sits on the card so the camera can push toward it.
    focus_box: dict[str, float] | None = None            # x, y, w, h in card pixels


class Word(BaseModel):
    text: str = Field(max_length=60)
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class Voice(BaseModel):
    audio_path: str
    duration: float = Field(ge=0)
    engine: Literal["elevenlabs", "gemini", "openai", "macos_say", "silent"]
    words: list[Word] = Field(default_factory=list)      # word timings for captions, may be empty
    timings_from: Literal["engine", "whisper", "estimated", "none"] = "none"


class Evidence(BaseModel):
    id: str = Field(max_length=8)                        # E1
    paper: str = Field(max_length=200)                   # short cite: West 2011
    stance: Literal["supports", "contradicts", "unclear"]
    access: Literal["full_text", "free_needs_browser", "abstract_only"]
    quote: str = Field(max_length=600)
    design: str | None = Field(default=None, max_length=60)
    people: str | None = Field(default=None, max_length=40)
    year: int | None = None
    url: str | None = None


class Finding(BaseModel):
    """Information, never a score."""

    label: Literal["supported", "contradicted", "mixed", "unclear", "insufficient"]
    sentence: str = Field(max_length=400)                # one plain sentence on what the research found
    supports: int = 0
    contradicts: int = 0
    unclear: int = 0
    full_text: int = 0
    abstract_only: int = 0


class RenderPlan(BaseModel):
    case_id: str
    claim: str = Field(max_length=300)                   # the claim as the creator made it
    creator: str | None = Field(default=None, max_length=80)
    width: int = 720
    height: int = 1280
    fps: int = 30
    source_clip: str | None = None                       # the original video, if we have the file
    scenes: list[Scene] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    finding: Finding | None = None
    voice: Voice | None = None
    sfx: bool = True
    brainrot: bool = False                               # split screen, off unless asked
    gameplay_path: str | None = None                     # the clip for the bottom pane, if any
    output_path: str | None = None                       # filled by compose

    @property
    def duration(self) -> float:
        if self.voice:
            return self.voice.duration
        return max((s.end for s in self.scenes), default=0.0)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str | Path) -> RenderPlan:
        return cls.model_validate_json(Path(path).read_text())
