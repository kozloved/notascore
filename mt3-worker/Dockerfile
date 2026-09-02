# NotaScore YourMT3 / MT3-Infer RunPod Serverless worker
#
# The image intentionally bakes the YourMT3 checkpoint into the image so a
# cold worker does not download ~536 MB of weights at request time.
#
# Build for RunPod with:
#   docker build --platform linux/amd64 -t <registry>/notascore-yourmt3:0.1 .

FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MT3_CHECKPOINT_DIR=/opt/mt3_checkpoints \
    MODEL_NAME=yourmt3

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-dev \
        git \
        git-lfs \
        ffmpeg \
        libsndfile1 \
        ca-certificates \
    && git lfs install --system \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3 /usr/local/bin/python
RUN python -m pip install --upgrade pip setuptools wheel

# MT3-Infer 0.2.0 was the version already selected by NotaScore.
# PyTorch 2.7.1 + CUDA 12.6 matches the upstream benchmark environment.
RUN python -m pip install \
        torch==2.7.1+cu126 \
        torchaudio==2.7.1+cu126 \
        --index-url https://download.pytorch.org/whl/cu126 \
    && python -m pip install \
        'mt3-infer[torch]==0.2.0' \
        runpod==1.7.13 \
        numpy

# Download the exact default YourMT3 checkpoint during image build.
# This is deliberately done at build time, not worker startup.
RUN mkdir -p "${MT3_CHECKPOINT_DIR}" \
    && python - <<'PY'
from mt3_infer import download_model
path = download_model("yourmt3")
print(f"YourMT3 checkpoint ready at: {path}")
PY

COPY handler.py /handler.py

# Fail the build if CUDA + YourMT3 cannot be imported and the checkpoint is absent.
RUN python - <<'PY'
import os
import torch
from pathlib import Path
from mt3_infer import get_model_info

print("Torch:", torch.__version__)
print("CUDA available during build:", torch.cuda.is_available())
print("YourMT3 info:", get_model_info("yourmt3").get("name"))
checkpoint_root = Path(os.environ["MT3_CHECKPOINT_DIR"])
if not any(checkpoint_root.rglob("*")):
    raise SystemExit("ERROR: YourMT3 checkpoint was not downloaded into the image")
print("Checkpoint files present under:", checkpoint_root)
PY

CMD ["python", "-u", "/handler.py"]
