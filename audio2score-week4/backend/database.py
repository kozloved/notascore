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


def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_job_mode_column()


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


def list_jobs(limit: int = 50):
    session = SessionLocal()

    try:
        rows = (
            session.query(Job)
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


ALLOWED_UPDATE_FIELDS = {
    "status",
    "progress",
    "error",
    "storage_key",
    "result_storage_key",
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
