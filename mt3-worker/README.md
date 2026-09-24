# NotaScore YourMT3 RunPod Worker

This folder is the **real** RunPod Serverless image (`kozloved/notascore-yourmt3`).
YourMT3 loads once, after the worker connects to RunPod. The worker returns MIDI only.

## GPU (required)

This image **cannot** run Blackwell. RunPod logs look like:

```
NVIDIA RTX PRO 6000 Blackwell ... sm_120 is not compatible
CUDA error: no kernel image is available for execution on the device
```

In the endpoint **GPU** list, pick **one** of:

- RTX 4090
- RTX 3090
- A40
- L40
- RTX 6000 Ada

Do **not** pick RTX PRO 6000 Blackwell, B200, or any other Blackwell card.

## Stuck on Initializing

RunPod shows **Initializing** until the container process calls `runpod.serverless.start()`.
Logs do not appear until that happens. One job sitting in queue with a worker
frozen on Initializing means the GPU never became **Running**.

Unstick (do this now, then send only one new job):

1. Open the endpoint → **Requests** → **Cancel** the queued job.
2. Open **Workers**. If one is Initializing, stop / terminate it.
3. **GPU**: only RTX 4090 (or 3090 / A40 / L40 / 6000 Ada). Uncheck Blackwell.
4. **Redeploy**.
5. Wait until a worker is **Running**. Then send one test. Do not retry while Initializing.

If it freezes again with **no logs**, the image is still pulling or the GPU node is bad.
Turn **Flash Boot off**, Redeploy, and pick 4090 only.

## Build (required: linux/amd64)

From the repository root, on the machine with Docker:

```bash
git pull origin main
docker login
docker buildx build --platform linux/amd64 \
  -t kozloved/notascore-yourmt3:0.3 \
  --push \
  ./mt3-worker
```

On an Apple Silicon Mac, `--platform linux/amd64` is mandatory. Without it, RunPod fails with `IMAGE_PULL_ERROR` / `no matching manifest for linux/amd64`.

The build downloads the ~536 MB checkpoint. It is slow. Tag `0.3` pins `transformers==4.43.4`. Tag `0.2` pulls a newer Transformers and crashes with `cache_position` / `'NoneType' object is not subscriptable`.

## RunPod endpoint

https://www.runpod.io/console/serverless

Keep **min workers at 0** so you are not billed for an idle GPU all day.
Create does not send a warmup job. The first polyphonic transcription
queues with `/run` and polls `/status` until MIDI is ready (cold start
often takes more than five minutes). After a job, the worker should stay up
for a few minutes in case they retry.

- Image: `kozloved/notascore-yourmt3:0.3`
- GPU: RTX 4090 (or A40 / L40 / 3090 if 4090 queues)
- **Min workers: 0**
- Max workers: 1
- **Idle Timeout: 300** seconds (not the default 5)
- Flash Boot: on
- Execution timeout: 600 seconds
- After a crash or image change, workers stay **Unhealthy** until you **Redeploy**

Copy the endpoint ID from the browser URL
(`.../endpoint/<ID>?tab=...`). Use that exact ID on the VPS.

## Console test

The console wraps your JSON as `input`. Paste **only**:

```json
{
  "audio_base64": "<real base64, not this sentence>",
  "filename": "clip.wav"
}
```

On a Mac, copy real base64 from a short wav:

```bash
base64 -i /path/to/short.wav | pbcopy
```

Wait until **running workers is not 0**, then send the request.

## NotaScore VPS

```env
MT3_ENDPOINT=https://api.runpod.ai/v2/<ENDPOINT_ID>/runsync
MT3_API_KEY=<RunPod Settings → API Keys>
```

Recreate `api` and `worker` after editing `.env.production`.
