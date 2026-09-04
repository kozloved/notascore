"""YourMT3 worker packaging pins (no CUDA, no model load)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2].parent / "mt3-worker"
sys.path.insert(0, str(ROOT))

from gpu_compat import cuda_device_error, refuse_unsupported_cuda  # noqa: E402


def test_requirements_pin_transformers_4_43():
    pins = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "transformers==4.43.4" in pins
    assert not any(p.startswith("transformers>=") or p.startswith("transformers>") for p in pins)


def test_blackwell_is_refused():
    message = cuda_device_error(
        "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb",
        12,
        0,
    )
    assert message is not None
    assert "Blackwell" in message
    assert "4090" in message


def test_refuse_unsupported_cuda_exits_on_blackwell(monkeypatch):
    class FakeCuda:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def get_device_name(_index):
            return "NVIDIA RTX PRO 6000 Blackwell Server Edition MIG 1g.24gb"

        @staticmethod
        def get_device_capability(_index):
            return (12, 0)

    class FakeTorch:
        cuda = FakeCuda

    monkeypatch.setitem(sys.modules, "torch", FakeTorch)
    with pytest.raises(SystemExit, match="Blackwell"):
        refuse_unsupported_cuda("cuda")


def test_refuse_unsupported_cuda_skips_cpu():
    refuse_unsupported_cuda("cpu")


def test_ampere_and_ada_are_allowed():
    assert cuda_device_error("NVIDIA GeForce RTX 4090", 8, 9) is None
    assert cuda_device_error("NVIDIA GeForce RTX 3090", 8, 6) is None
    assert cuda_device_error("NVIDIA A40", 8, 6) is None


def test_dockerfile_copies_gpu_compat_and_asserts_transformers():
    text = (ROOT / "Dockerfile").read_text()
    assert "COPY gpu_compat.py /gpu_compat.py" in text
    assert 'assert v.startswith(\'4.43.\')' in text or 'assert transformers.__version__.startswith("4.43.")' in text
