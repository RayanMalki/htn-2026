"""Versioned, persisted contract shared by the video stages."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

VERSION = 4
SceneKind = Literal['clip', 'claim', 'paper', 'finding', 'close']
Transition = Literal['fade', 'smoothup', 'circleopen', 'fadeblack', 'slideleft', 'slideup', 'none']


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.part')
    temporary.write_text(text)
    temporary.replace(path)


class Badge(BaseModel):
    label: str
    value: str


class Card(BaseModel):
    kind: SceneKind
    eyebrow: str | None = None
    title: str | None = None
    body: list[str] = Field(default_factory=list)
    highlight: str | None = None
    highlight_section: str | None = None
    badges: list[Badge] = Field(default_factory=list)
    footer: str | None = None
    evidence_id: str | None = None


class Scene(BaseModel):
    kind: SceneKind
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    narration: str = ''
    card: Card
    transition_in: Transition = 'fade'
    card_png: str | None = None
    focus_box: dict[str, float] | None = None


class Word(BaseModel):
    text: str
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)


class Voice(BaseModel):
    audio_path: str
    duration: float = Field(gt=0, allow_inf_nan=False)
    engine: Literal['openai', 'silent']
    words: list[Word] = Field(default_factory=list)
    timings_from: Literal['whisper', 'estimated', 'none'] = 'none'


class Evidence(BaseModel):
    id: str
    claim_id: str
    passage_id: str
    paper_id: str
    paper: str
    provider: str
    source_kind: str
    access: Literal['full_text', 'abstract_only', 'summary']
    quote: str
    url: str


class Finding(BaseModel):
    label: Literal['supports', 'contradicts', 'uncertain']
    sentence: str
    limitations: list[str] = Field(default_factory=list)
    papers: int = 0
    summaries: int = 0


class RenderPlan(BaseModel):
    version: int = VERSION
    case_id: str
    selected_claim_id: str = ''
    claim: str
    width: int = 720
    height: int = 1280
    fps: int = 30
    source_clip: str | None = None
    source_start: float = 0
    source_duration: float = 0
    source_transcript: str = ''
    scenes: list[Scene] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    finding: Finding | None = None
    voice: Voice | None = None
    sfx: bool = True
    brainrot: bool = False
    gameplay_path: str | None = None
    output_path: str | None = None
    stage: str = 'script'
    timings: dict[str, float] = Field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max((s.end for s in self.scenes), default=0.0)

    def save(self, path: str | Path) -> None:
        atomic_text(Path(path), self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate_json(Path(path).read_text())
