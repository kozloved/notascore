# Development split

Use this corpus to diagnose failures and guide future improvements.

## Add a case

```
development/<case_id>/
  input.wav
  reference.mid
  case.yaml      # optional
```

Then:

```bash
python -m evaluation.runner --case <case_id>
# or
python -m evaluation.runner --split development
```

Do not place the same `performance_id` (or shared reference MIDI) in both
`development/` and `holdout/`.
