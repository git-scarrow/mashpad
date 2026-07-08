# mashpad

Local-first mashup compatibility workbench (prototype). Not a DJ app, not
a desktop app yet. The question this repo answers: can two local songs be
analyzed well enough to suggest plausible mashup pairings?

## Commands

```bash
uv sync                          # install deps
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mashcheck a.mp3 b.mp3     # run the CLI
```

## Model: mashup moves, not just "two tracks"

A mashup candidate is Track A *in a role* over Track B *in another role*,
using a specific move type — not just "Track A + Track B." See
`docs/mashup-move-taxonomy.md` for the move types and their v0 support
status (supported / partial / out_of_scope), and `mashpad.models` for
`MashupMoveType`, `TrackRole`, `CompatibilityProfile`. Compatibility is
asymmetric: swapping which track is `vocal` vs `instrumental` is a
different evaluation, not a relabeling — see `mashpad.scoring.evaluate_move`.

## Architecture

- `src/mashpad/analysis/` — tempo/key/section estimation. **Currently
  deterministic stubs** (seeded from file name, not real audio content).
  Each stub file has a `TODO(real analysis)` docstring marking the seam.
- `src/mashpad/scoring/` — real, tested logic: tempo compatibility
  (including half/double-time), harmonic compatibility (circle-of-fifths
  key relations), phrase fit (section-confidence based), arrangement
  contrast and vocal/bass collision penalty (real math, but need caller-
  supplied inputs — no analyzer produces them yet), composite scoring
  with configurable weights, candidate ranking. `evaluate_move()` in
  `scoring/__init__.py` is the top-level entry point. This is a
  **hypothesis over structured analysis inputs, not validated real-audio
  judgment** — v0-usable with confidence scores and manual override, not
  "reliable."
- `src/mashpad/overrides.py` — applies a `ManualOverride` (BPM
  multiplier, key replacement, phrase-boundary shift) to a
  `TrackAnalysis`. Downbeat/stem-gain overrides are modeled but not yet
  applicable (no beat-grid/stem data) — raises `NotImplementedError`
  rather than silently no-op.
- `src/mashpad/io/audio_file.py` — file validation only, no decoding yet.
- `src/mashpad/report/` — text report rendering; states the assumed move
  type and role assignment explicitly.
- `src/mashpad/cli.py` — `mashcheck` entry point. `build_report()` is
  pure (no file I/O) so tests can drive it with fixture `TrackAnalysis`
  objects; `run()`/`main()` wire it to real files.

## Guardrails

- Do not commit audio files, even short clips. See `fixtures/README.md`.
- Do not add real DSP dependencies (librosa, aubio, demucs, etc.) without
  discussing it first — the stubs are intentional for this stage.
- Do not make licensing claims about audio sources.
- Keep stub seams explicit (`TODO(real analysis)` + deterministic
  placeholder) rather than faking a "complete" implementation.
- Tests must stay deterministic — no real audio analysis in the test
  suite; use JSON fixtures (`tests/fixtures/*.json`) or the seeded stubs.
- Don't score out-of-scope move types as if supported (`scores=None`,
  not a fabricated number) and don't claim a dimension is measured
  (`CollisionProfile.measured`, `arrangement_contrast_score`) when
  nothing actually estimated it.
- Composite score weights are configurable defaults
  (`CompatibilityWeights`), not tuned/validated truth — see
  `docs/eval-plan.md`.

See `docs/decision-log.md` for why things are built this way, and
`docs/mashup-move-taxonomy.md` / `docs/eval-plan.md` for the move-type
and evaluation-corpus design.
