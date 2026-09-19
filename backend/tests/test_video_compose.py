"""
The video compositor and post stages, tested the way continuous integration can run
them: ffmpeg is installed there, node and a browser are not. Cards are colour blocks
from ffmpeg here, the browser path is exercised in a second test that skips when the
toolchain is absent.
"""

import shutil
import subprocess
import time

import pytest

from app.video import cards, compose, post
from app.video.plan import Badge, Card, Finding, RenderPlan, Scene, Voice


def _png(path, colour, w=720, h=1280):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"color=c={colour}:s={w}x{h}:r=1", "-frames:v", "1", str(path)], check=True)
    return str(path)


def _silence(path, seconds):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", "anullsrc=r=48000:cl=mono", "-t", str(seconds), str(path)], check=True)
    return str(path)


def _clip(path, seconds, w=320, h=240):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=s={w}x{h}:r=30", "-t", str(seconds), "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _plan(tmp_path):
    scenes = [
        Scene(kind="clip", start=0, end=2, narration="one", transition_in="none",
              card=Card(kind="clip", title="Blue light is not ruining your sleep")),
        Scene(kind="paper", start=2, end=4, narration="two", transition_in="smoothup",
              card=Card(kind="paper", title="A paper", body=["Some results."], highlight="Some results.",
                        badges=[Badge(label="Design", value="Randomized trial")]),
              focus_box={"x": 100, "y": 400, "w": 400, "h": 40}),
        Scene(kind="finding", start=4, end=6, narration="three", transition_in="circleopen",
              card=Card(kind="finding", title="Partly right.")),
    ]
    plan = RenderPlan(case_id="test", claim="Blue light is not ruining your sleep", scenes=scenes,
                      finding=Finding(label="mixed", sentence="Partly right.", supports=2, contradicts=5),
                      voice=Voice(audio_path=_silence(tmp_path / "voice.wav", 6), duration=6.0, engine="silent"))
    colours = ["0x223344", "0xfffdf8", "0xf4efe6"]
    for i, s in enumerate(plan.scenes):
        s.card_png = _png(tmp_path / f"card{i}.png", colours[i])
    return plan


def test_compose_then_post_produces_correct_videos(tmp_path):
    plan = _plan(tmp_path)
    pages = [
        {"start": 0.5, "end": 1.5, "text": "one", "png": _png(tmp_path / "cap0.png", "yellow", 400, 100)},
        {"start": 2.5, "end": 3.5, "text": "two", "png": _png(tmp_path / "cap1.png", "yellow", 400, 100)},
    ]
    t = time.time()
    plan = compose.compose(plan, tmp_path / "out", pages)
    assert plan.output_path and plan.output_path.endswith("rebuttal.mp4")
    assert compose.probe_size(plan.output_path) == (720, 1280)
    assert abs(compose.probe_duration(plan.output_path) - 6.0) < 0.3
    # The gap frame between captions must be transparent, and the picture must be
    # visible between captions. An opaque gap once blacked out the whole video.
    assert compose.pixel_rgba(tmp_path / "out" / "caption_blank.png", 360, 640)[3] == 0
    r, g, b, _ = compose.pixel_rgba(plan.output_path, 360, 640, seek=1.8)
    assert r + g + b > 60, f"frame between captions is black: {(r, g, b)}"
    r, g, b, _ = compose.pixel_rgba(plan.output_path, 360, 640, seek=5.0)
    assert r + g + b > 400, f"finding card frame is not the light card: {(r, g, b)}"

    plan.sfx = True
    plan.brainrot = True
    plan.gameplay_path = _clip(tmp_path / "game.mp4", 6)
    plan = post.apply(plan, tmp_path / "out")
    assert plan.output_path.endswith("rebuttal_sfx_brainrot.mp4")
    assert (tmp_path / "out" / "rebuttal_sfx.mp4").exists()
    assert compose.probe_size(plan.output_path) == (720, 1280)
    assert abs(compose.probe_duration(plan.output_path) - 6.0) < 0.4
    assert time.time() - t < 30, "compose plus post should stay well under half a minute for 6 seconds of video"


def test_post_cues_land_on_scene_changes(tmp_path):
    plan = _plan(tmp_path)
    got = post.cues(plan)
    names = [n for n, _ in got]
    assert names.count("whoosh") == 2 and "thud" in names and "pop" in names
    assert ("thud", 4.0) in got
    assert any(n == "pop" and abs(at - 3.2) < 0.01 for n, at in got)


def test_env_flags_override_the_plan(monkeypatch):
    monkeypatch.setenv("SFX", "0")
    monkeypatch.setenv("BRAINROT", "1")
    assert post._flag("SFX", True) is False
    assert post._flag("BRAINROT", False) is True
    monkeypatch.delenv("SFX")
    assert post._flag("SFX", True) is True


def test_browser_cards_render_with_focus_box(tmp_path):
    if not shutil.which("node"):
        pytest.skip("node is not installed here, the browser card path is tested locally")
    try:
        cards.find_playwright(install=False)
    except cards.CardsUnavailable as exc:
        pytest.skip(str(exc))
    plan = RenderPlan(case_id="cards", claim="Blue light is not ruining your sleep", scenes=[
        Scene(kind="paper", start=0, end=3, card=Card(
            kind="paper", eyebrow="Journal of Applied Physiology, 2011", title="Blue light from LEDs elicits a dose-dependent suppression of melatonin in humans",
            highlight_section="Results",
            body=["Light suppresses melatonin in humans, with the strongest response occurring in the short-wavelength portion of the spectrum between 446 and 477 nm that appears blue.",
                  "Blue monochromatic light suppressed melatonin in a dose-dependent manner."],
            highlight="Blue monochromatic light suppressed melatonin in a dose-dependent manner.",
            badges=[Badge(label="Design", value="Randomized trial"), Badge(label="People", value="Humans"), Badge(label="Year", value="2011")],
            footer="West et al., PubMed 21164152")),
        Scene(kind="finding", start=3, end=6, card=Card(kind="finding", title="Partly right. Brightness matters, and so does colour.",
                                                        badges=[Badge(label="Support", value="2"), Badge(label="Contradict", value="5")])),
    ])
    plan = cards.render_cards(plan, tmp_path / "cards")
    assert plan.scenes[0].card_png and compose.probe_size(plan.scenes[0].card_png) == (1440, 2560)
    assert plan.scenes[1].card_png and compose.probe_size(plan.scenes[1].card_png) == (720, 1280)
    fb = plan.scenes[0].focus_box
    assert fb and fb["w"] > 50 and 0 < fb["y"] < 1280 * 0.75
    pages = cards.render_caption_pages([{"start": 0, "end": 1, "text": "on day seven", "emphasis": 2}], plan, tmp_path / "cards")
    assert pages[0]["png"] and compose.probe_size(pages[0]["png"]) == (720, 1280)
