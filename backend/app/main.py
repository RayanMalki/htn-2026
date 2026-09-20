import asyncio
import hmac
import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
import sentry_sdk
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import and_, func, or_, select, text

from app.config import settings
from app.db import Case, Event, init_db, now, read_case, session, update_case
from app.media import MAX_BYTES
from app.observability import configure_sentry
from app.queue import enqueue, redis_client
from app.schemas import CaseCreate
from app.search import ElasticSearch

configure_sentry()


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="HypeCheck", version="0.1.0", lifespan=lifespan)


def valid_id(case_id: str):
    try:
        return str(uuid.UUID(case_id))
    except ValueError:
        raise HTTPException(404, "Case not found")


def get_case(case_id: str):
    case_id = valid_id(case_id)
    try:
        return read_case(case_id)
    except LookupError:
        raise HTTPException(404, "Case not found")


def admin(authorization: str | None):
    token = settings().admin_token
    if not token or not hmac.compare_digest(authorization or "", f"Bearer {token}"):
        raise HTTPException(401, "Administrator token required")


def rate_limit(request: Request):
    import hashlib
    import time
    # Use the direct peer unless uvicorn is explicitly configured to trust Caddy.
    identity = hashlib.sha256((request.client.host if request.client else "unknown").encode()).hexdigest()
    try:
        r = redis_client()
        key = f"rate:{identity}:{int(time.time()) // 60}"
        count = r.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],65) end; return n", 1, key)
        if count > settings().rate_limit_per_minute:
            raise HTTPException(429, "Too many submissions. Try again in a minute.", headers={"Retry-After": "60"})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "The job queue is unavailable. Please try again.")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/readyz")
async def ready():
    checks = {}
    try:
        with session() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False
    try:
        checks["redis"] = bool(await asyncio.to_thread(redis_client().ping))
    except Exception:
        checks["redis"] = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            search = ElasticSearch(client)
            await search.call("GET", f"/{settings().elastic_index}/_mapping")
            checks["elasticsearch"] = True
            if settings().elastic_semantic:
                await search.call("GET", f"/_inference/{settings().elastic_inference_id}")
            checks["semantic_endpoint"] = True
    except Exception:
        checks.setdefault("elasticsearch", False)
        checks["semantic_endpoint"] = False
    checks["model_configured"] = settings().model_configured
    if settings().video_enabled and settings().model_mode == 'live':
        from app.video import dependencies
        checks.update({f'video_{key}': value for key, value in dependencies().items()})
    return JSONResponse({"status": "ready" if all(checks.values()) else "not_ready", "checks": checks,
                         "model_mode": settings().model_mode}, status_code=200 if all(checks.values()) else 503)


@app.get("/api/config")
def public_config():
    return {"model_mode": settings().model_mode, "semantic_enabled": settings().elastic_semantic,
            "target_seconds": 90, "max_duration_seconds": 100}


@app.post("/api/cases", status_code=202)
def create_case(body: CaseCreate, request: Request):
    rate_limit(request)
    gate = redis_client().lock("admission", timeout=5, blocking_timeout=1)
    if not gate.acquire():
        raise HTTPException(503, "Submission busy. Please retry.")
    try:
        with session() as db, db.begin():
            count = db.scalar(select(func.count()).select_from(Case).where(or_(
                Case.status.in_(["queued", "downloading", "transcribing", "researching", "judging", "rendering"]),
                and_(Case.status == "awaiting_upload", Case.updated_at > now() - timedelta(hours=1)),
            )))
            if count >= settings().max_active_cases:
                raise HTTPException(429, "The demo queue is full. Please try again shortly.")
            case = Case(source_url=body.source_url, result={"schema_version": 1,
                         "submitted_at": now().isoformat(), "model_mode": settings().model_mode})
            db.add(case)
            db.flush()
            case_id = case.id
        result = update_case(case_id, status="queued")
        try:
            enqueue(case_id)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            # Durable case remains queued; beat recovers it if publication failed.
        return result
    finally:
        gate.release()


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str):
    return get_case(case_id)


@app.post("/api/cases/{case_id}/render", status_code=202)
def request_render(case_id: str, request: Request, brainrot: bool = False, sfx: bool = True):
    return queue_retry(case_id, request, render_options={"brainrot": brainrot, "sfx": sfx})


@app.post("/api/cases/{case_id}/media", status_code=202)
async def upload(case_id: str, request: Request, file: UploadFile = File(...)):
    case_id = valid_id(case_id)
    rate_limit(request)
    case = get_case(case_id)
    if case["status"] != "awaiting_upload":
        raise HTTPException(409, "This case is not waiting for a video upload.")
    lock = redis_client().lock(f"upload:{case_id}", timeout=180, blocking=False)
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "An upload is already in progress.")
    folder = settings().media_root / case_id
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / "upload.tmp"
    final = folder / "upload.video"
    try:
        if get_case(case_id)["status"] != "awaiting_upload":
            raise HTTPException(409, "The case has already resumed.")
        size = 0
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "Video must be at most 100 MB.")
                output.write(chunk)
        if not size:
            raise HTTPException(422, "The uploaded file is empty.")
        temporary.replace(final)
        result = update_case(case_id, media_path=str(final), status="queued", error=None,
                             result_patch={"input_mode": "upload", "submitted_at": now().isoformat()})
        try:
            enqueue(case_id)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
        return result
    finally:
        temporary.unlink(missing_ok=True)
        await file.close()
        lock.release()


def event_batch(case_id, cursor):
    with session() as db:
        events = db.scalars(select(Event).where(Event.case_id == case_id, Event.sequence > cursor)
                            .order_by(Event.sequence).limit(100)).all()
        return [(event.sequence, event.payload) for event in events]


@app.get("/api/cases/{case_id}/events")
async def events(case_id: str, request: Request, last_event_id: str | None = Header(default=None)):
    case = get_case(case_id)
    try:
        cursor = int(last_event_id or request.query_params.get("after", "0"))
        if cursor < 0 or cursor > case["sequence"]:
            cursor = 0
    except ValueError:
        raise HTTPException(400, "Invalid event cursor")

    async def stream():
        position = cursor
        # Poll persisted events as source of truth; Redis publication is available for other subscribers.
        # A one-second poll keeps reconnect behavior independent of missed pub/sub notifications.
        while not await request.is_disconnected():
            batch = await asyncio.to_thread(event_batch, case_id, position)
            for sequence, payload in batch:
                position = sequence
                yield f"id: {sequence}\nevent: case\ndata: {json.dumps(payload)}\n\n"
            current = await asyncio.to_thread(read_case, case_id)
            if current["status"] in {"complete", "incomplete", "no_claims"} and position >= current["sequence"]:
                yield "event: end\ndata: {}\n\n"
                break
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.get("/api/cases/{case_id}/replay")
def replay(case_id: str, format: str = "html"):
    case = get_case(case_id)
    if case["status"] not in {"complete", "incomplete", "no_claims"}:
        raise HTTPException(409, "Replay is available after analysis finishes.")
    if format not in {"html", "json"}:
        raise HTTPException(400, "Choose html or json")
    from app.replay import export_case
    path = export_case(case["id"]).with_suffix(f".{format}")
    return FileResponse(path, filename=f"hypecheck-{case['id']}.{format}")


@app.get("/api/metrics")
def metrics():
    with session() as db:
        cases = db.scalars(select(Case).where(Case.created_at > now() - timedelta(hours=24))).all()
    finished = [c for c in cases if c.status in {"complete", "incomplete", "no_claims"}]
    durations = sorted(c.result.get("timings", {}).get("total", 0) for c in finished)
    stages: dict[str, list] = {}
    for case in finished:
        for name, duration in case.result.get("timings", {}).items():
            if name != "total":
                stages.setdefault(name, []).append(duration)
    return {"window": "24h", "total_cases": len(cases), "finished": len(finished),
            "complete": sum(c.status in {"complete", "no_claims"} for c in finished),
            "failed": sum(c.status == "incomplete" for c in finished),
            "completion_rate": sum(c.status in {"complete", "no_claims"} for c in finished) / len(finished) if finished else None,
            "failure_rate": sum(c.status == "incomplete" for c in finished) / len(finished) if finished else None,
            "queued": sum(c.status == "queued" for c in cases),
            "p50_seconds": durations[len(durations) // 2] if durations else None,
            "p95_seconds": durations[min(len(durations) - 1, int(len(durations) * .95))] if durations else None,
            "stages": {k: round(sum(v) / len(v), 2) for k, v in stages.items()}}


@app.post("/api/admin/failure")
def controlled_failure(authorization: str | None = Header(default=None)):
    admin(authorization)
    if not settings().enable_failure_injection:
        raise HTTPException(404, "Failure injection is disabled")
    try:
        raise RuntimeError("Controlled demonstration failure: no user data")
    except RuntimeError as exc:
        event_id = sentry_sdk.capture_exception(exc)
    return JSONResponse({"injected": True, "sentry_event_id": event_id}, status_code=503)


@app.post("/api/cases/{case_id}/retry", status_code=202)
def retry_case(case_id: str, request: Request):
    return queue_retry(case_id, request)


def queue_retry(case_id: str, request: Request, render_options: dict | None = None):
    from app.video.script import eligible_claims
    case_id = valid_id(case_id)
    rate_limit(request)
    gate = redis_client().lock("admission", timeout=5, blocking_timeout=1)
    if not gate.acquire():
        raise HTTPException(503, "Submission busy. Please retry.")
    lock = redis_client().lock(f"processing:{case_id}", timeout=10, blocking=False)
    acquired = False
    try:
        case = get_case(case_id)
        current = case['result'].get('video', {})
        options = render_options if render_options is not None else current.get('options', {'sfx': True, 'brainrot': False})
        same = current.get('options', {'sfx': True, 'brainrot': False}) == options
        if render_options is not None:
            try:
                eligible_claims(case)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if same and current.get('status') in {'pending', 'rendering'} and case['status'] in {'queued', 'rendering'}:
                return case
        if same and current.get('status') == 'ready':
            from app.video.plan import VERSION
            try:
                video_artifact(case_id, 'response.mp4')
                available = True
            except HTTPException:
                available = False
            from app.video.render import renderer_identity
            if available and current.get('version') == VERSION and current.get('renderer_identity') == renderer_identity():
                return case
        acquired = lock.acquire(blocking=False)
        if not acquired or case['status'] not in {'incomplete', 'complete'}:
            raise HTTPException(409, 'This case is already processing or has no finished analysis.')
        with session() as db:
            active = db.scalar(select(func.count()).select_from(Case).where(
                Case.status.in_(['queued', 'downloading', 'transcribing', 'researching', 'judging', 'rendering'])))
        if active >= settings().max_active_cases:
            raise HTTPException(429, 'The demo queue is full. Please try again shortly.')
        claims = case['result'].get('claims', {})
        for item in claims.values():
            if item.get('status') == 'incomplete' and item.get('evidence') is not None:
                item['status'] = 'researched'
                item.pop('error', None)
        result = update_case(case_id, status='queued', error=None, finished_at=None,
            result_patch={'claims': claims, 'video': {'status': 'pending', 'options': options,
                          'requested': render_options is not None or current.get('requested', False)}})
    finally:
        if acquired:
            lock.release()
        gate.release()
    try:
        enqueue(case_id)
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
    return result


def video_artifact(case_id: str, filename: str):
    case = get_case(case_id)
    video = case['result'].get('video', {})
    if video.get('status') != 'ready':
        raise HTTPException(409, 'Video is not ready.')
    import re
    artifact = video.get('artifact', '')
    if not re.fullmatch(r'[a-f0-9]{20}', artifact):
        raise HTTPException(404, 'Video artifact not found.')
    root = (settings().media_root / case['id'] / 'video').resolve()
    path = (root / artifact / filename).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(404, 'Video artifact not found.')
    if not path.is_file():
        raise HTTPException(410, 'This temporary video has expired.')
    return path


@app.get('/api/cases/{case_id}/video')
def generated_video(case_id: str, download: bool = False):
    return FileResponse(video_artifact(case_id, 'response.mp4'), media_type='video/mp4',
                        filename=f'hypecheck-{valid_id(case_id)}.mp4' if download else None)


@app.get('/api/cases/{case_id}/video/captions')
def video_captions(case_id: str):
    return FileResponse(video_artifact(case_id, 'captions.vtt'), media_type='text/vtt')


@app.get('/api/cases/{case_id}/video/sources')
def video_sources(case_id: str):
    return FileResponse(video_artifact(case_id, 'manifest.json'), media_type='application/json',
                        filename=f'hypecheck-{valid_id(case_id)}-sources.json')
