import asyncio
from datetime import datetime
from pathlib import Path
from time import monotonic

import httpx
import sentry_sdk

from app.config import settings
from app.db import now, read_case, update_case
from app.detection import Detector
from app.literature import DiscoveryIncomplete, Literature
from app.media import MediaError, download, extract_audio
from app.models import models
from app.observability import log_event, record_case_duration, stage
from app.schemas import AudioAnalysis, Claim, validate_verdict
from app.search import ElasticSearch
from app.video import RenderError, render_video

TERMINAL = {"complete", "no_claims", "incomplete", "awaiting_upload"}


async def run_case(case_id: str):
    existing = read_case(case_id)
    if existing["status"] in TERMINAL:
        return
    from app.db import Case, session
    with session() as db:
        saved = db.get(Case, case_id)
        media_path = saved.media_path
    cfg = settings()
    video_requested = (cfg.video_enabled or existing["result"].get("video", {}).get("requested", False)) and cfg.model_mode == "live"
    result = dict(existing["result"])
    if "analysis" in result and (result.get("model_mode") != cfg.model_mode
            or (result.get("model_id") is not None and result["model_id"] != cfg.model_id)):
        update_case(case_id, status="incomplete", finished_at=now(), error={
            "code": "model_configuration_changed", "message": "Model mode changed during this case. Submit a new case to use the new model configuration.",
        })
        return
    timings = dict(result.get("timings", {}))
    previous_attempt = timings.get("total", 0)
    queue_wait = max(0, (now() - datetime.fromisoformat(existing["updated_at"])).total_seconds())
    timings["queue_wait"] = round(queue_wait, 3)
    started = monotonic() - queue_wait
    stage_name = "intake"
    update_case(case_id, started_at=now(), error=None, result_patch={
        "schema_version": 1, "model_mode": cfg.model_mode,
        "model_id": cfg.model_id,
        "limitations": ["Spoken English only; at most three claims; literature search is not exhaustive."]
        + (["MOCK MODE: the transcript and claim are prepared inputs, not extracted from this video."]
           if cfg.model_mode == "mock" else [])
        + (["Claim timestamps are approximate 10-second audio-window ranges, not word-level timing."]
           if cfg.model_mode == "live" and cfg.model_provider == "backboard" else []),
    })
    sentry_sdk.set_tag("case_id", case_id)
    sentry_sdk.set_tag("model_mode", cfg.model_mode)
    log_event("HypeCheck case started", case_id=case_id, model_mode=cfg.model_mode)

    def save(**patch):
        update_case(case_id, result_patch={**patch, "timings": dict(timings)})

    try:
        async with asyncio.timeout(cfg.case_timeout_seconds):
            if not media_path and "analysis" not in result:
                update_case(case_id, status="downloading")
                try:
                    with stage("download", timings):
                        path = await download(case_id, existing["source_url"])
                    media_path = str(path)
                    update_case(case_id, media_path=media_path)
                except MediaError as exc:
                    timings["total"] = round(monotonic() - started + previous_attempt, 3)
                    update_case(case_id, status="awaiting_upload", error={"code": "download_blocked",
                        "message": str(exc)}, result_patch={"timings": timings})
                    return

            stage_name = "transcription"
            update_case(case_id, status="transcribing")
            adapter = models()
            if "analysis" in result:
                analysis = AudioAnalysis.model_validate(result["analysis"])
            else:
                with stage("audio_extraction", timings):
                    audio, duration = await extract_audio(Path(media_path))
                with stage("transcription", timings):
                    async with asyncio.timeout(25):
                        analysis = await adapter.analyze(audio, duration=duration)
                if any(c.end > duration + 0.5 for c in analysis.claims):
                    raise ValueError("Claim timestamp exceeds media duration")
                save(analysis=analysis.model_dump(), duration_seconds=duration)
            if analysis.language.lower() not in {"en", "english"}:
                raise MediaError("Only spoken English is supported in this iteration")
            if not analysis.usable_speech or not analysis.claims:
                timings["total"] = round(monotonic() - started + previous_attempt, 3)
                update_case(case_id, status="no_claims", finished_at=now(), result_patch={
                    "timings": timings, "outcome": "No usable spoken medical claims were found.",
                })
                return

            stage_name = "research"
            update_case(case_id, status="researching")
            completed = dict(result.get("claims", {}))
            failures = []
            async with httpx.AsyncClient(timeout=10) as client:
                literature = Literature(client)
                search = ElasticSearch(client)

                async def research(claim: Claim):
                    # Checkpoints are persisted after every completed claim and reused on redelivery.
                    if completed.get(claim.id, {}).get("evidence") is not None:
                        return
                    local_timings = {}
                    try:
                        async with asyncio.timeout(cfg.research_timeout_seconds):
                            with stage("literature", local_timings) as span:
                                passages, provenance = await literature.discover(claim)
                                for key in ["papers_found", "passages_found", "cache_hits", "full_text_fallbacks"]:
                                    span.set_data(key, provenance.get(key, 0))
                            sources = {p.paper_id: {"title": p.title, "source_url": p.source_url,
                                "access_type": p.access_type, "provider": p.provider,
                                "source_kind": p.source_kind} for p in passages}
                            completed[claim.id] = {"claim": claim.model_dump(), "status": "indexing",
                                "discovered_sources": list(sources.values()), "timings": local_timings}
                            save(claims=dict(completed))
                            with stage("indexing", local_timings) as span:
                                indexing = await search.index(passages)
                                span.set_data("indexed", indexing.get("indexed", 0))
                                span.set_data("cache_hits", indexing.get("index_cache_hits", 0))
                            with stage("retrieval", local_timings):
                                reranking = {}
                                evidence, mode = await search.retrieve(claim.text, provenance["candidate_ids"],
                                    hybrid=cfg.elastic_semantic and indexing["index_mode"] == "hybrid",
                                    diagnostics=reranking)
                        completed[claim.id] = {"claim": claim.model_dump(),
                            "evidence": [p.model_dump() for p in evidence],
                            "provenance": {**provenance, **indexing, "retrieval_mode": mode,
                                           "reranking": reranking, "search_scope": "current_claim_candidates"},
                            "timings": local_timings, "status": "researched"}
                    except Exception as exc:
                        sentry_sdk.capture_exception(exc)
                        failures.append(claim.id)
                        if isinstance(exc, DiscoveryIncomplete):
                            completed[claim.id] = {
                                "provenance": exc.provenance,
                                "discovered_sources": list({p.paper_id: {
                                    "title": p.title, "source_url": p.source_url,
                                    "access_type": p.access_type, "provider": p.provider,
                                    "source_kind": p.source_kind,
                                } for p in exc.passages}.values()),
                            }
                        completed[claim.id] = {**completed.get(claim.id, {}), "claim": claim.model_dump(), "status": "incomplete",
                            "error": "Medical research could not complete. No verdict was assigned.",
                            "timings": local_timings}
                    save(claims=dict(completed))

                async def detect():
                    # Authorship is a side signal: it never gates a verdict and never fails a case.
                    if result.get("detection"):
                        return
                    try:
                        with stage("detection", timings):
                            outcome = await Detector(client).scan(analysis)
                        save(detection=outcome.model_dump())
                    except Exception as exc:
                        sentry_sdk.capture_exception(exc)

                with stage("research", timings):
                    await asyncio.gather(detect(), *(research(c) for c in analysis.claims))

            stage_name = "judgment"
            update_case(case_id, status="judging")

            async def judge(claim: Claim):
                from app.schemas import Passage
                item = completed[claim.id]
                if item.get("verdict") or item["status"] == "incomplete":
                    return
                try:
                    evidence = [Passage.model_validate(p) for p in item["evidence"]]
                    with stage("judgment", item["timings"]):
                        async with asyncio.timeout(20):
                            verdict = validate_verdict(await adapter.judge(claim, evidence), evidence)
                    for failure in item.get("provenance", {}).get("provider_failures", []):
                        verdict.limitations.append(
                            f"{failure['provider']} was unavailable; this assessment uses the remaining sources.")
                    item.update(verdict=verdict.model_dump(), status="complete")
                except Exception as exc:
                    sentry_sdk.capture_exception(exc)
                    failures.append(claim.id)
                    item.update(status="incomplete", error="Evidence judgment failed validation or timed out.")
                save(claims=dict(completed))

            with stage("judgment", timings):
                await asyncio.gather(*(judge(c) for c in analysis.claims))
            timings["total"] = round(monotonic() - started + previous_attempt, 3)
            status = "incomplete" if failures or any(c["status"] == "incomplete" for c in completed.values()) else "complete"
            sentry_sdk.set_tag("case_status", status)
            update_case(case_id, status="rendering" if status == "complete" and video_requested else status,
                        finished_at=None if status == "complete" and video_requested else now(), result_patch={
                "claims": completed, "timings": timings, "target_met": timings["total"] <= 90,
            })
        if read_case(case_id)["status"] == "rendering":
            stage_name = "rendering"
            save(video={**read_case(case_id)["result"].get("video", {}), "status": "rendering"},
                 analysis_seconds=timings["total"])
            with stage("rendering", timings):
                # Rendering is intentionally uncapped: long evidence videos may
                # need several minutes for narration, cards, FFmpeg and captions.
                video = await render_video(read_case(case_id))
            timings["total"] = round(monotonic() - started + previous_attempt, 3)
            update_case(case_id, status="complete", finished_at=now(), result_patch={
                "video": video, "timings": timings, "target_met": timings["total"] <= 90,
            })
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        if stage_name == "rendering":
            save(video={**read_case(case_id)["result"].get("video", {}), "status": "failed",
                        "error_code": exc.code if isinstance(exc, RenderError) else "render_failed",
                        "error": str(exc) if isinstance(exc, RenderError) else
                        "Video generation stopped or timed out. Saved evidence is intact; retry to resume."})
        timings["total"] = round(monotonic() - started + previous_attempt, 3)
        message = str(exc) if isinstance(exc, MediaError) else f"The {stage_name} stage did not complete. No unsupported verdict was assigned."
        latest = read_case(case_id)["result"]
        partial_claims = latest.get("claims", {})
        for claim in latest.get("analysis", {}).get("claims", []):
            item = partial_claims.setdefault(claim["id"], {"claim": claim})
            if item.get("status") != "complete":
                item.update(status="incomplete", error=message)
        update_case(case_id, status="incomplete", finished_at=now(), error={
            "code": f"{stage_name}_failed", "message": message,
        }, result_patch={"timings": timings, "claims": partial_claims})
    finally:
        final_status = read_case(case_id)["status"]
        sentry_sdk.set_tag("case_status", final_status)
        if "total" in timings:
            record_case_duration(timings["total"])
        log_event("HypeCheck case finished", case_id=case_id, case_status=final_status,
                  duration_seconds=timings.get("total"), model_mode=cfg.model_mode)
        if final_status in {"complete", "no_claims", "incomplete"}:
            from app.replay import export_case
            export_case(case_id)
