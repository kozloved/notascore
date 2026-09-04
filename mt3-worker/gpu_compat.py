"""Refuse GPUs that the shipped PyTorch cannot run.

YourMT3 itself is unchanged. The NVIDIA CUDA 12.6 + PyTorch 2.7.1 wheels in
this image support Ampere / Ada / Hopper (sm_80, sm_86, sm_89, sm_90).
Blackwell (sm_120, RTX PRO 6000) loads the checkpoint then dies on the first
CUDA kernel with "no kernel image is available for execution on the device".
"""

from __future__ import annotations

BLACKWELL_CUDA_MAJOR = 12


def cuda_device_error(device_name: str, major: int, minor: int) -> str | None:
    """Return a user-facing error if this GPU cannot run the image."""
    if major >= BLACKWELL_CUDA_MAJOR:
        sm = f"sm_{major}{minor}"
        return (
            f"GPU {device_name} is CUDA capability {sm}. "
            "This YourMT3 image cannot run Blackwell (RTX PRO 6000, B200). "
            "In RunPod, change the endpoint GPU to RTX 4090, RTX 3090, "
            "A40, L40, or RTX 6000 Ada, then redeploy."
        )
    return None


def refuse_unsupported_cuda(device: str) -> None:
    """Exit at worker boot if the attached GPU is Blackwell."""
    if str(device).lower() != "cuda":
        return
    import torch

    if not torch.cuda.is_available():
        return
    name = torch.cuda.get_device_name(0)
    major, minor = torch.cuda.get_device_capability(0)
    message = cuda_device_error(name, int(major), int(minor))
    if message:
        print(f"[MT3] {message}", flush=True)
        raise SystemExit(message)
