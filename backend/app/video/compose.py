"""
Compose: the scenes, the caption pages and the voice track become one MP4.

Pure ffmpeg. Remotion was tried in a pre-event lab and its motion is nicer, but its
free licence covers teams of up to three people and this team is four, so ffmpeg is
the renderer until that is settled in writing. Every piece of text on screen is a PNG
from the card stage, because this ffmpeg build has no drawtext and no subtitles
filter.

How the time lines up: each scene becomes its own clip, then one join pass runs the
clips through xfade so scene boundaries sit exactly at scene.start, then the caption
pages are overlaid at their times from one concat stream, then the voice is muxed.
The paper scene pushes the camera slowly toward the highlighted sentence, which the
card stage rendered at double resolution so the push has pixels to spare.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.video.plan import RenderPlan, Scene

T = 0.3            # seconds a transition takes, centred on the scene boundary
T_NONE = 0.04      # "none" still goes through xfade, as a cut this short
ZOOM = 1.18        # how far the paper push-in goes
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def _ff(args: list[str], timeout: int = 900) -> None:
    proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-800:]}")


def probe_size(path: str | Path) -> tuple[int, int]:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def probe_duration(path: str | Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def _still(png: str | Path, seconds: float, fps: int) -> list[str]:
    return ["-loop", "1", "-framerate", str(fps), "-t", f"{seconds:.3f}", "-i", str(png)]


def _timing(plan: RenderPlan) -> tuple[list[float], list[float], list[float]]:
    """Per scene: visible duration, clip length to render, and the xfade offset of the
    transition INTO it. Clips overlap by one transition, so the join is exactly the
    sum of visible durations and each boundary lands on scene.start."""
    n = len(plan.scenes)
    d = [max(s.end - s.start, 0.2) for s in plan.scenes]
    t_in = [(_t_for(s.transition_in) if i > 0 else 0.0) for i, s in enumerate(plan.scenes)]
    lengths = []
    for i in range(n):
        before = t_in[i] / 2
        after = (t_in[i + 1] / 2) if i + 1 < n else 0.0
        lengths.append(d[i] + before + after)
    offsets = []
    acc = 0.0
    for i in range(1, n):
        acc += d[i - 1]
        offsets.append(acc - t_in[i] / 2)
    return d, lengths, offsets


def _t_for(name: str) -> float:
    return T_NONE if name == "none" else T


def _render_scene(plan: RenderPlan, scene: Scene, length: float, out_dir: Path, idx: int) -> Path:
    W, H, fps = plan.width, plan.height, plan.fps
    out = out_dir / f"scene_{idx}.mp4"
    if scene.kind == "clip" and plan.source_clip and Path(plan.source_clip).exists():
        # The original video, looped if it is shorter than the scene, cropped to fill.
        _ff(["-stream_loop", "-1", "-i", str(plan.source_clip), "-t", f"{length:.3f}",
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps}",
             "-an", *ENC, str(out)])
        return out
    if not scene.card_png or not Path(scene.card_png).exists():
        raise RuntimeError(f"scene {idx} ({scene.kind}) has no rendered card, run the card stage first")
    pw, _ = probe_size(scene.card_png)
    scale = pw / W
    if scene.kind == "paper" and scene.focus_box:
        # Slow push toward the highlighted sentence, easing in, settling at 60 percent
        # of the scene so the badges and the narration land on a still frame.
        fb = scene.focus_box
        cx = (fb["x"] + fb["w"] / 2) * scale
        cy = (fb["y"] + fb["h"] / 2) * scale
        a = 0.4
        z_end = max(0.6 * length, a + 0.5)
        u = f"clip((on/{fps}-{a})/({z_end - a:.3f}),0,1)"
        zexpr = f"1+{ZOOM - 1:.3f}*{u}*{u}*(3-2*{u})"
        vf = (f"fps={fps},zoompan=z='{zexpr}':x='clip({cx:.1f}-iw/zoom/2,0,iw-iw/zoom)'"
              f":y='clip({cy:.1f}-ih/zoom/2,0,ih-ih/zoom)':d=1:s={W}x{H}:fps={fps}")
        _ff([*_still(scene.card_png, length, fps), "-vf", vf, "-t", f"{length:.3f}", *ENC, str(out)])
        return out
    vf = f"scale={W}:{H}" if scale != 1 else "null"
    _ff([*_still(scene.card_png, length, fps), "-vf", vf, "-t", f"{length:.3f}", *ENC, str(out)])
    return out


def _blank_png(plan: RenderPlan, out_dir: Path) -> Path:
    """A fully transparent frame for the gaps between caption pages.

    The color source only carries alpha when the chain negotiates an alpha format,
    so format=rgba has to sit right behind it. Without that, black@0.0 quietly
    becomes opaque black and the caption track blacks out every frame between
    captions. That happened, and the test now checks a pixel for it."""
    blank = out_dir / "caption_blank.png"
    _ff(["-f", "lavfi", "-i", f"color=c=black@0.0:s={plan.width}x{plan.height}:r=1,format=rgba",
             "-frames:v", "1", "-pix_fmt", "rgba", str(blank)])
    return blank


def pixel_rgba(path: str | Path, x: int, y: int, seek: float | None = None) -> tuple[int, int, int, int]:
    """One pixel of an image or a video frame, for tests that check what is on screen."""
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
    if seek is not None:
        args += ["-ss", f"{seek:.3f}"]
    # format=rgba first: a 1 by 1 crop straight off 4:2:0 video fails, since chroma
    # is stored at half resolution and the crop would be smaller than one chroma sample.
    args += ["-i", str(path), "-frames:v", "1", "-vf", f"format=rgba,crop=1:1:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    raw = subprocess.run(args, capture_output=True, check=True).stdout[:4]
    if len(raw) != 4:
        raise RuntimeError(f"No video frame decoded from {path} at {seek if seek is not None else 0:g}s")
    return tuple(raw)  # type: ignore[return-value]


def _caption_concat(pages: list[dict], plan: RenderPlan, out_dir: Path, total: float) -> Path | None:
    """One concat stream of caption PNGs with transparent gaps, so the join has a
    single overlay input however many pages there are."""
    pages = sorted((p for p in pages if p.get("png") and Path(p["png"]).exists()), key=lambda p: p["start"])
    if not pages:
        return None
    blank = _blank_png(plan, out_dir)
    entries: list[tuple[str, float]] = []
    cursor = 0.0
    for i, p in enumerate(pages):
        start = max(float(p["start"]), cursor)
        end = max(float(p["end"]), start + 1 / plan.fps)
        if start > cursor:
            entries.append((str(blank), start - cursor))
        # Concat inputs must share dimensions and pixel format. Switching between
        # RGB caption PNGs and the RGBA gap frame reinitializes the filter graph,
        # discarding the scene transitions and cutting the video stream short.
        caption = out_dir / f"caption_page_{i}.png"
        _ff(["-i", str(p["png"]), "-vf",
             f"format=rgba,crop=w='min(iw,{plan.width})':h='min(ih,{plan.height})':x=0:y=0,"
             f"pad={plan.width}:{plan.height}:0:0:color=black@0",
             "-frames:v", "1", "-pix_fmt", "rgba", str(caption)])
        entries.append((str(caption), end - start))
        cursor = end
    if cursor < total:
        entries.append((str(blank), total - cursor))
    lines = ["ffconcat version 1.0"]
    for f, dur in entries:
        lines += [f"file '{f}'", f"duration {dur:.4f}"]
    lines.append(f"file '{entries[-1][0]}'")
    path = out_dir / "captions.ffconcat"
    path.write_text("\n".join(lines) + "\n")
    return path


def compose(plan: RenderPlan, out_dir: Path, caption_pages: list[dict] | None = None) -> RenderPlan:
    """Render every scene, join them, overlay captions, mux the voice. Sets and
    returns plan.output_path."""
    if not plan.scenes:
        raise ValueError("plan has no scenes")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    d, lengths, offsets = _timing(plan)
    total = sum(d)
    clips = [_render_scene(plan, s, lengths[i], out_dir, i) for i, s in enumerate(plan.scenes)]

    args: list[str] = []
    for c in clips:
        args += ["-i", str(c)]
    n = len(clips)
    filters: list[str] = []
    prev = "0:v"
    for i in range(1, n):
        name = plan.scenes[i].transition_in
        name = "fade" if name == "none" else name
        filters.append(f"[{prev}][{i}:v]xfade=transition={name}:duration={_t_for(plan.scenes[i].transition_in):.3f}"
                       f":offset={offsets[i - 1]:.3f}[x{i}]")
        prev = f"x{i}"
    video = prev

    concat = _caption_concat(caption_pages or [], plan, out_dir, total)
    cap_idx = None
    if concat:
        cap_idx = n
        args += ["-f", "concat", "-safe", "0", "-i", str(concat)]
        filters.append(f"[{cap_idx}:v]fps={plan.fps},format=rgba[cap]")
        filters.append(f"[{video}][cap]overlay=0:0:eof_action=pass[vcap]")
        video = "vcap"
    filters.append(f"[{video}]format=yuv420p[out]")

    audio_idx = n + (1 if concat else 0)
    if plan.voice and Path(plan.voice.audio_path).exists():
        args += ["-i", str(plan.voice.audio_path)]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]

    out = out_dir / "rebuttal.mp4"
    _ff([*args, "-filter_complex", ";".join(filters), "-map", "[out]", "-map", f"{audio_idx}:a",
         "-t", f"{total:.3f}", *ENC, "-r", str(plan.fps), "-c:a", "aac", "-b:a", "160k",
         "-movflags", "+faststart", str(out)])
    plan.output_path = str(out)
    return plan
