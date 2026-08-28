FROM pytorch/pytorch:2.4.1-cuda12.4-cudnn9-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MT3_MODEL=yourmt3 \
    MT3_WARMUP=1 \
    PORT=8090

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    git-lfs \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install

COPY requirements.txt .
# The base image already has CUDA torch. Install inference extras without
# replacing it with a CPU wheel from default PyPI.
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY mt3_gpu_worker.py start.sh ./
RUN chmod +x start.sh

EXPOSE 8090

CMD ["./start.sh"]
