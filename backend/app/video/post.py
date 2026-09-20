"""
Post: sound effects on the cuts, and the optional split screen.

Both are explicit toggles on the plan (plan.sfx, plan.brainrot), supplied by the
API or CLI. They are part of the artifact identity and stay fixed for each job.

Sound effects are synthesized by ffmpeg from nothing: a whoosh from shaped noise, a
low thud from a decaying sine, a short pop from high noise. Nothing is downloaded
and nothing is licensed. A whoosh fires on every scene change, a pop when the study
badges settle on the paper, a thud when the finding card lands.

The split screen is the short-form "eyes busy" layout: the rebuttal in the top 760
pixels over a blurred zoomed copy of itself, and a muted looping gameplay clip in the
bottom 520 pixels. The clip is plan.gameplay_path. Subway Surfers footage is
copyrighted by its maker, so nothing is fetched or bundled here, drop in a clip you
have the rights to. Without one, a procedural Mandelbrot zoom stands in, which is
hypnotic enough to prove the layout.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.video.plan import RenderPlan
from app.video.runtime import ff as _ff

TOP_H = 760
SFX_GAIN = {"whoosh": 0.55, "thud": 0.9, "pop": 0.5}




def _flag(env: str, default: bool) -> bool:
    raw = os.environ.get(env)
    if raw is None:
        return default
    return raw.strip() == "1"


def synth_sfx(sfx_dir: Path) -> dict[str, Path]:
    """Three sounds, mono, 48 kHz, each under half a second. Skips any that exist."""
    sfx_dir.mkdir(parents=True, exist_ok=True)
    paths = {name: sfx_dir / f"{name}.wav" for name in SFX_GAIN}
    if not paths["whoosh"].exists():
        _ff(["-f", "lavfi", "-i", "aevalsrc=exprs='(random(0)-0.5)*2':s=48000:d=0.45",
             "-af", "lowpass=f=3500,highpass=f=250,"
                    "volume='if(lt(t,0.05),t/0.05,pow(max(1-(t-0.05)/0.4,0),2))':eval=frame,"
                    "aformat=channel_layouts=mono", str(paths["whoosh"])])
    if not paths["thud"].exists():
        _ff(["-f", "lavfi", "-i", "sine=f=70:d=0.35:r=48000",
             "-af", "volume='pow(max(1-t/0.3,0),3)*1.6':eval=frame,lowpass=f=220,aformat=channel_layouts=mono",
             str(paths["thud"])])
    if not paths["pop"].exists():
        _ff(["-f", "lavfi", "-i", "aevalsrc=exprs='(random(0)-0.5)*2':s=48000:d=0.08",
             "-af", "highpass=f=1500,volume='pow(max(1-t/0.07,0),2)*0.7':eval=frame,aformat=channel_layouts=mono",
             str(paths["pop"])])
    return paths


def cues(plan: RenderPlan) -> list[tuple[str, float]]:
    """When each sound fires, in seconds from the start of the video."""
    out: list[tuple[str, float]] = []
    for scene in plan.scenes[1:]:
        out.append(("whoosh", scene.start))
    for scene in plan.scenes:
        if scene.kind == "finding":
            out.append(("thud", scene.start))
        if scene.kind == "paper":
            # The badges settle where the push-in ends, 60 percent through the scene.
            out.append(("pop", scene.start + 0.6 * max(scene.end - scene.start, 0.2)))
    return sorted(out, key=lambda c: c[1])


def add_sfx(src: Path, dst: Path, plan: RenderPlan, sfx_dir: Path) -> None:
    """Mix the cues over the existing track. The video stream is copied, not re-encoded."""
    paths = synth_sfx(sfx_dir)
    cue_list = cues(plan)
    if not cue_list:
        dst.write_bytes(src.read_bytes())
        return
    args = ["-i", str(src)]
    for name, _ in cue_list:
        args += ["-i", str(paths[name])]
    filters = []
    labels = []
    for i, (name, at) in enumerate(cue_list, start=1):
        filters.append(f"[{i}:a]adelay={int(round(at * 1000))}:all=1,volume={SFX_GAIN[name]}[s{i}]")
        labels.append(f"[s{i}]")
    filters.append(f"[0:a]{''.join(labels)}amix=inputs={len(cue_list) + 1}:normalize=0:dropout_transition=0[a]")
    _ff([*args, "-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[a]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(dst)])


def add_brainrot(src: Path, dst: Path, plan: RenderPlan) -> str:
    """Stack the rebuttal over a gameplay pane. Returns a note about the pane source."""
    W, H, fps = plan.width, plan.height, plan.fps
    bot_h = H - TOP_H
    if plan.gameplay_path and Path(plan.gameplay_path).exists():
        game = ["-stream_loop", "-1", "-i", str(plan.gameplay_path)]
        note = f"gameplay from {Path(plan.gameplay_path).name}"
    else:
        game = ["-f", "lavfi", "-i", f"mandelbrot=s={W}x{bot_h}:rate={fps}"]
        note = "no gameplay clip on the plan, Mandelbrot zoom used as the stand-in"
    filters = [
        "[0:v]split[fg][bgsrc]",
        f"[bgsrc]scale={W}:{TOP_H}:force_original_aspect_ratio=increase,crop={W}:{TOP_H},boxblur=20:4,eq=brightness=-0.15[bg]",
        f"[fg]scale={W}:{TOP_H}:force_original_aspect_ratio=decrease[fgs]",
        "[bg][fgs]overlay=(W-w)/2:(H-h)/2[top]",
        f"[1:v]fps={fps},scale={W}:{bot_h}:force_original_aspect_ratio=increase,crop={W}:{bot_h},setsar=1[bot]",
        "[top][bot]vstack=inputs=2,format=yuv420p[out]",
    ]
    # crf 23, not lower: the bottom pane is busy by design and the file balloons otherwise.
    _ff(["-i", str(src), *game, "-filter_complex", ";".join(filters), "-map", "[out]", "-map", "0:a",
         "-t", f"{plan.duration:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-threads", "2", "-r", str(fps),
         "-c:a", "copy", "-movflags", "+faststart", str(dst)])
    return note


def apply(plan: RenderPlan, out_dir: Path) -> RenderPlan:
    """Run whichever toggles are on, in order, and point plan.output_path at the result."""
    if not plan.output_path or not Path(plan.output_path).exists():
        raise RuntimeError("plan.output_path is missing, run compose first")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sfx = plan.sfx
    brainrot = plan.brainrot
    # Output names derive from the input name, so applying a stage to a file that
    # already went through it never asks ffmpeg to overwrite its own input.
    current = Path(plan.output_path)
    if sfx:
        dst = out_dir / f"{current.stem}_sfx.mp4"
        add_sfx(current, dst, plan, out_dir / "sfx")
        current = dst
    if brainrot:
        dst = out_dir / f"{current.stem}_brainrot.mp4"
        add_brainrot(current, dst, plan)
        current = dst
    plan.output_path = str(current)
    return plan
