"""
Where can this go wrong. Tests for the ways the evidence pipeline breaks on logic,
inputs, robustness, and speed. Every FAIL here is a finding, not an embarrassment.

Run: python3 test_failure_modes.py            (network tests on)
     NETWORK=0 python3 test_failure_modes.py  (offline only, about 1 second)

No pytest on this machine, so a small runner at the bottom collects every
function named test_* and reports PASS, FAIL or SKIP with the reason.
"""

from __future__ import annotations

import os
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

import paper_authorship as pa
import resolver
from weigh import Study, weigh

NETWORK = os.environ.get("NETWORK", "1") == "1"
EMAIL = "ezekieljoseph2005@gmail.com"

# Every run starts with an empty cache, so the offline tests that count network
# calls see the real chain and never a cached answer from a previous run.
resolver.CACHE_PATH = Path(tempfile.mkdtemp()) / "cache.db"


class Skip(Exception):
    pass


# ------------------------------------------------------------------ logic: weighing

def test_cherry_pick_one_agreeing_review_does_not_win():
    """This morning's bug. One review that agrees must not beat five trials that disagree."""
    studies = [Study("review", "supports", "systematic review", "human")]
    studies += [Study(f"rct{i}", "contradicts", "randomized controlled trial", "human") for i in range(5)]
    v = weigh(studies)
    assert v.label != "supported", f"cherry-pick got through: {v.label}, {v.reason}"
    assert v.label == "contradicted", v.reason


def test_one_mouse_study_cannot_outrank_eight_human_studies():
    studies = [Study("mouse", "supports", "randomized controlled trial", "animal")]
    studies += [Study(f"h{i}", "contradicts", "randomized controlled trial", "human") for i in range(8)]
    v = weigh(studies)
    assert v.label == "contradicted", v.reason


def test_single_paper_on_a_side_cannot_win_outright():
    """Even a Cochrane review alone against one weak study is mixed, not a win. Two independent sources to call it."""
    v = weigh([Study("c", "supports", "cochrane", "human"), Study("cr", "contradicts", "case report", "human")])
    assert v.label == "mixed", v.reason


def test_balanced_sides_are_mixed_not_unclear():
    studies = [Study(f"s{i}", "supports", "randomized controlled trial") for i in range(3)]
    studies += [Study(f"c{i}", "contradicts", "randomized controlled trial") for i in range(3)]
    v = weigh(studies)
    assert v.label == "mixed", v.reason


def test_zero_or_one_study_is_insufficient_not_a_verdict():
    assert weigh([]).label == "insufficient"
    assert weigh([Study("only", "contradicts", "meta-analysis")]).label == "insufficient"


def test_all_unclear_is_unclear_and_distinct_from_insufficient():
    v = weigh([Study(f"u{i}", "unclear", "randomized controlled trial") for i in range(4)])
    assert v.label == "unclear", v.reason


def test_retracted_studies_are_ignored_and_counted_as_ignored():
    studies = [Study("r1", "supports", "meta-analysis", retracted=True), Study("r2", "supports", "meta-analysis", retracted=True)]
    studies += [Study("c1", "contradicts", "randomized controlled trial"), Study("c2", "contradicts", "randomized controlled trial")]
    v = weigh(studies)
    assert v.label == "contradicted", v.reason
    assert v.retracted_ignored == 2


def test_blue_light_video_lands_mixed_not_supported():
    """The real case from today, with the stances we found in the papers."""
    studies = [
        Study("Wood 2013", "supports", "clinical trial", access="abstract_only"),
        Study("Silvani 2022", "supports", "systematic review", access="full_text"),
        Study("West 2011", "contradicts", "randomized controlled trial", access="full_text"),
        Study("Brainard 2001", "contradicts", "clinical trial", access="full_text"),
        Study("Thapan 2001", "contradicts", "clinical trial", access="full_text"),
        Study("Gooley 2010", "contradicts", "randomized controlled trial", access="full_text"),
        Study("Chinoy 2018", "contradicts", "randomized controlled trial", access="full_text"),
        Study("Cajochen 2011", "unclear", "clinical trial", access="abstract_only"),
    ]
    v = weigh(studies)
    assert v.label == "mixed", f"expected mixed, got {v.label}: {v.reason}"
    assert v.full_text == 6 and v.abstract_only == 2, (v.full_text, v.abstract_only)
    assert v.strongest_against in ("West 2011", "Gooley 2010", "Chinoy 2018")


def test_unknown_design_and_species_do_not_crash():
    v = weigh([Study("a", "supports", "weird thing", "martian"), Study("b", "supports", "", "")])
    assert v.label in ("supported", "mixed", "insufficient")


# ------------------------------------------------------------------ logic: resolver, offline

def test_match_guard_rejects_wrong_year_and_author():
    rec = {"pubYear": "2021", "authorString": "Smith J, Jones K."}
    assert not resolver.verify_match(rec, want_year=2001, want_author="Smith"), "2021 accepted for a 2001 claim"
    assert not resolver.verify_match(rec, want_year=2021, want_author="Brainard"), "wrong author accepted"
    assert resolver.verify_match(rec, want_year=2020, want_author="Smith"), "one year drift should pass"
    assert resolver.verify_match(rec), "no expectations should pass"
    assert not resolver.verify_match({"pubYear": "n/a"}, want_year=2001), "non-numeric year should fail"


def test_block_status_vs_dead_host_are_told_apart():
    assert resolver._is_block_status("HTTP 403")
    assert resolver._is_block_status("HTTP 429")
    assert resolver._is_block_status("HTTP 503")
    assert not resolver._is_block_status("HTTP 404")
    assert not resolver._is_block_status("<urlopen error [Errno 61] Connection refused>")
    assert not resolver._is_block_status(None)


def test_bot_wall_page_is_detected():
    assert resolver._bot_blocked(b"<html><title>Just a moment...</title>")
    assert resolver._bot_blocked(b"<p>Ray ID: abc123</p>")
    assert not resolver._bot_blocked(b"<html><title>Action spectrum for melatonin</title><p>Results</p>")


def test_dead_legacy_domain_gets_a_modern_candidate():
    c = resolver._candidate_urls("http://intl-jap.physiology.org/cgi/content/full/110/3/619", "10.1152/x.2009")
    assert len(c) == 2 and c[1] == "https://journals.physiology.org/doi/full/10.1152/x.2009", c
    assert resolver._candidate_urls("https://example.org/paper", "10.1/x") == ["https://example.org/paper"]


def _patched(fake):
    """Swap resolver._get for a fake that records calls. Returns (restore, calls)."""
    calls = []
    real = resolver._get

    def stub(url, email, timeout=25.0):
        calls.append(url)
        return fake(url)
    resolver._get = stub
    return (lambda: setattr(resolver, "_get", real)), calls


def test_no_links_no_doi_no_pmcid_is_abstract_only_with_zero_requests():
    restore, calls = _patched(lambda u: (_ for _ in ()).throw(AssertionError("network call made")))
    try:
        r = resolver.resolve_fulltext({"isOpenAccess": "N", "abstractText": "x" * 300}, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert r["access_type"] == "abstract_only" and r["chars"] == 300 and calls == []


def test_subscription_only_and_abstract_style_links_are_never_fetched():
    rec = {"isOpenAccess": "N", "abstractText": "a" * 300, "fullTextUrlList": {"fullTextUrl": [
        {"availability": "Subscription required", "documentStyle": "html", "url": "https://x/sub"},
        {"availability": "Free", "documentStyle": "abs", "url": "https://x/abs"},
    ]}}
    restore, calls = _patched(lambda u: (b"<html>" + b"y" * 5000, 0.0, None))
    try:
        r = resolver.resolve_fulltext(rec, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert calls == [], f"fetched something it should not: {calls}"
    assert r["access_type"] == "abstract_only"


def test_embargo_expired_free_link_is_fetched_and_read():
    rec = {"isOpenAccess": "N", "abstractText": "a" * 300, "fullTextUrlList": {"fullTextUrl": [
        {"availability": "Free after 12 months", "documentStyle": "html", "site": "pub", "url": "https://pub/full"}]}}
    restore, calls = _patched(lambda u: (b"<html><body>" + b"real paper text " * 400 + b"</body>", 0.0, None))
    try:
        r = resolver.resolve_fulltext(rec, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert calls == ["https://pub/full"], calls
    assert r["access_type"] == "full_text" and r["chars"] > 1500, r["access_type"]


def test_free_link_behind_403_is_free_needs_browser_not_paywalled():
    rec = {"isOpenAccess": "N", "abstractText": "a" * 300, "fullTextUrlList": {"fullTextUrl": [
        {"availability": "Free", "documentStyle": "html", "site": "pub", "url": "https://pub/full"}]}}
    restore, _ = _patched(lambda u: (b"<title>Just a moment...</title>", 0.0, "HTTP 403"))
    try:
        r = resolver.resolve_fulltext(rec, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert r["access_type"] == "free_needs_browser" and r["free_url"] == "https://pub/full", r


def test_dead_host_falls_through_to_abstract_not_to_gated():
    rec = {"isOpenAccess": "N", "abstractText": "a" * 300, "fullTextUrlList": {"fullTextUrl": [
        {"availability": "Free", "documentStyle": "html", "site": "pub", "url": "https://gone/full"}]}}
    restore, _ = _patched(lambda u: (None, 0.0, "<urlopen error [Errno 61] Connection refused>"))
    try:
        r = resolver.resolve_fulltext(rec, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert r["access_type"] == "abstract_only", r["access_type"]


def test_first_mirror_blocked_second_mirror_read_gives_full_text():
    """Today's regression: Gooley was reported gated because the first mirror was blocked."""
    rec = {"isOpenAccess": "N", "abstractText": "a" * 300, "fullTextUrlList": {"fullTextUrl": [
        {"availability": "Free", "documentStyle": "html", "site": "mirror1", "url": "https://m1/full"},
        {"availability": "Free", "documentStyle": "html", "site": "mirror2", "url": "https://m2/full"}]}}

    def fake(u):
        if "m1" in u:
            return (b"<title>Just a moment</title>", 0.0, "HTTP 403")
        return (b"<html>" + b"paper text " * 400, 0.0, None)
    restore, calls = _patched(fake)
    try:
        r = resolver.resolve_fulltext(rec, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert r["access_type"] == "full_text" and "mirror2" in r["route"], r["route"]
    assert len(calls) == 2, calls


def test_second_resolve_of_the_same_paper_makes_zero_requests():
    """The cache is the fix for rate limiting and the reason a demo rerun is instant."""
    rec = {"isOpenAccess": "N", "doi": "10.9/cache-me", "abstractText": "a" * 300}
    restore, calls = _patched(lambda u: (b'{"is_oa": false}', 0.0, None))
    try:
        first = resolver.resolve_fulltext(rec, EMAIL, gap=0)
        n_first = len(calls)
        second = resolver.resolve_fulltext(rec, EMAIL, gap=0)
    finally:
        restore()
    assert n_first >= 1, "first resolve should have hit the network"
    assert len(calls) == n_first, f"second resolve made {len(calls) - n_first} requests, expected 0"
    assert second.get("cached") is True and second["access_type"] == first["access_type"]


def test_a_throttled_non_full_text_result_is_not_cached():
    """Under a 429, 'abstract only' means 'ask again later'. Caching it would lock in a wrong badge."""
    rec = {"isOpenAccess": "Y", "pmcid": "PMC_THROTTLED", "abstractText": "a" * 300}
    restore, calls = _patched(lambda u: (b"", 0.0, "HTTP 429"))
    try:
        first = resolver.resolve_fulltext(rec, EMAIL, gap=0)
        n_first = len(calls)
        resolver.resolve_fulltext(rec, EMAIL, gap=0)
    finally:
        restore()
    assert first["access_type"] == "abstract_only" and first["throttled"] is True
    assert len(calls) > n_first, "a throttled result was cached and never retried"


def test_doi_prefix_is_stripped_for_unpaywall():
    rec = {"isOpenAccess": "N", "abstractText": "a" * 300, "doi": "https://doi.org/10.1/ABC"}
    restore, calls = _patched(lambda u: (b'{"is_oa": false}', 0.0, None))
    try:
        r = resolver.resolve_fulltext(rec, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert any("api.unpaywall.org/v2/10.1/ABC?" in c for c in calls), calls
    assert "10.1/https" not in " ".join(calls) and "%2F" not in " ".join(calls), "doi was mangled"
    assert r["access_type"] == "abstract_only"


# ------------------------------------------------------------------ logic: scanner, offline

def test_scanner_survives_malformed_detector_output():
    s = pa.read_scan("p", {}, 1000)
    assert s.status == "scored" and s.ai_probability is None and s.sentences == []
    s = pa.read_scan("p", {"sentences": [{"sentence": "x", "generated_prob": "high"}, {"generated_prob": 0.5}],
                            "class_probabilities": {"ai": "lots"}}, 1000)
    assert s.sentences == [] and s.ai_probability is None
    s = pa.read_scan("p", {"sentences": [{"sentence": "x", "generated_prob": 0.5}] * 500,
                            "paragraphs": [{"completely_generated_prob": 0.3}] * 100}, 1000)
    assert len(s.sentences) == 200 and len(s.paragraphs) == 40, "caps not applied"


def test_scanner_no_key_and_too_short_are_skipped_never_raised():
    assert pa.scan_paper("p", "x" * 5000, None).status == "skipped"
    assert pa.scan_paper("p", "short", "some-key").status == "skipped"


def test_scanner_detector_outage_is_unavailable_not_a_crash():
    real = pa._predict
    pa._predict = lambda text, key, timeout=25.0: (_ for _ in ()).throw(urllib.error.URLError("down"))
    try:
        s = pa.scan_paper("p", "x" * 5000, "key")
    finally:
        pa._predict = real
    assert s.status == "unavailable" and "did not respond" in (s.note or "")


def test_store_is_idempotent_one_row_per_paper():
    real = pa.DB_PATH
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    pa.DB_PATH = tmp
    try:
        s = pa.read_scan("PMC1", {"class_probabilities": {"ai": 0.9}}, 1000)
        pa.store(s)
        s2 = pa.read_scan("PMC1", {"class_probabilities": {"ai": 0.1}}, 1000)
        pa.store(s2)
        with pa._db() as conn:
            rows = conn.execute("SELECT paper_id, ai_probability FROM paper_authorship").fetchall()
    finally:
        pa.DB_PATH = real
    assert rows == [("PMC1", 0.1)], rows


def test_unicode_and_empty_abstracts_do_not_crash():
    restore, _ = _patched(lambda u: (None, 0.0, "x"))
    try:
        r1 = resolver.resolve_fulltext({"isOpenAccess": "N", "abstractText": "Ménière’s disease → 5 µg/L"}, EMAIL, gap=0, use_cache=False)
        r2 = resolver.resolve_fulltext({"isOpenAccess": "N"}, EMAIL, gap=0, use_cache=False)
    finally:
        restore()
    assert r1["access_type"] == "abstract_only" and r1["chars"] > 0
    assert r2["access_type"] == "abstract_only" and r2["chars"] == 0


# ------------------------------------------------------------------ speed and robustness, network

def _net():
    if not NETWORK:
        raise Skip("NETWORK=0")


def test_timeout_is_honored_and_does_not_hang():
    _net()
    t = time.time()
    data, dt, err = resolver._get("https://10.255.255.1/never", EMAIL, timeout=1.5)
    took = time.time() - t
    assert data is None and err, "expected a failure"
    assert took < 4, f"timeout not honored, took {took:.1f}s"


def test_single_literature_search_is_fast():
    _net()
    q = {"query": 'TITLE:"vitamin D" AND TITLE_ABS:"respiratory tract infections"', "format": "json",
         "resultType": "core", "pageSize": 5, "sort": "CITED desc"}
    t = time.time()
    data, dt, err = resolver._get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(q), EMAIL)
    assert data and not err, err
    assert dt < 5.0, f"search took {dt:.2f}s, judges will feel anything over 3"
    print(f"      search {dt:.2f}s")


def test_spaced_burst_does_not_exhaust_sockets():
    """Errno 49 crashed a run today when requests fired back to back. With the gap it must not."""
    _net()
    errors = []
    t = time.time()
    for i in range(12):
        q = {"query": f'TITLE:"melatonin" AND PUB_YEAR:{2000 + i}', "format": "json", "pageSize": 1}
        data, dt, err = resolver._get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(q), EMAIL)
        if err:
            errors.append(err)
        time.sleep(0.35)
    took = time.time() - t
    assert not any("Errno 49" in e for e in errors), f"socket exhaustion: {errors}"
    assert took < 45, f"12 spaced requests took {took:.1f}s"
    print(f"      12 requests {took:.1f}s, errors {len(errors)}")


def test_three_papers_resolve_end_to_end_under_30s():
    _net()
    queries = ['AUTH:"Chinoy" AND TITLE:"tablet" AND TITLE:"circadian"',
               'AUTH:"Gooley" AND TITLE:"room light" AND TITLE:"melatonin"',
               'AUTH:"Wood" AND TITLE:"self-luminous" AND TITLE:"melatonin"']
    t = time.time()
    got = []
    for q in queries:
        p = {"query": q, "format": "json", "resultType": "core", "pageSize": 1, "sort": "CITED desc"}
        data, dt, err = resolver._get("https://www.ebi.ac.uk/europepmc/webservices/rest/search?" + urllib.parse.urlencode(p), EMAIL)
        assert data and not err, err
        import json
        rec = json.loads(data)["resultList"]["result"][0]
        got.append(resolver.resolve_fulltext(rec, EMAIL, use_cache=False)["access_type"])
        time.sleep(0.35)
    took = time.time() - t
    assert took < 30, f"three resolves took {took:.1f}s"
    # Chinoy and Gooley have free copies, Wood is paywalled. Under throttling a free
    # copy can come back as gated instead of full text, and that is still "found",
    # so the assertion is about free copies located, not about which route won.
    free = got.count("full_text") + got.count("free_needs_browser")
    assert free >= 2, got
    print(f"      3 papers {took:.1f}s -> {got}")


def test_local_transcription_is_seconds_not_minutes():
    audio = Path(__file__).with_name("test") / "audio.wav"
    model = Path(__file__).with_name("test") / "ggml-base.en.bin"
    if not (audio.exists() and model.exists()):
        raise Skip("no cached audio or model")
    import subprocess
    t = time.time()
    out = subprocess.run(["whisper-cli", "-m", str(model), "-f", str(audio), "-nt", "-t", "4"], capture_output=True, text=True, timeout=60)
    took = time.time() - t
    assert out.returncode == 0 and len(out.stdout.strip()) > 100, out.stderr[-200:]
    assert took < 10, f"transcription took {took:.1f}s"
    print(f"      whisper {took:.1f}s, {len(out.stdout)} chars")


def test_empty_transcript_does_not_reach_the_detector():
    """A music-only video transcribes to nothing. The scanner must skip, not score silence."""
    assert pa.scan_paper("silent-video", "", "key").status == "skipped"
    assert pa.scan_paper("silent-video", "   \n  ", "key").status == "skipped"


# ------------------------------------------------------------------ runner

def main() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = skipped = 0
    fails = []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"PASS  {name}")
        except Skip as s:
            skipped += 1
            print(f"SKIP  {name}  ({s})")
        except AssertionError as e:
            failed += 1
            fails.append((name, str(e)))
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            fails.append((name, f"{type(e).__name__}: {e}"))
            print(f"FAIL  {name}\n      {type(e).__name__}: {str(e)[:200]}")
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped, of {len(tests)}")
    if fails:
        print("\nFindings:")
        for name, msg in fails:
            print(f"  {name}: {msg[:160]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
