# Model and checkpoint licenses (next-gen adapters)

Commercial hosted SaaS. Do not enable a provider until both **code** and
**checkpoint** licenses are compatible. Large weights are never committed.

| Provider | Role | In-tree status | Code | Checkpoints | SaaS note |
|---|---|---|---|---|---|
| Basic Pitch (Spotify) | Solo / stem AMT | Production adapter | Apache-2.0 (verify pin) | Model cards in package | Already used for Solo |
| Remote YourMT3 worker | Full-mix polyphonic AMT | `mt3-worker/` image, HTTP only | Magenta / YourMT3 lineage is **not** imported into the API process | Worker image downloads weights at build | Keep remote. Do not vendor GPL worker code into `audio2score-week4/backend` |
| PM2S | Piano hands / rhythm | Opt-in, missing weights → fallback | Check PyPI/`pm2s` | Separate weights | Remain optional |
| Transkun V2 | Piano specialist AMT | Adapter **disabled** | Unknown until vendored | Unknown | Feature flag `NEXTGEN_TRANSKUN=0` |
| MelBand-RoFormer / BS-RoFormer | Stems | Adapter **disabled** | Often MIT/Apache *or* research-only — confirm the exact repo | Checkpoints often non-commercial | Feature flag `NEXTGEN_SEPARATION=0`. Do not fake stems |
| Beat This! | Beats / downbeats | Adapter **disabled** | Confirm before enable | Confirm before enable | Feature flag `NEXTGEN_BEAT_THIS=0`. madmom tracker remains fallback |
| All-In-One | Structure | Not wired | — | — | Future |

If license is uncertain, the adapter exists, reports `unavailable`, and must not
run in production.
