"""CORS origin list includes optional FRONTEND_PUBLIC_URL."""

import main as app_main


def test_cors_includes_frontend_public_url(monkeypatch):
    monkeypatch.setattr(app_main, "CORS_ORIGIN", "https://notascore.com")
    monkeypatch.setenv(
        "FRONTEND_PUBLIC_URL", "https://preview.example.com"
    )
    origins = app_main._cors_origins()
    assert "https://notascore.com" in origins
    assert "https://preview.example.com" in origins
