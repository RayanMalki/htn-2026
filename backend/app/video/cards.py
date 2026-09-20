from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from app.video.plan import RenderPlan

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FRONTEND = REPO / "frontend"
SCRIPT = HERE / "cards.mjs"


class CardsUnavailable(RuntimeError):
    """Raised when the browser toolchain is not present. Tests skip on this."""


def find_playwright(install: bool = True) -> Path:
    """Locate the preinstalled browser package; never install during a job."""
    override = os.environ.get("HYPECHECK_PLAYWRIGHT_DIR")
    candidates = [Path(override)] if override else []
    candidates += [HERE / "node_modules" / "playwright", FRONTEND / "node_modules" / "@playwright" / "test", FRONTEND / "node_modules" / "playwright"]
    for c in candidates:
        if (c / "package.json").exists():
            return c
    raise CardsUnavailable(
        "Playwright is not available. Install the frontend's node modules (cd frontend && npm ci) "
        "or point HYPECHECK_PLAYWRIGHT_DIR at a node_modules/playwright directory."
    )


def _require_node() -> str:
    node = shutil.which("node")
    if not node:
        raise CardsUnavailable("node is not installed, and the cards are rendered by a headless browser driven from node.")
    return node


def _run(spec: dict, out_dir: Path) -> dict:
    node = _require_node()
    pw = find_playwright()
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / "cards_spec.json"
    spec_path.write_text(json.dumps(spec))
    proc = subprocess.run([node, str(SCRIPT), str(pw), str(spec_path)], capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"card rendering failed: {proc.stderr.strip()[-600:]}")
    last = proc.stdout.strip().splitlines()[-1]
    return json.loads(last)


def _card_spec(scene_id: str, card) -> dict:
    d = card.model_dump()
    d["id"] = scene_id
    return d


def render_cards(plan: RenderPlan, out_dir: Path) -> RenderPlan:
    """Render one PNG per scene at the plan size. Paper scenes also get a focus_box,
    the pixel box of the highlighted sentence in plan coordinates."""
    spec = {
        "width": plan.width, "height": plan.height, "out_dir": str(out_dir.resolve()),
        "cards": [_card_spec(f"s{i}", s.card) for i, s in enumerate(plan.scenes)],
        "captions": [],
    }
    result = _run(spec, out_dir)
    by_id = {c["id"]: c for c in result["cards"]}
    for i, scene in enumerate(plan.scenes):
        got = by_id.get(f"s{i}")
        if not got:
            continue
        scene.card_png = got["png"]
        if scene.kind == "paper" and got.get("focus_box"):
            scene.focus_box = {k: float(v) for k, v in got["focus_box"].items()}
    return plan


def render_caption_pages(pages: list[dict], plan: RenderPlan, out_dir: Path) -> list[dict]:
    """Each page is a dict with at least "text" and a "start" and "end" in seconds.
    An optional "emphasis" is the index of the word to colour. Returns the same
    dicts with a "png" path added."""
    if not pages:
        return pages
    spec = {
        "width": plan.width, "height": plan.height, "out_dir": str(out_dir.resolve()),
        "caption_y": 760 if plan.brainrot else round(plan.height * 0.67),
        "cards": [],
        "captions": [{"id": f"c{i}", "text": p.get("text", ""), "emphasis": p.get("emphasis")} for i, p in enumerate(pages)],
    }
    result = _run(spec, out_dir)
    by_id = {c["id"]: c["png"] for c in result["captions"]}
    for i, p in enumerate(pages):
        if f"c{i}" in by_id:
            p["png"] = by_id[f"c{i}"]
    return pages
