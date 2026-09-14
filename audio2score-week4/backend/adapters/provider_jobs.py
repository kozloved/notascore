"""Persist and resume remote transcription provider jobs.

A successful RunPod /run response is stored on the application job row
immediately, keyed by input hash and transcription configuration. Worker
recovery can then poll the same provider ID instead of submitting another
GPU job.

This is not exactly-once execution. The remaining crash window is the gap
between a successful /run HTTP response and a durable persist of that ID.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from mir.raw_identity import sha256_hex

_BINDING: ContextVar["AppJobBinding | None"] = ContextVar(
    "notascore_provider_job_binding", default=None
)
_STORE: ContextVar["ProviderJobStore | None"] = ContextVar(
    "notascore_provider_job_store", default=None
)


@dataclass(frozen=True)
class AppJobBinding:
    job_id: str
    attempt_id: str | None = None


@dataclass(frozen=True)
class ProviderJobRecord:
    provider_job_id: str
    input_sha256: str
    config_sha256: str


class ProviderJobStore:
    def lookup(
        self,
        *,
        job_id: str | None,
        input_sha256: str,
        config_sha256: str,
    ) -> ProviderJobRecord | None:
        raise NotImplementedError

    def persist(
        self,
        *,
        job_id: str | None,
        attempt_id: str | None,
        record: ProviderJobRecord,
    ) -> bool:
        raise NotImplementedError


class InMemoryProviderJobStore(ProviderJobStore):
    def __init__(self):
        self.records: dict[str, ProviderJobRecord] = {}
        self.persist_calls = 0

    def _key(self, job_id: str | None, input_sha256: str, config_sha256: str) -> str:
        return f"{job_id or '_'}::{input_sha256}::{config_sha256}"

    def lookup(
        self,
        *,
        job_id: str | None,
        input_sha256: str,
        config_sha256: str,
    ) -> ProviderJobRecord | None:
        record = self.records.get(self._key(job_id, input_sha256, config_sha256))
        if record is None and job_id:
            record = self.records.get(self._key(None, input_sha256, config_sha256))
        return record

    def persist(
        self,
        *,
        job_id: str | None,
        attempt_id: str | None,
        record: ProviderJobRecord,
    ) -> bool:
        self.persist_calls += 1
        self.records[self._key(job_id, record.input_sha256, record.config_sha256)] = record
        if job_id:
            self.records[self._key(None, record.input_sha256, record.config_sha256)] = record
        return True


class DatabaseProviderJobStore(ProviderJobStore):
    def lookup(
        self,
        *,
        job_id: str | None,
        input_sha256: str,
        config_sha256: str,
    ) -> ProviderJobRecord | None:
        if not job_id:
            return None
        import database as db

        row = db.get_job(job_id)
        if not row:
            return None
        provider_job_id = (row.get("provider_job_id") or "").strip()
        if not provider_job_id:
            return None
        stored_input = (row.get("provider_input_sha256") or "").strip()
        stored_config = (row.get("provider_config_sha256") or "").strip()
        if stored_input != input_sha256 or stored_config != config_sha256:
            return None
        return ProviderJobRecord(
            provider_job_id=provider_job_id,
            input_sha256=stored_input,
            config_sha256=stored_config,
        )

    def persist(
        self,
        *,
        job_id: str | None,
        attempt_id: str | None,
        record: ProviderJobRecord,
    ) -> bool:
        if not job_id:
            return False
        import database as db

        fields = {
            "provider_job_id": record.provider_job_id,
            "provider_input_sha256": record.input_sha256,
            "provider_config_sha256": record.config_sha256,
        }
        if attempt_id:
            return db.heartbeat_job_attempt(job_id, attempt_id, **fields)
        return db.update_job(job_id, **fields)


def current_binding() -> AppJobBinding | None:
    return _BINDING.get()


def current_store() -> ProviderJobStore:
    return _STORE.get() or DatabaseProviderJobStore()


@contextmanager
def bind_app_job(job_id: str, attempt_id: str | None = None) -> Iterator[AppJobBinding]:
    binding = AppJobBinding(job_id=job_id, attempt_id=attempt_id)
    token = _BINDING.set(binding)
    try:
        yield binding
    finally:
        _BINDING.reset(token)


@contextmanager
def use_provider_job_store(store: ProviderJobStore) -> Iterator[ProviderJobStore]:
    token = _STORE.set(store)
    try:
        yield store
    finally:
        _STORE.reset(token)


def config_fingerprint(settings: dict) -> str:
    payload = {
        "model": settings.get("model"),
        "provider": settings.get("provider"),
        "toolkit": settings.get("toolkit"),
        "toolkit_version": settings.get("toolkit_version"),
        "endpoint_root": settings.get("endpoint_root") or settings.get("endpoint") or "",
    }
    return sha256_hex(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def lookup_resumable_provider_job(
    *,
    input_sha256: str,
    config_sha256: str,
) -> ProviderJobRecord | None:
    binding = current_binding()
    return current_store().lookup(
        job_id=binding.job_id if binding else None,
        input_sha256=input_sha256,
        config_sha256=config_sha256,
    )


def persist_provider_job(
    *,
    provider_job_id: str,
    input_sha256: str,
    config_sha256: str,
) -> bool:
    binding = current_binding()
    return current_store().persist(
        job_id=binding.job_id if binding else None,
        attempt_id=binding.attempt_id if binding else None,
        record=ProviderJobRecord(
            provider_job_id=provider_job_id,
            input_sha256=input_sha256,
            config_sha256=config_sha256,
        ),
    )
