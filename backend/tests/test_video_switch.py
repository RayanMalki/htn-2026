"""
The renderer switch, and the adapter that lets render.py wear artifact.py's contract.

The adapter is tested with render_case replaced by a stub that writes a tiny real MP4
with ffmpeg, so the folder layout, the digest shape the endpoints validate, the VTT,
the manifest and the idempotence are all exercised without a browser or a voice.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import pipeline
from app.video import artifact, pipeline_adapter
from app.video.plan import Card, Evidence, Finding, RenderPlan, Scene, Voice, Word

CASE = {
    "id": "0d1b2c3e-4f5a-4b6c-8d7e-9f0a1b2c3d4e",
    "source_url": "https://www.tiktok.com/@creator/video/1",
    "result": {"claims": {"c1": {"text": "Blue light isn't ruining your sleep", "verdict": {"label": "uncertain"}}}},
}


def _fake_render_case(case, out_dir, **kwargs):
    """A stand-in for render.py that produces a real 1 second MP4 and a filled plan."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "rebuttal.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=720x1280:d=1:r=30", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                    "-t", "1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(mp4)], check=True)
    plan = RenderPlan(
        case_id=case["id"], claim="Blue light isn't ruining your sleep",
        scenes=[Scene(kind="claim", start=0.0, end=1.0, narration="Here is the claim.",
                      card=Card(kind="claim", title="claim"))],
        evidence=[Evidence(id="E1", paper="West 2011", stance="contradicts", access="full_text",
                           quote="Light suppresses melatonin in humans.", year=2011)],
        finding=Finding(label="mixed", sentence="Part of this holds up.", supports=1, contradicts=1),
        voice=Voice(audio_path=str(out_dir / "voice.wav"), duration=1.0, engine="silent",
                    words=[Word(text="Here", start=0.0, end=0.3), Word(text="is", start=0.3, end=0.5),
                           Word(text="the", start=0.5, end=0.7), Word(text="claim.", start=0.7, end=1.0)],
                    timings_from="estimated"),
        output_path=str(mp4),
    )
    _fake_render_case.calls += 1
    return plan


_fake_render_case.calls = 0


def test_default_renderer_is_the_plan_based_one():
    from app.config import Settings
    assert Settings.model_fields["video_renderer"].default == "plan"


def test_select_renderer_honours_the_setting():
    assert pipeline.select_renderer(SimpleNamespace(video_renderer="plan")) is pipeline_adapter.render_video
    assert pipeline.select_renderer(SimpleNamespace(video_renderer="artifact")) is artifact.render_video


def test_adapter_writes_the_artifact_layout_and_is_idempotent(monkeypatch, tmp_path):
    import app.video.render as render_module
    monkeypatch.setattr(render_module, "render_case", _fake_render_case)
    _fake_render_case.calls = 0

    video = pipeline_adapter.render_sync(CASE, root=tmp_path)

    assert video["status"] == "ready" and video["renderer"] == "plan"
    assert re.fullmatch(r"[a-f0-9]{20}", video["artifact"]), "digest must be 20 hex chars for the endpoints"
    folder = tmp_path / CASE["id"] / "video" / video["artifact"]
    assert (folder / "response.mp4").stat().st_size > 0
    vtt = (folder / "captions.vtt").read_text()
    assert vtt.startswith("WEBVTT") and "-->" in vtt and "claim." in vtt
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["references"][0]["id"] == "E1" and manifest["scenes"][0]["kind"] == "claim"
    assert video["url"] == f"/api/cases/{CASE['id']}/video"
    assert video["finding"]["label"] == "mixed" and "score" not in video["finding"]
    assert _fake_render_case.calls == 1

    again = pipeline_adapter.render_sync(CASE, root=tmp_path)
    assert again == video and _fake_render_case.calls == 1, "a second call must reuse the finished folder"


def test_digest_changes_when_the_verdicts_change():
    changed = {**CASE, "result": {"claims": {"c1": {"text": "x", "verdict": {"label": "supports"}}}}}
    assert pipeline_adapter.digest_for(CASE) != pipeline_adapter.digest_for(changed)


def test_source_clip_discovery_prefers_the_original_video(tmp_path):
    case_root = tmp_path / "case"
    (case_root / "video").mkdir(parents=True)
    assert pipeline_adapter.source_clip_for(case_root) is None
    (case_root / "upload.video").write_bytes(b"x")
    assert pipeline_adapter.source_clip_for(case_root).endswith("upload.video")


@pytest.mark.asyncio
async def test_async_wrapper_returns_the_same_dict(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline_adapter, "render_sync", lambda case, root=None: {"status": "ready", "artifact": "a" * 20})
    assert (await pipeline_adapter.render_video(CASE))["status"] == "ready"
