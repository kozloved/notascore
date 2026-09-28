# OSMD render inspection (automated visual check)

Engine package regenerated with production OSMD config
(`evaluation/osmd_config.json` + `evaluation/render_osmd.mjs`).
This is **not** musician sign-off and is **not** a musical-quality rating.

## Summary

| Check | Result |
|---|---|
| Cases with v1 + v2 OSMD HTML/PNG/SVG | **15 / 15** |
| `visual_status.json` status | **passed** for all 30 renders |
| Clefs present (G2 + F4 grand staff) | **15 / 15** |
| Key signature present (C / 0 fifths) | **15 / 15** |
| Meter matches candidate metadata | **15 / 15** (incl. `3/4`, `6/8`) |
| At least one complete OSMD page | **15 / 15** |

## Rendering observations (separate from musical quality)

1. **Sparse page layout.** Short examples occupy the top-left of a full page;
   large blank area below. Usable for review; not a cropping failure.
2. **Empty bass staff without whole rests.** Several RH-only examples leave
   the bass staff blank (no whole-measure rest). Report as a notation /
   rest-spelling observation for musicians — OSMD still draws clef + meter.
3. **Version spelling differences.** e.g. `dev-detached-triplets` v2 shows
   explicit triplet brackets; compare v1 carefully. Record per-version notes
   in `dimensions.*.versions.v1` / `.v2` when they diverge.
4. **Held-out `hold-meter-6-8`.** Meter `6/8` is displayed; musicians should
   still judge whether measure fill / beaming feels complete. That is a
   musical judgment, not an OSMD crash.

## Not claimed

- No acoustic accuracy.
- No attributed musician acceptance.
- No P1 completion.
