# Base image for the NotaScore / Audio2Score dev environment.
#
# node:22-bookworm gives us Node 22 (for the Next.js frontend) and Debian
# bookworm, whose default Python is 3.11. Python 3.11 is required because the
# transcription stack (basic-pitch + tensorflow<2.15.1) has no wheels for 3.12.
FROM node:22-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-venv \
        python3.11-dev \
        redis-server \
        ffmpeg \
        build-essential \
        git \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*
