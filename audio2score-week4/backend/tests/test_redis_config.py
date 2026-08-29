"""Tests for Compose Redis URL selection."""

from redis_config import redis_url


def test_redis_url_prefers_private(monkeypatch):
    monkeypatch.setenv("REDIS_PRIVATE_URL", "redis://red-internal:6379")
    monkeypatch.setenv("REDIS_URL", "redis://default:public@host:6379")
    assert redis_url() == "redis://red-internal:6379"


def test_redis_url_falls_back_to_public(monkeypatch):
    monkeypatch.delenv("REDIS_PRIVATE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379")
    assert redis_url() == "redis://redis:6379"


def test_redis_url_default(monkeypatch):
    monkeypatch.delenv("REDIS_PRIVATE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert redis_url() == "redis://localhost:6379"
