# Deploy NotaScore on Oracle Always Free

Stack: Nginx (TLS) → Next.js + FastAPI + Redis + RQ worker on one Ampere VM.

## 0. Oracle VM + DNS (do this first)

> As of the packaging smoke check, `notascore.com` resolved to an **AWS** host (`54.149.79.189`, OpenResty parking), not an Oracle VM — SSH:22 timed out. You must create the Ampere instance and **repoint the A records** before bootstrap.

1. Create an Always Free **Ampere A1** Ubuntu 22.04/24.04 instance (2–4 OCPUs, 12–24 GB RAM).
2. Attach a public IP. In the VCN security list / NSG allow inbound **22, 80, 443**.
3. Point DNS for `notascore.com` (replace the current AWS parking IP):
   - `A` `@` → **Oracle** VM public IP
   - `A` `www` → same IP
4. Confirm SSH: `ssh ubuntu@<PUBLIC_IP>`
5. Push this repo’s deploy packaging to `main` first (`docker-compose.yml`, Dockerfiles, `deploy/`, `nginx/`) so the VM `git clone` has it.

## 1. Install Docker on the VM

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
# log out and back in so docker works without sudo
```

## 2. Clone and configure

```bash
cd ~
git clone https://github.com/kozloved/notascore.git
cd notascore/audio2score-week4
cp .env.production.example .env.production
# Defaults already target https://notascore.com for CORS + NEXT_PUBLIC_API_URL
```

## 3. Bring up the stack + TLS

First start on HTTP (ACME needs port 80), then issue certs:

```bash
cp nginx/notascore.http.conf nginx/notascore.conf
docker compose up -d --build

EMAIL=you@example.com ./deploy/init-tls.sh
```

`init-tls.sh` requests Let's Encrypt certs for `notascore.com` + `www`, writes SSL helpers, and switches Nginx to `nginx/notascore.tls.conf`.

Optional renew loop:

```bash
docker compose --profile certbot up -d certbot
```

## 4. Smoke test

```bash
curl -fsS https://notascore.com/ | head
curl -fsS https://notascore.com/api/health

# CLI upload → poll → MusicXML download
curl -fsS -F "file=@./backend/test_tone.wav;type=audio/wav" \
  https://notascore.com/api/upload
# then poll GET /api/jobs/<job_id> until status=completed
# then GET /api/jobs/<job_id>/result

docker compose logs -f worker
```

Local packaging check (HTTP, before Oracle DNS/TLS):

```bash
cp nginx/notascore.http.conf nginx/notascore.conf
cp .env.production.example .env.production
# set NEXT_PUBLIC_API_URL=http://localhost/api and CORS_ORIGIN=http://localhost
NEXT_PUBLIC_API_URL=http://localhost/api docker compose up -d --build
curl -fsS http://localhost/api/health
```

## 5. Ongoing updates (latest pushed `main`)

```bash
cd ~/notascore/audio2score-week4
git pull origin main
docker compose up -d --build
```

## API proxy mapping

| Browser | Nginx | FastAPI |
|---------|-------|---------|
| `https://notascore.com/api/upload` | `location /api/` → `proxy_pass http://api:8000/` | `POST /upload` |
| `https://notascore.com/api/jobs/{id}` | same | `GET /jobs/{id}` |
| `https://notascore.com/api/jobs/{id}/result` | same | `GET /jobs/{id}/result` |

- Frontend build: `NEXT_PUBLIC_API_URL=https://notascore.com/api`
- Backend CORS: `CORS_ORIGIN=https://notascore.com,https://www.notascore.com`

## Notes

- Redis stays on the Docker network only (not published).
- Uploads / results / SQLite use named Docker volumes.
- First Basic Pitch image build on Ampere can take a long time.
- Do **not** run MR-MT3 on this free VM (needs a separate GPU host later).
