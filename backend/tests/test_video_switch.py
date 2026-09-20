"""Regressions for reconciling the former renderer switch with one worker contract."""
from collections import Counter

from app import pipeline, video
from app.main import app


def test_worker_uses_the_single_staged_entrypoint():
    assert pipeline.render_video is video.render_video


def test_no_duplicate_api_method_paths():
    pairs = [(method, route.path) for route in app.routes for method in getattr(route, 'methods', [])]
    assert not [pair for pair, count in Counter(pairs).items() if count > 1]
