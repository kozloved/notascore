from engine.flags import PIPELINE_MODE_LEGACY, nextgen_status, pipeline_mode


def test_pipeline_mode_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("NEXTGEN_PIPELINE_MODE", raising=False)
    assert pipeline_mode() == PIPELINE_MODE_LEGACY
    assert nextgen_status()["pipeline_mode"] == PIPELINE_MODE_LEGACY
    assert nextgen_status()["orchestrator_active"] is False


def test_pipeline_mode_rejects_unknown(monkeypatch):
    monkeypatch.setenv("NEXTGEN_PIPELINE_MODE", "experimental")
    assert pipeline_mode() == PIPELINE_MODE_LEGACY


def test_pipeline_mode_live_is_opt_in(monkeypatch):
    monkeypatch.setenv("NEXTGEN_PIPELINE_MODE", "live")
    assert pipeline_mode() == "live"
    assert nextgen_status()["orchestrator_active"] is True
