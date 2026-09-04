# NotaScore YourMT3 / MT3-Infer RunPod Serverless worker
#
# IMPORTANT: the model checkpoint is downloaded during image build, not when a
# user sends a job. This avoids a model download during every cold start.
#
# Build on Apple Silicon/other ARM machines with:
#   docker build --platform linux/amd64 -t <registry>/notascore-yourmt3:0.3 .

# RunPod GPUs are linux/amd64. On an Apple Silicon Mac you MUST pass
#   docker build --platform linux/amd64
# or this FROM pin. An arm64 image fails with IMAGE_PULL_ERROR.
FROM --platform=linux/amd64 nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MT3_CHECKPOINT_DIR=/opt/mt3_checkpoints \
    MODEL_NAME=yourmt3 \
    MT3_DEVICE=cuda

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

# The NotaScore repository currently targets mt3-infer 0.2.0.
# PyTorch 2.7.1 + CUDA 12.6 matches the YourMT3 benchmark environment
# documented by mt3-infer.
RUN python -m pip install \
        torch==2.7.1+cu126 \
        torchaudio==2.7.1+cu126 \
        --index-url https://download.pytorch.org/whl/cu126

COPY requirements.txt /requirements.txt
RUN python -m pip install --no-cache-dir -r /requirements.txt \
    && python -c "import transformers; v=transformers.__version__; assert v.startswith('4.43.'), v"

# Download the default YourMT3 checkpoint at BUILD time. mt3-infer documents
# this as the YPTF.MoE+Multi (noPS) checkpoint. The resulting ~536 MB model is
# stored in the image under /opt/mt3_checkpoints.
RUN mkdir -p "${MT3_CHECKPOINT_DIR}" \
    && python -c 'from mt3_infer import download_model; print(download_model("yourmt3"))'

COPY handler.py /handler.py
COPY payload.py /payload.py
COPY gpu_compat.py /gpu_compat.py

# Validate that the package can resolve the pre-downloaded checkpoint without
# attempting another network download. We do not load CUDA weights at build
# time because Docker builds do not require a GPU.
RUN python - <<'PY'
import os
from pathlib import Path
from mt3_infer import load_model

root = Path(os.environ["MT3_CHECKPOINT_DIR"])
files = [p for p in root.rglob("*") if p.is_file()]
if not files:
    raise SystemExit("ERROR: YourMT3 checkpoint is missing from the image")
print(f"Checkpoint files: {len(files)}")
print(f"Checkpoint bytes: {sum(p.stat().st_size for p in files):,}")
import transformers
assert transformers.__version__.startswith("4.43."), transformers.__version__
model = load_model("yourmt3", device="cpu", auto_download=False)
print("YourMT3 CPU checkpoint load: OK")
print("transformers", transformers.__version__)
# Release references before the build layer ends.
del model
PY

CMD ["python", "-u", "/handler.py"]
