# NotaScore YourMT3 RunPod Worker

GPU worker for NotaScore polyphonic transcription.

## What is in Git?

Keep the **Dockerfile, handler, requirements, and deployment documentation** in Git.
Do **not** commit model weights, audio files, MIDI test outputs, API keys, or `.env` files.

The image currently downloads the YourMT3 checkpoint during `docker build`, so the
checkpoint is part of the resulting container image. This is intentionally the
first reproducible experiment. RunPod's cached-model mechanism can be evaluated
later if it produces faster/cheaper cold starts.

## Model

- `mt3-infer==0.2.0`
- `yourmt3`
- Default checkpoint: `YPTF.MoE+Multi (noPS)`
- CUDA: 12.6 runtime
- PyTorch: 2.7.1 + cu126

## Build

From the repository root:

```bash
docker build --platform linux/amd64 -t notascore-yourmt3:0.1 ./mt3-worker
```

On an Apple Silicon Mac, `--platform linux/amd64` is required for a RunPod-compatible image.

The build downloads the ~536 MB YourMT3 checkpoint and verifies that the checkpoint can be loaded.

## Local GPU test

On a CUDA machine:

```bash
docker run --rm --gpus all \
  -e MODEL_NAME=yourmt3 \
  -e MT3_DEVICE=cuda \
  notascore-yourmt3:0.1
```

For a real job, use the RunPod test request below after deployment.

## RunPod endpoint

Create a **Queue-based Serverless endpoint** from this image/repository.
Recommended first-test settings:

- Min workers: `0`
- Max workers: `1`
- FlashBoot: `ON`
- Idle timeout: `300` seconds while benchmarking
- Execution timeout: `600` seconds
- GPU: 24 GB-class NVIDIA GPU

The worker loads the model once at process startup and reuses it for subsequent jobs.

## Input

```json
{
  "input": {
    "audio_base64": "...",
    "filename": "recording.wav"
  }
}
```

The handler accepts WAV/MP3/etc. that `soundfile` can decode. For the first test,
use WAV. Stereo audio is downmixed to mono; no NotaScore post-processing or quantization
is performed in this worker.

## Output

```json
{
  "midi_base64": "...",
  "model": "yourmt3",
  "timing": {
    "model_load_seconds": 0,
    "inference_seconds": 0,
    "total_seconds": 0
  }
}
```

The timing fields are intentionally exposed so we can measure cold-start/model-load/inference costs.

## Important: do not connect NotaScore yet

First prove this chain:

```text
WAV
  -> RunPod worker
  -> YourMT3
  -> MIDI
```

Then compare cold and warm requests. Only after that should `MT3_ENDPOINT` in NotaScore be pointed at the RunPod endpoint.
