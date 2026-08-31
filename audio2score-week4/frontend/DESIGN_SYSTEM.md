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

- Public: NotaScore · How it works · Examples · Log in · **Create a score**
- App: Create · My Scores · Account
- Mobile app: bottom tabs Create / Scores / Account

## What was preserved

- `POST /upload` and job polling
- Solo / polyphonic `mode` values sent to the API
- `SheetResult` OSMD preview
- MIDI, score MIDI, MusicXML, and PDF downloads
- `ListenPreview` playback
- Supabase Google sign-in on `/login`

## Known issues

- `/dashboard` is still an upload workspace, not a score library (`listJobs` exists but is unused).
- There is no Pricing page yet; the public nav omits it.
- Examples currently points at the live create flow.
- No frontend unit tests existed; Pass 1 did not add a test runner.
