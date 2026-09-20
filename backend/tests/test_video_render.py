"""
The orchestrator runs every stage in order and leaves a plan.json behind.

The visual stages need ffmpeg and a browser, so here they are replaced by stubs
that only mark the plan the way the real stages would. That keeps this test about
one thing, the order and the hand-offs in render.py, and lets it run anywhere the
audio stages run, which includes CI with no voice engine (the silent path).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

import app.video as video_pkg
from app.video import render
from app.video.plan import RenderPlan

EXAMPLE = Path(__file__).resolve().parents[1] / "app" / "video" / "examples" / "blue_light_case.json"


def _stub_visual_stages(monkeypatch, calls: list[str]):
    """Stand-ins for cards, compose and post that record being called."""

    def render_cards(plan: RenderPlan, out_dir: Path) -> RenderPlan:
        calls.append("cards")
        for scene in plan.scenes:
            scene.card_png = str(out_dir / f"{scene.kind}.png")
            if scene.kind == "paper":
                scene.focus_box = {"x": 40, "y": 600, "w": 640, "h": 120}
        return plan

    def render_caption_pages(pages, plan, out_dir):
        calls.append("caption_pages")
        return [{**p, "png": str(out_dir / "cap.png")} for p in pages]

    def compose(plan: RenderPlan, out_dir: Path, caption_pages) -> RenderPlan:
        calls.append("compose")
        assert plan.voice is not None, "compose ran before voice"
        assert all(s.card_png for s in plan.scenes), "compose ran before cards"
        assert caption_pages and all("png" in p for p in caption_pages), "compose ran before caption pages"
        plan.output_path = str(out_dir / "rebuttal.mp4")
        return plan

    def apply(plan: RenderPlan, out_dir: Path) -> RenderPlan:
        calls.append("post")
        assert plan.output_path, "post ran before compose"
        return plan

    cards = types.ModuleType("app.video.cards")
    cards.render_cards = render_cards
    cards.render_caption_pages = render_caption_pages
    comp = types.ModuleType("app.video.compose")
    comp.compose = compose
    post = types.ModuleType("app.video.post")
    post.apply = apply
    for name, mod in (("cards", cards), ("compose", comp), ("post", post)):
        monkeypatch.setitem(sys.modules, f"app.video.{name}", mod)
        monkeypatch.setattr(video_pkg, name, mod, raising=False)


def test_render_case_runs_stages_in_order_and_saves_the_plan(monkeypatch, tmp_path):
    for key in ("ELEVENLABS_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    calls: list[str] = []
    _stub_visual_stages(monkeypatch, calls)
    case = json.loads(EXAMPLE.read_text())

    plan = render.render_case(case, tmp_path, sfx=False, brainrot=True, log=lambda *_: None)

    assert calls == ["cards", "caption_pages", "compose", "post"], calls
    assert plan.output_path and plan.output_path.endswith("rebuttal.mp4")
    assert plan.brainrot is True and plan.sfx is False
    assert plan.finding is not None and plan.finding.label == "mixed"
    assert plan.voice is not None and plan.voice.duration > 0
    saved = RenderPlan.load(tmp_path / "plan.json")
    assert saved.case_id == plan.case_id and len(saved.scenes) == len(plan.scenes)
    assert abs(saved.scenes[-1].end - saved.voice.duration) < 0.05, "scenes were not rescaled to the audio"


def test_render_case_reports_a_missing_stage_clearly(monkeypatch, tmp_path):
    """A stage that is not there fails at render time with its name, never at app import."""
    for name in ("cards", "compose", "post"):
        monkeypatch.setitem(sys.modules, f"app.video.{name}", None)
        monkeypatch.delattr(video_pkg, name, raising=False)
    case = json.loads(EXAMPLE.read_text())
    with pytest.raises(ImportError):
        render.render_case(case, tmp_path, log=lambda *_: None)
