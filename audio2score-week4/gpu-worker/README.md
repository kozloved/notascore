# Quality GPU worker (MR-MT3)

NotaScore Fast stays on CPU. Quality POSTs audio here and expects MIDI.

**RTX 4000 Ada 20 GB is enough.** MR-MT3 weights are ~176 MB. Inference usually sits in a few GB of VRAM. 20 GB leaves headroom. You do not need a 4090.

This Cloud Agent cannot log into your GPU rental. Run the steps on the GPU pod, then point NotaScore at the public URL.

## 1. Rent the pod

Use a **PyTorch + CUDA** template (CUDA 12.x, Python 3.10 or 3.11).

- GPU: RTX 4000 Ada 20 GB (~$0.28/hr is fine)
- Disk: ≥ 20 GB (checkpoints + pip)
- Expose **HTTP port 8090** (RunPod: Connect → HTTP services / TCP port)

Stop the pod when you are not transcribing. 24h on = about $7.

## 2. On the GPU box

SSH in, then:

```bash
python -c "import torch; print(torch.__version__, 'cuda', torch.cuda.is_available())"
```

You want `cuda True`. If it prints `False`, pick a different PyTorch template — do not `pip install torch` from default PyPI (that often replaces CUDA torch with CPU torch).

Copy this folder onto the pod (git clone the repo, or scp `gpu-worker/`), then:

```bash
cd audio2score-week4/gpu-worker   # or wherever you copied it
python -m pip install -U pip
python -m pip install -r requirements.txt

# First run downloads ~176 MB of MR-MT3 weights
python -c "from mt3_infer import load_model; load_model('mr_mt3', device='cuda'); print('ok')"

export MT3_API_KEY='pick-a-long-random-secret'
chmod +x start.sh
./start.sh
```

Health check on the pod:

```bash
curl -s http://127.0.0.1:8090/health
```

Expect `"cuda": true` and `"vram_gb": 20` (or similar).

## 3. Public URL

RunPod usually gives something like:

`https://<pod-id>-8090.proxy.runpod.net`

Test from your laptop (not from inside the pod):

```bash
curl -sS -X POST "https://<pod-id>-8090.proxy.runpod.net/transcribe" \
  -H "Authorization: Bearer pick-a-long-random-secret" \
  -F "file=@clip.wav" \
  -o out.mid
file out.mid   # should say Standard MIDI
```

## 4. Point NotaScore at it

On the machine that runs FastAPI (not the GPU):

```env
MT3_ENDPOINT=https://<pod-id>-8090.proxy.runpod.net/transcribe
MT3_API_KEY=pick-a-long-random-secret
MT3_TIMEOUT_SECONDS=300
```

Restart API + RQ worker. `/health` should show `quality.available: true`. In the UI, Quality becomes selectable.

## If pip broke CUDA

```bash
python -c "import torch; print(torch.cuda.is_available())"   # False = broken
# Reinstall the CUDA wheel that matches the image, e.g. CUDA 12.4:
pip install --index-url https://download.pytorch.org/whl/cu124 torch torchaudio
```

Then retry `load_model('mr_mt3', device='cuda')`.

## Cost

- Idle with the pod **stopped**: $0
- Idle with the pod **running** (even no jobs): ~$0.28/hr
- A short piano clip on Ada 4000 is typically seconds to a minute after the model is loaded

Keep one pod for tests; stop it when you are done.
