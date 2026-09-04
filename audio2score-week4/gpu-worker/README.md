# Polyphonic GPU worker (YourMT3 via mt3-infer 0.2.0)

NotaScore **Solo** stays on CPU Basic Pitch. **Polyphonic** POSTs audio here and expects MIDI.

This worker runs the **latest production MT3-family toolkit**: [`mt3-infer` 0.2.0](https://pypi.org/project/mt3-infer/) (July 2026). Default model is **YourMT3** (`YPTF.MoE+Multi`), the current polyphonic / multi-stem descendant of Magenta MT3.

| `MT3_MODEL` | What it is | Weights | Notes |
|---|---|---|---|
| `yourmt3` (default) | YourMT3+ (MLSP 2024) | ~536 MB | Best multi-instrument polyphony |
| `mt3_pytorch` | Official MT3 architecture in PyTorch | ~176 MB | Closest to Magenta MT3 |
| `mr_mt3` | Multi-resolution MT3 | ~176 MB | Fastest |

**12 GB VRAM is enough** (RTX 3060 / 4070 / 4000 Ada). YourMT3 sits in a few GB. You do not need a 4090.

This Cloud Agent cannot log into Vast.ai or RunPod. Rent the GPU, start the worker, then point NotaScore at the public URL.

## Architecture

```text
Browser → notascore.com (CPU: Next.js + FastAPI + Redis)
                │  Polyphonic jobs only
                ▼
         Vast.ai GPU  POST /transcribe  → MIDI
```

The site does **not** need a GPU. Only this worker does.

## 1. Rent a Vast.ai GPU (recommended)

1. Create an account at [vast.ai](https://vast.ai/).
2. Search for an **RTX 3060 12 GB** or better, **PyTorch + CUDA 12.x** template, Python 3.10/3.11, disk ≥ 40 GB (YourMT3 checkpoint + git-lfs).
3. Open **port 8090** (Direct TCP / extra ports). Interruptible instances are cheaper; on-demand is more stable.
4. Launch, then SSH in.

Copy this folder onto the pod (`audio2score-week4/gpu-worker/`), then:

```bash
cd audio2score-week4/gpu-worker   # or /workspace/notascore-gpu
export MT3_API_KEY='pick-a-long-random-secret'
export MT3_MODEL=yourmt3
export MT3_CHECKPOINT_DIR=/workspace/mt3-checkpoints
chmod +x vast.onstart.sh start.sh
./vast.onstart.sh
```

First boot downloads ~536 MB of YourMT3 weights. Health check on the pod:

```bash
curl -s http://127.0.0.1:8090/health
```

Expect `"cuda": true`, `"model": "yourmt3"`, `"toolkit_version": "0.2.0"`.

Vast.ai maps `8090` to a public `IP:PORT`. Test from your laptop:

```bash
curl -sS -X POST "http://<vast-ip>:<mapped-port>/transcribe" \
  -H "Authorization: Bearer pick-a-long-random-secret" \
  -F "file=@clip.wav" \
  -o out.mid
file out.mid   # should say Standard MIDI
```

## 2. Docker image (optional)

From this folder, with an NVIDIA GPU and nvidia-container-toolkit:

```bash
docker build -t notascore-mt3-gpu .
docker run --gpus all -p 8090:8090 \
  -e MT3_API_KEY='pick-a-long-random-secret' \
  -e MT3_MODEL=yourmt3 \
  notascore-mt3-gpu
```

On Vast.ai you can also point the instance at this image after you push it to a registry.

## 3. RunPod Serverless

There is **no pod-proxy URL** for Serverless. The only address is:

```
https://api.runpod.ai/v2/<endpoint-id>/runsync
```

The image must run `handler.py` (RunPod protocol: JSON `input.audio_base64` → `midi_base64`). `kozloved/notascore-yourmt3:0.1` started the HTTP server only, so `/runsync` could not return MIDI.

RunPod workers are **linux/amd64**. If you build on an Apple Silicon Mac without `--platform linux/amd64`, Docker Hub stores an arm64 image and RunPod fails with `IMAGE_PULL_ERROR` / `no matching manifest for linux/amd64`.

Build and push from this folder (slow on a Mac because it emulates amd64):

```bash
cd audio2score-week4/gpu-worker
docker buildx build --platform linux/amd64 -t kozloved/notascore-yourmt3:0.2 --push .
```

Or:

```bash
chmod +x build-and-push.sh
./build-and-push.sh kozloved/notascore-yourmt3:0.2
```

Confirm the Hub tag shows `linux/amd64` before redeploying. In RunPod **Serverless → Endpoints**, set the worker image to `kozloved/notascore-yourmt3:0.2` and **redeploy**.

On the VPS `.env.production`:

```env
MT3_ENDPOINT=https://api.runpod.ai/v2/<endpoint-id>/runsync
MT3_API_KEY=<your RunPod API key from RunPod Settings → API Keys>
```

`MT3_API_KEY` must be the RunPod account API key, not a random worker secret. Recreate `api` and `worker` after editing.

Do not put `MT3_API_KEY` in the browser.

## 4. Point NotaScore at it

On the **CPU** machine that runs FastAPI (not the GPU):

```env
MT3_ENDPOINT=http://<vast-ip>:<mapped-port>/transcribe
MT3_API_KEY=pick-a-long-random-secret
MT3_MODEL=yourmt3
MT3_TIMEOUT_SECONDS=300
```

Restart API + RQ worker. `/health` should show `modes.polyphonic: true` (and the legacy alias `quality.available: true`). In the UI, **Polyphonic** becomes selectable.

## If pip broke CUDA

```bash
python -c "import torch; print(torch.cuda.is_available())"   # False = broken
# Reinstall the CUDA wheel that matches the image, e.g. CUDA 12.4:
pip install --index-url https://download.pytorch.org/whl/cu124 torch torchaudio
```

Then retry `load_model('yourmt3', device='cuda')`.

## Cost

- Vast.ai interruptible RTX 3060 12 GB is typically well under $0.20/hr
- Idle with the instance **destroyed**: $0 (you pay disk only if you keep a volume)
- Idle with the instance **running**: you still pay the GPU hourly rate
- A short piano clip on 12 GB is typically seconds to a minute after the model is loaded

Destroy or stop the instance when you are not transcribing.
