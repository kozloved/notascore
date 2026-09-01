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


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_job_mode_column()
    _ensure_job_ownership_columns()
    _ensure_score_edit_columns()


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
