"""
Runs the plan-based renderer (render.py) inside the pipeline, in artifact.py's clothes.

The pipeline, the video endpoints and the page all speak one contract, the one
artifact.py established: a folder under media_root/{case_id}/video/{digest}/ holding
response.mp4, captions.vtt and manifest.json, and a "video" dict on the case result
with status, artifact, duration, and the three URLs. This module makes render.py
produce exactly that, so switching renderers changes nothing downstream. Pick it with
VIDEO_RENDERER=plan (the default) or artifact.

Same idempotence rule as artifact.py: a case whose verdicts have not changed reuses
its finished folder instead of rendering again.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

from app.config import settings
from app.video.plan import RenderPlan

VERSION = 1
VIDEO_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def digest_for(case: dict) -> str:
    """Twenty hex characters, the shape video_artifact() in main.py insists on."""
    claims = (case.get("result") or {}).get("claims") or {}
    seed = json.dumps({"id": case.get("id"), "claims": claims, "renderer": "plan", "v": VERSION}, sort_keys=True)
    return hashlib.sha1(seed.encode()).hexdigest()[:20]


def source_clip_for(case_root: Path) -> str | None:
    """The original video the pipeline downloaded or the creator uploaded, if it is still here."""
    if not case_root.is_dir():
        return None
    for path in sorted(case_root.iterdir()):
        if not path.is_file():
            continue
        if path.name == "upload.video" or path.suffix.lower() in VIDEO_SUFFIXES:
            return str(path)
    return None


def _stamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02}:{int(minutes):02}:{secs:06.3f}"


def write_vtt(pages: list[dict], path: Path) -> None:
    """WebVTT from the caption pages, one cue per page, word timed when the voice stage had timings."""
    lines = ["WEBVTT", ""]
    for page in pages:
        text = str(page.get("text", "")).replace("-->", "→").replace("<", "&lt;")
        lines += [f"{_stamp(page['start'])} --> {_stamp(page['end'])}", text, ""]
    path.write_text("\n".join(lines))


def _references(plan: RenderPlan) -> list[dict]:
    return [
        {"id": e.id, "paper": e.paper, "stance": e.stance, "access": e.access, "quote": e.quote,
         "design": e.design, "people": e.people, "year": e.year, "url": e.url}
        for e in plan.evidence
    ]


def _video_dict(case_id: str, plan: RenderPlan, digest: str) -> dict:
    voice = plan.voice
    word_timed = bool(voice and voice.timings_from in ("engine", "whisper"))
    return {
        "status": "ready", "version": VERSION, "renderer": "plan", "artifact": digest,
        "duration_seconds": round(plan.duration, 3), "width": plan.width, "height": plan.height,
        "voice": voice.engine if voice else "silent", "ai_voice": bool(voice and voice.engine != "silent"),
        "caption_timing": "word" if word_timed else "approximate",
        "finding": plan.finding.model_dump() if plan.finding else None,
        "url": f"/api/cases/{case_id}/video",
        "captions_url": f"/api/cases/{case_id}/video/captions",
        "sources_url": f"/api/cases/{case_id}/video/sources",
    }


def render_sync(case: dict, root: Path | None = None) -> dict:
    """The whole job on the calling thread. render_video() wraps it for the async pipeline."""
    from app.video import captions
    from app.video.render import render_case

    case_id = str(case["id"])
    root = Path(root) if root is not None else settings().media_root
    case_root = root / case_id
    digest = digest_for(case)
    folder = case_root / "video" / digest
    manifest_file = folder / "manifest.json"
    if manifest_file.is_file():
        return json.loads(manifest_file.read_text())["video"]

    work = folder / "work"
    work.mkdir(parents=True, exist_ok=True)
    plan = render_case(case, work, sfx=True, brainrot=False, source_clip=source_clip_for(case_root),
                       log=lambda *_: None)
    if not plan.output_path or not Path(plan.output_path).is_file():
        raise RuntimeError("The renderer finished without producing an MP4.")

    shutil.copyfile(plan.output_path, folder / "response.mp4")
    write_vtt(captions.pages(plan), folder / "captions.vtt")
    video = _video_dict(case_id, plan, digest)
    scenes = [{"kind": s.kind, "start": s.start, "end": s.end, "narration": s.narration,
               "evidence_id": s.card.evidence_id} for s in plan.scenes]
    manifest = {"video": video, "source_url": case.get("source_url"), "scenes": scenes,
                "references": _references(plan)}
    manifest_file.write_text(json.dumps(manifest, indent=2))
    return video


async def render_video(case: dict) -> dict:
    """Drop-in for artifact.render_video: same argument, same returned dict, same folder layout."""
    return await asyncio.to_thread(render_sync, case)
