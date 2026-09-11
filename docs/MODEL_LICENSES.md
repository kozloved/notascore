# Model and checkpoint licenses (next-gen adapters)

Commercial hosted SaaS. Do not enable a provider until both **code** and
**checkpoint** licenses are compatible. Large weights are never committed.

| Provider | Role | In-tree status | Code | Checkpoints | SaaS note |
|---|---|---|---|---|---|
| Basic Pitch (Spotify) | Solo / stem AMT | Production adapter | Apache-2.0 (verify pin) | Model cards in package | Already used for Solo |
| Remote YourMT3 worker | Full-mix polyphonic AMT | `mt3-worker/` image, HTTP only | Magenta / YourMT3 lineage is **not** imported into the API process | Worker image downloads weights at build | Keep remote. Do not vendor GPL worker code into `audio2score-week4/backend` |
| PM2S | Piano hands / rhythm | Opt-in, missing weights → fallback | Check PyPI/`pm2s` | Separate weights | Remain optional |
| Transkun V2 | Piano specialist AMT | Adapter **disabled** | Unknown until vendored | Unknown | Feature flag `NEXTGEN_TRANSKUN=0` |
| MelBand-RoFormer / BS-RoFormer | Stems | **HTTP adapter real; in-process inference disabled** | Architecture code (lucidrains/BS-RoFormer, openmirlab/melband-roformer-infer) is typically MIT | Community / paper checkpoints are **not** uniformly commercial: many Hugging Face drops have no weight license; Kimberley Jensen vocal weights are widely used but not a blanket SaaS grant; ByteDance research weights are not treated as commercially licensed here | `NEXTGEN_SEPARATION=0` by default. Production path is `SEPARATION_ENDPOINT` (the remote operator is responsible for the checkpoint they load). Do not load RoFormer into the API/RQ worker. Do not fake stems |
| Beat This! | Beats / downbeats | Adapter **disabled** | MIT (CPJKU `beat_this`, verify pin) | Official checkpoints typically CC-BY-4.0 research weights; **not** enabled for hosted SaaS until a commercial-compatible checkpoint is chosen | Feature flag `NEXTGEN_BEAT_THIS=0`. Production uses madmom/librosa through `ExistingBeatTrackerAdapter` → `MusicalTimeMap` |
| All-In-One | Structure | Not wired | — | — | Future |

If license is uncertain, the adapter exists, reports `unavailable`, and must not
run in production.

### Stem-separation checkpoint review (this increment)

Investigated 2026-09-11:

- **lucidrains/BS-RoFormer** — MIT code for the architecture. No official
  commercial SaaS checkpoint.
- **openmirlab/melband-roformer-infer** — MIT inference packaging. The README
  notes that many catalogued checkpoints are community files without an explicit
  weight license.
- **Kimberley Jensen MelBand Roformer vocals** — commonly redistributed; not
  treated here as a confirmed commercial hosted-SaaS grant.

Therefore in-process RoFormer remains **disabled**. The HTTP separator adapter is
license-neutral: it only talks to `SEPARATION_ENDPOINT`. Do not claim a
RoFormer model is production-enabled because the adapter exists.

