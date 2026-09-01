# NotaScore design system (Pass 1)

Semantic tokens, theme, and reusable UI foundation. The transcription engine, job API, OSMD score renderer, and export endpoints are unchanged.

## Theme

Preference is stored in `localStorage` as `notascore-theme`: `system` | `light` | `dark`.

`data-theme` on `<html>` plus a boot script in `app/layout.jsx` prevent a flash of the wrong theme.

| Token | Light | Dark |
|---|---|---|
| background | `#F6F3EC` | `#0B1018` |
| surface | `#FFFC F7` | `#121A25` |
| text-primary | `#101A2C` | `#F3EEE6` |
| primary (CTA) | navy | warm ivory |
| accent | muted orange, used sparingly | muted orange |
| score-paper | `#F7F1E6` in both themes | same |

The application chrome follows the theme. The score preview stays paper-like in dark mode.

## Typography

- UI: **Inter** (`--font-sans`)
- Display: **Instrument Serif** (`--font-display`)

Styles: `display`, `h1`–`h3`, `body-large`, `body`, `body-small`, `label`, `caption`, `metadata`.

## Components

Added under `components/`:

- `theme/ThemeProvider`, `ThemeToggle`
- `layout/AppShell`, `PublicNavbar`, `AppNavbar`, `MobileTabBar`, `Container`, `Wordmark`
- `ui/Button`, `IconButton`, `Card`, `Alert`, `SegmentedControl`, `Text`

Icons: **Lucide** (`lucide-react`).

## Navigation

- Public: NotaScore · How it works · Examples · Pricing · Log in · **Create a score**
- App: Create · My Scores · Account avatar
- Mobile app: bottom tabs Create / Scores / Account

## Public product (Pass 2)

Routes: `/`, `/how-it-works`, `/examples`, `/pricing`, `/login`, `/signup`, `/forgot-password`, `/verify-email`, `/create`, plus help/contact/legal.

Create flow lives at `/create` and still calls `POST /upload` without requiring an account. Sign-in uses the existing Supabase client (Google + email). Apple is not configured, so it is not shown.

Demo assets in `public/demo/` are a real transcription of a short piano figure, labelled as an example.

Analytics: first-party `track()` events only. No third-party pixels or cookies.

## What was preserved

- `POST /upload` and job polling
- Solo / polyphonic `mode` values sent to the API
- `SheetResult` OSMD preview
- MIDI, score MIDI, MusicXML, and PDF downloads
- `ListenPreview` playback
- Supabase Google sign-in on `/login` (now also email)

## Create workflow (Pass 3)

`/create` is a staged workspace: empty dropzone → local audio preview → one `POST /upload` → poll `GET /jobs/:id` → paper score.

Job id is stored in the URL (`?job=`) and in `localStorage` (`notascore-active-job`, `notascore-recent-jobs`) so refresh and My Scores can recover server-side work. Files chosen but not yet uploaded stay in memory only.

Instrument detection is not shown: the job API does not return a detected instrument. Ensemble remains an advanced option only when health says polyphonic is available. Default request is solo (“let NotaScore choose”).

My Scores lists jobs from this browser, not account ownership. The backend does not associate jobs with users.

No transcription-engine changes were made.

## Account-owned scores (Pass 4)

Authenticated scores are rows in the existing `jobs` table with `user_id` set from the Supabase JWT `sub`. There is no second database. FastAPI checks ownership on job/source/result/score routes. Unowned jobs remain readable by UUID until claimed, so create-before-login still works.

Upload now returns a one-time `claim_token` when anonymous. After login, the client calls `POST /scores/claim` (and `POST /scores/claim-unowned` for Pass 3 local IDs). Raw audio is never stored in localStorage.

My Scores (`/dashboard`) loads `GET /scores` for the signed-in user. Stable URLs are `/score/{id}`; `/results/{id}` redirects there.

`localStorage` remains a cache (`notascore-active-job`, `notascore-recent-jobs`), not the source of truth.

No transcription-engine changes were made.

## Mini score editor (Pass 5)

`/score/{id}` is a correction layer on top of the stored MusicXML. Notes are edited as `{ id, pitch, start, duration, velocity, track }` on a sixteenth-note grid. OSMD re-renders from MusicXML after save; it is not patched as the source of truth.

Original `{job_id}.musicxml` stays immutable. Edits persist as `{job_id}.edits.json`, `{job_id}.edited.musicxml`, and `{job_id}.edited.mid`. Reset restores the original files.

No transcription-engine changes were made.

## Known issues

- My Scores requires a configured Supabase project and `SUPABASE_JWT_SECRET` (or JWKS) on the API.
- Apple sign-in is not configured.
- Score thumbnails are placeholders; OSMD does not currently emit a library preview.
- Undo after delete is not implemented.
- Billing is not implemented; pricing pages describe structure only.
- Ensemble transcription may be offline depending on the workspace.
