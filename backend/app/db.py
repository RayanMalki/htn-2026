import uuid
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("case_id", "sequence"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    payload: Mapped[dict] = mapped_column(JSON)


class PaperCache(Base):
    __tablename__ = "paper_cache"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    data: Mapped[dict] = mapped_column(JSON)


@lru_cache
def engine():
    settings().media_root.mkdir(parents=True, exist_ok=True)
    kw = {"connect_args": {"check_same_thread": False}} if settings().database_url.startswith("sqlite") else {}
    return create_engine(settings().database_url, pool_pre_ping=True, **kw)


def session():
    return sessionmaker(engine(), expire_on_commit=False)()


def init_db():
    Base.metadata.create_all(engine())


def snapshot(case: Case) -> dict:
    def iso(value):
        return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()
    return {
        "id": case.id, "source_url": case.source_url, "status": case.status,
        "created_at": iso(case.created_at), "updated_at": iso(case.updated_at),
        "started_at": iso(case.started_at) if case.started_at else None,
        "finished_at": iso(case.finished_at) if case.finished_at else None,
        "sequence": case.sequence, "result": case.result, "error": case.error,
    }


def read_case(case_id: str) -> dict:
    with session() as db:
        case = db.get(Case, case_id)
        if not case:
            raise LookupError("Case not found")
        return snapshot(case)


def update_case(case_id: str, *, result_patch: dict | None = None, **changes) -> dict:
    # Row lock serializes the snapshot and event sequence; pub/sub is only a wake-up hint.
    with session() as db, db.begin():
        case = db.scalar(select(Case).where(Case.id == case_id).with_for_update())
        if case is None:
            raise LookupError("Case not found")
        for name, value in changes.items():
            setattr(case, name, value)
        if result_patch is not None:
            case.result = {**case.result, **result_patch}
        case.updated_at = now()
        case.sequence += 1
        payload = snapshot(case)
        db.add(Event(case_id=case.id, sequence=case.sequence, payload=payload))
    try:
        from app.queue import redis_client
        redis_client().publish(f"case:{case_id}", str(payload["sequence"]))
    except Exception:
        # Committed database events remain replayable even when notification delivery fails.
        pass
    return payload
