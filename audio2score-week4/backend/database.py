from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import create_engine, Column, String, Integer, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timezone
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./audio2score.db")

connect_args = {}

if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    status = Column(String, default="queued")
    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=True)
    storage_key = Column(String, nullable=True)
    result_storage_key = Column(String, nullable=True)
    progress = Column(Integer, default=0)
    error = Column(String, nullable=True)
    created_at = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)
    mode = Column(String, default="solo")
    user_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    claim_token_hash = Column(String, nullable=True, index=True)
    deleted_at = Column(String, nullable=True)
    edited_result_storage_key = Column(String, nullable=True)
    edit_revision = Column(Integer, default=0)
    processing_attempt = Column(String, nullable=True)
    published_attempt = Column(String, nullable=True)


OWNERSHIP_COLUMNS = {
    "user_id": "VARCHAR",
    "title": "VARCHAR",
    "duration_seconds": "INTEGER",
    "claim_token_hash": "VARCHAR",
    "deleted_at": "VARCHAR",
}

SCORE_EDIT_COLUMNS = {
    "edited_result_storage_key": "VARCHAR",
    "edit_revision": "INTEGER DEFAULT 0",
}

ATTEMPT_COLUMNS = {
    "processing_attempt": "VARCHAR",
    "published_attempt": "VARCHAR",
}


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_job_mode_column()
    _ensure_job_ownership_columns()
    _ensure_score_edit_columns()
    _ensure_attempt_columns()


def _ensure_job_mode_column():
    """create_all does not add columns to an existing jobs table."""
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("jobs")}
    if "mode" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE jobs ADD COLUMN mode VARCHAR DEFAULT 'solo'"))
        conn.execute(text("UPDATE jobs SET mode = 'solo' WHERE mode IS NULL"))


def _ensure_job_ownership_columns():
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        for name, sql_type in OWNERSHIP_COLUMNS.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_user_created "
                "ON jobs (user_id, created_at)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_claim_token_hash "
                "ON jobs (claim_token_hash)"
            )
        )


def _ensure_score_edit_columns():
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        for name, sql_type in SCORE_EDIT_COLUMNS.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}"))


def _ensure_attempt_columns():
    inspector = inspect(engine)
    if "jobs" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("jobs")}
    with engine.begin() as conn:
        for name, sql_type in ATTEMPT_COLUMNS.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {sql_type}"))


def row_to_dict(row):
    if not row:
        return None

    return {
        column.name: getattr(row, column.name)
        for column in row.__table__.columns
    }


def create_job(job: dict):
    session = SessionLocal()

    try:
        row = Job(**job)
        session.add(row)
        session.commit()
    finally:
        session.close()


def get_job(job_id: str):
    session = SessionLocal()

    try:
        row = (
            session.query(Job)
            .filter(Job.id == job_id)
            .first()
        )

        return row_to_dict(row)

    finally:
        session.close()


def get_job_by_claim_hash(token_hash: str):
    if not token_hash:
        return None
    session = SessionLocal()
    try:
        row = (
            session.query(Job)
            .filter(Job.claim_token_hash == token_hash)
            .filter(Job.deleted_at.is_(None))
            .first()
        )
        return row_to_dict(row)
    finally:
        session.close()


def list_jobs(limit: int = 50):
    session = SessionLocal()

    try:
        rows = (
            session.query(Job)
            .filter(Job.deleted_at.is_(None))
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )

        return [
            row_to_dict(row)
            for row in rows
        ]

    finally:
        session.close()


def list_jobs_for_user(user_id: str, limit: int = 100):
    session = SessionLocal()
    try:
        rows = (
            session.query(Job)
            .filter(Job.user_id == user_id)
            .filter(Job.deleted_at.is_(None))
            .order_by(Job.created_at.desc())
            .limit(limit)
            .all()
        )
        return [row_to_dict(row) for row in rows]
    finally:
        session.close()


ALLOWED_UPDATE_FIELDS = {
    "status",
    "progress",
    "error",
    "storage_key",
    "result_storage_key",
    "user_id",
    "title",
    "duration_seconds",
    "claim_token_hash",
    "deleted_at",
    "edited_result_storage_key",
    "edit_revision",
    "processing_attempt",
    "published_attempt",
}


def update_job(job_id: str, **fields):
    clean_fields = {
        key: value
        for key, value in fields.items()
        if key in ALLOWED_UPDATE_FIELDS
    }

    if not clean_fields:
        return False

    clean_fields["updated_at"] = utcnow()

    session = SessionLocal()

    try:
        updated_count = (
            session.query(Job)
            .filter(Job.id == job_id)
            .update(
                clean_fields,
                synchronize_session=False,
            )
        )

        session.commit()

        return updated_count > 0

    finally:
        session.close()


def cas_update_job(job_id: str, expected: dict | None = None, expected_in: dict | None = None, **fields):
    """Atomically update a job only when the expected predicates still match."""
    clean_fields = {
        key: value
        for key, value in fields.items()
        if key in ALLOWED_UPDATE_FIELDS
    }
    if not clean_fields:
        return False
    clean_fields["updated_at"] = utcnow()
    session = SessionLocal()
    try:
        query = session.query(Job).filter(Job.id == job_id)
        for key, value in (expected or {}).items():
            column = getattr(Job, key)
            if value is None:
                query = query.filter(column.is_(None))
            else:
                query = query.filter(column == value)
        for key, options in (expected_in or {}).items():
            query = query.filter(getattr(Job, key).in_(list(options)))
        updated_count = query.update(clean_fields, synchronize_session=False)
        session.commit()
        return updated_count > 0
    finally:
        session.close()


def claim_job_attempt(job_id: str, attempt_id: str) -> bool:
    return cas_update_job(
        job_id,
        expected_in={"status": ("queued", "failed")},
        status="processing",
        processing_attempt=attempt_id,
        error=None,
        progress=5,
    )


def complete_job_attempt(job_id: str, attempt_id: str, **fields) -> bool:
    payload = dict(fields)
    payload.setdefault("status", "completed")
    payload.setdefault("progress", 100)
    payload.setdefault("error", None)
    payload["published_attempt"] = attempt_id
    return cas_update_job(
        job_id,
        expected={"status": "processing", "processing_attempt": attempt_id},
        **payload,
    )


def fail_job_attempt(job_id: str, attempt_id: str, error: str) -> bool:
    return cas_update_job(
        job_id,
        expected={"status": "processing", "processing_attempt": attempt_id},
        status="failed",
        error=error,
    )
