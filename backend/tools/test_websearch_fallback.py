"""
Tests for the web-search fallback. No network. Run: python3 test_websearch_fallback.py

Covers the guard, the mock shape, and the parser against a hand-written body in
the exact shape the Responses API documentation specifies (web_search_call item,
message item with output_text and url_citation annotations).
"""

import json
import unittest
from unittest import mock

import websearch_fallback as wf


def studies(*stances):
    return [{"stance": s, "title": f"study {i}"} for i, s in enumerate(stances)]


# The documented output shape, written by hand from the docs so the parser is
# proven against it without spending a key. Includes one citation outside the
# allowlist (must be dropped) and a numeric score (must be stripped).
DOCUMENTED_BODY = {
    "id": "resp_123",
    "model": "gpt-5.6-terra",
    "output": [
        {
            "type": "web_search_call",
            "id": "ws_1",
            "status": "completed",
            "action": {"type": "search", "queries": ["alkaline water cancer WHO", "alkaline diet cancer evidence"]},
        },
        {
            "type": "message",
            "id": "msg_1",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": json.dumps({
                    "stance": "contradicts",
                    "paragraph": "Public-health sources do not support it [1]. Blood pH is tightly regulated [2].",
                    "citations": [
                        {"url": "https://www.cdc.gov/cancer/risk-factors/", "title": "Cancer risk factors",
                         "publisher": "Centers for Disease Control and Prevention",
                         "quote": "There is no evidence that alkaline water prevents cancer."},
                        {"url": "https://www.nhs.uk/live-well/", "title": "Diet myths",
                         "publisher": "", "quote": "Your body controls blood pH on its own."},
                        {"url": "https://randomwellnessblog.example/alkaline", "title": "Alkaline miracle",
                         "publisher": "A blog", "quote": "Alkaline water cures everything."},
                    ],
                    "confidence_note": "Two public-health pages, no trial data.",
                    "score": 4,
                }),
                "annotations": [
                    {"type": "url_citation", "url": "https://www.cdc.gov/cancer/risk-factors/",
                     "title": "Cancer risk factors", "start_index": 0, "end_index": 40},
                    {"type": "url_citation", "url": "https://www.who.int/news-room/fact-sheets/cancer",
                     "title": "Cancer fact sheet", "start_index": 41, "end_index": 80},
                ],
            }],
        },
    ],
    "usage": {"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500},
}


class GuardTests(unittest.TestCase):
    def test_fires_on_zero_studies(self):
        self.assertTrue(wf.should_fallback([]))
        self.assertTrue(wf.should_fallback({"studies": []}))

    def test_fires_on_one_study(self):
        self.assertTrue(wf.should_fallback(studies("supports")))

    def test_fires_when_all_unclear(self):
        self.assertTrue(wf.should_fallback(studies("unclear", "unclear", "unclear")))
        # the team backend spells it uncertain
        self.assertTrue(wf.should_fallback(studies("uncertain", "uncertain")))

    def test_does_not_fire_on_two_clear_studies(self):
        self.assertFalse(wf.should_fallback(studies("supports", "contradicts")))
        self.assertFalse(wf.should_fallback(studies("supports", "supports", "unclear")))

    def test_search_and_write_returns_none_when_papers_exist(self):
        # the guard sits inside the function, so a real key must never reach the network
        with mock.patch.object(wf.urllib.request, "urlopen", side_effect=AssertionError("network was called")):
            self.assertIsNone(wf.search_and_write("claim", studies("supports", "contradicts"), api_key="sk-fake"))


class MockShapeTests(unittest.TestCase):
    def test_mock_has_the_full_shape(self):
        result = wf.search_and_write("Alkaline water prevents cancer", [], api_key=None)
        for key in ("source_badge", "badge_text", "stance", "paragraph", "citations",
                    "confidence_note", "queries", "model", "mode", "usage", "estimated_cost_usd"):
            self.assertIn(key, result)
        self.assertEqual(result["mode"], "mock")
        self.assertEqual(result["source_badge"], "web_sources")
        self.assertIn("not the primary literature", result["badge_text"])
        self.assertIn(result["stance"], wf.STANCES)
        self.assertTrue(result["citations"])
        for c in result["citations"]:
            self.assertTrue(wf._allowed(c["url"]), c["url"])
            for k in ("url", "title", "publisher", "quote"):
                self.assertIn(k, c)
        self.assertNotIn("score", result)


class ParseTests(unittest.TestCase):
    def test_parses_documented_shape(self):
        result = wf.parse_response(DOCUMENTED_BODY)
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["stance"], "contradicts")
        self.assertIn("[1]", result["paragraph"])
        self.assertEqual(result["queries"], ["alkaline water cancer WHO", "alkaline diet cancer evidence"])
        self.assertEqual(result["model"], "gpt-5.6-terra")

    def test_drops_citations_outside_allowlist(self):
        urls = [c["url"] for c in wf.parse_response(DOCUMENTED_BODY)["citations"]]
        self.assertNotIn("https://randomwellnessblog.example/alkaline", urls)
        self.assertIn("https://www.cdc.gov/cancer/risk-factors/", urls)
        self.assertIn("https://www.nhs.uk/live-well/", urls)

    def test_folds_in_annotation_citations_without_duplicates(self):
        urls = [c["url"] for c in wf.parse_response(DOCUMENTED_BODY)["citations"]]
        self.assertEqual(urls.count("https://www.cdc.gov/cancer/risk-factors/"), 1)
        self.assertIn("https://www.who.int/news-room/fact-sheets/cancer", urls)

    def test_fills_publisher_from_domain(self):
        by_url = {c["url"]: c for c in wf.parse_response(DOCUMENTED_BODY)["citations"]}
        self.assertEqual(by_url["https://www.nhs.uk/live-well/"]["publisher"], "National Health Service")

    def test_strips_numeric_score(self):
        result = wf.parse_response(DOCUMENTED_BODY)
        self.assertNotIn("score", result)
        self.assertNotIn("score", json.dumps(result))

    def test_estimates_cost_from_usage(self):
        cost = wf.parse_response(DOCUMENTED_BODY)["estimated_cost_usd"]
        # 1200 in at 2 per million plus 300 out at 12 per million
        self.assertAlmostEqual(cost, (1200 * 2 + 300 * 12) / 1_000_000, places=6)

    def test_unknown_stance_with_no_citations_is_insufficient(self):
        body = {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"stance": "maybe"}', "annotations": []}]}]}
        self.assertEqual(wf.parse_response(body)["stance"], "insufficient")

    def test_request_body_matches_documented_tool_shape(self):
        body = wf._request_body("claim", [])
        self.assertEqual(body["model"], wf.MODEL)
        tool = body["tools"][0]
        self.assertEqual(tool["type"], "web_search")
        self.assertIn(tool["search_context_size"], ("low", "medium", "high"))
        self.assertEqual(tool["filters"]["allowed_domains"], wf.ALLOWED_DOMAINS)
        self.assertIn("web_search_call.action.sources", body["include"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
