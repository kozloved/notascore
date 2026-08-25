# Holdout split

Reserved for checking generalization.

**HOLDOUT EVALUATION** reports are marked clearly. Do not repeatedly tune the
production implementation against individual holdout cases.

Different audio renders of the same MIDI performance must not be split between
`development/` and `holdout/`. Share a `performance_id` in `case.yaml` for
paired renders so the runner can detect leakage.
