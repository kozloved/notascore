# Deploy NotaScore on Oracle Cloud (Always Free)

Run the full Docker Compose stack on an **Oracle Cloud Always Free** Ubuntu VM. The VM stays on 24/7 — no laptop, no Cloudflare Tunnel connector.

```text
Browser → Cloudflare (HTTPS, optional proxy) → Oracle VM :80/:443 → nginx → frontend /api
```

Two SSL options:

| Mode | When to use | DNS | TLS |
|------|-------------|-----|-----|
| **cloudflare** (default) | You already use Cloudflare for `notascore.com` | Orange-cloud A record → VM IP | Cloudflare terminates HTTPS |
| **letsencrypt** | Direct DNS or grey-cloud A record | A record → VM IP | Let's Encrypt on the VM |

---

## 1. Create an Oracle Cloud VM

1. Sign up at [cloud.oracle.com](https://cloud.oracle.com/) (Always Free tier).
2. **Compute → Instances → Create instance**
3. Recommended shape: **Ampere A1** (`VM.Standard.A1.Flex`)
   - **2 OCPUs, 12 GB RAM** is a good balance for Basic Pitch (free tier allows up to 4 OCPU / 24 GB total across VMs).
4. Image: **Ubuntu 22.04** (or 24.04).
5. Networking: assign a **public IPv4** address.
6. SSH key: add your public key (or let Oracle generate one — download the private key).

Note the instance **public IP** when it is running.

---

## 2. Open firewall ports (Oracle + VM)

### Oracle Cloud security list

**Networking → Virtual cloud networks → your VCN → Security Lists → Default Security List → Add ingress rules:**

| Source CIDR | Protocol | Port |
|-------------|----------|------|
| `0.0.0.0/0` | TCP | 22 |
| `0.0.0.0/0` | TCP | 80 |
| `0.0.0.0/0` | TCP | 443 |

(You can restrict 80/443 to [Cloudflare IP ranges](https://www.cloudflare.com/ips/) if you use orange-cloud proxy only.)

### Ubuntu UFW (on the VM)

```bash
sudo bash deploy/oracle/open-ports.sh
```

---

## 3. Install Docker on the VM

SSH in:

```bash
ssh ubuntu@YOUR_VM_PUBLIC_IP
```

Clone the repo (or skip to bootstrap which clones for you):

```bash
git clone --branch cursor/oracle-deploy-setup-6c3d \
  https://github.com/kozloved/notascore.git ~/notascore
cd ~/notascore/audio2score-week4
```

Install Docker:

```bash
sudo bash deploy/oracle/install-docker.sh
# log out and back in so 'docker' group applies
exit
```

Optional — add swap on small instances:

```bash
sudo bash deploy/oracle/setup-swap.sh
```

---

## 4. Point DNS at the VM

In **Cloudflare** (domain already active on Cloudflare):

1. **DNS → Records**
2. Delete any tunnel CNAMEs for `@` and `www` if you were testing the local tunnel.
3. Add:

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | `@` | `YOUR_VM_PUBLIC_IP` | Proxied (orange cloud) |
| A | `www` | `YOUR_VM_PUBLIC_IP` | Proxied |

4. **SSL/TLS → Overview → Full** (not Flexible).

You do **not** need a Cloudflare Tunnel for this setup.

---

## 5. Bootstrap the app

### Option A — Cloudflare proxy (recommended)

```bash
cd ~/notascore/audio2score-week4
MODE=cloudflare DOMAIN=notascore.com ./deploy/oracle/bootstrap.sh
```

### Option B — Let's Encrypt on the VM

Grey-cloud the A records (DNS only), then:

```bash
MODE=letsencrypt EMAIL=you@example.com DOMAIN=notascore.com ./deploy/oracle/bootstrap.sh
```

### One-liner on a fresh VM (after Docker is installed)

```bash
curl -fsSL https://raw.githubusercontent.com/kozloved/notascore/cursor/oracle-deploy-setup-6c3d/audio2score-week4/deploy/oracle/bootstrap.sh \
  | bash -s -- cloudflare
```

---

## 6. Verify

On the VM:

```bash
curl -fsS http://localhost/api/health
docker compose ps
docker compose logs -f worker
```

From your laptop (after DNS propagates):

```bash
curl -fsS https://notascore.com/api/health
BASE_URL=https://notascore.com/api ./deploy/smoke-test.sh
```

---

## 7. Updates

```bash
cd ~/notascore/audio2score-week4
git pull origin cursor/oracle-deploy-setup-6c3d
MODE=cloudflare ./deploy/start-oracle.sh
```

---

## Environment variables

Copy and edit `.env.production` (bootstrap creates it from the example):

```env
# Leave empty on Oracle — no tunnel connector
CLOUDFLARE_TUNNEL_TOKEN=

NEXT_PUBLIC_API_URL=https://notascore.com/api
CORS_ORIGIN=https://notascore.com,https://www.notascore.com
```

Optional: set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to store uploads in Supabase Storage instead of local Docker volumes.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Site unreachable | Check OCI security list + UFW; confirm A record points to VM IP |
| 502 from Cloudflare | `docker compose ps` — ensure nginx/api/frontend are up; `curl localhost/api/health` |
| SSL errors | Cloudflare mode: use **Full**, not Flexible. LE mode: re-run `init-tls.sh` |
| Transcription fails / OOM | Increase VM RAM or run `setup-swap.sh`; check `docker compose logs worker` |
| Still using tunnel CNAMEs | Remove tunnel hostnames in Zero Trust; use A records to VM IP |

---

## Compare with local + tunnel

| | Local + tunnel | Oracle VM |
|--|----------------|-----------|
| Machine must stay on | Your PC | Oracle VM (always on) |
| Cloudflare Tunnel token | Required | Not used |
| Router port forwarding | Not needed | Not needed |
| Cost | Free (your electricity) | Oracle Always Free |

See also: [../README.md](../README.md) (local Cloudflare Tunnel path).
