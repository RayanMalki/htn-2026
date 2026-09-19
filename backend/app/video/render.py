"""
The orchestrator. One call takes a finished case to a rebuttal MP4.

    case (stored result) -> script -> voice -> captions -> cards -> compose -> post

Each stage reads and writes the shared RenderPlan in plan.py and knows nothing about
the others, so any one of them can be swapped or run alone. This module is the only
place the order lives. Stage modules are imported inside the function so that an
unfinished or missing stage fails with a clear message at render time, not at import
time for the whole app.

Command line, for pre-rendering the demo videos before judging:

    python -m app.video.render path/to/case.json out/dir [--brainrot] [--no-sfx]
        [--gameplay clip.mp4] [--source-clip original.mp4]

The plan is saved next to the output as plan.json so a render can be inspected or
replayed without rerunning the pipeline.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from app.video.plan import RenderPlan

# Where renders go. Self-contained on purpose so the video package never depends on
# the app's settings and can run from the command line before the app is up.
RENDER_ROOT = Path(os.environ.get("HYPECHECK_RENDER_DIR", "data/renders"))


def render_case(
    case: dict,
    out_dir: Path,
    *,
    sfx: bool = True,
    brainrot: bool = False,
    gameplay_path: str | None = None,
    source_clip: str | None = None,
    log=print,
) -> RenderPlan:
    """Run every stage in order and return the finished plan with output_path set."""
    from app.video import captions, cards, compose, post, script, voice

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    marks: list[tuple[str, float]] = []

    def stage(name: str):
        marks.append((name, time.time()))
        log(f"  {name}")

    stage("script")
    plan = script.build_plan(case, out_dir)
    plan.sfx = sfx
    plan.brainrot = brainrot
    plan.gameplay_path = gameplay_path
    if source_clip:
        plan.source_clip = str(source_clip)

    stage("voice")
    plan = voice.synthesize(plan, out_dir)

    stage("captions")
    pages = captions.pages(plan)

    stage("cards")
    plan = cards.render_cards(plan, out_dir)
    pages = cards.render_caption_pages(pages, plan, out_dir)

    stage("compose")
    plan = compose.compose(plan, out_dir, pages)

    stage("post")
    plan = post.apply(plan, out_dir)

    plan.save(out_dir / "plan.json")
    total = time.time() - marks[0][1]
    log(f"  done in {total:.1f}s -> {plan.output_path}")
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a rebuttal video from a stored case.")
    parser.add_argument("case_json", help="path to the case result as JSON")
    parser.add_argument("out_dir", help="where the plan, cards, audio and MP4 go")
    parser.add_argument("--brainrot", action="store_true", help="split screen with a gameplay pane")
    parser.add_argument("--no-sfx", action="store_true", help="skip the synthesized sound effects")
    parser.add_argument("--gameplay", default=None, help="clip for the bottom pane, one you have rights to")
    parser.add_argument("--source-clip", default=None, help="the original video file, if downloaded")
    args = parser.parse_args()

    case = json.loads(Path(args.case_json).read_text())
    plan = render_case(
        case,
        Path(args.out_dir),
        sfx=not args.no_sfx,
        brainrot=args.brainrot,
        gameplay_path=args.gameplay,
        source_clip=args.source_clip,
    )
    print(plan.output_path)


if __name__ == "__main__":
    main()
