# mashpad

Local-first mashup compatibility workbench (prototype). Not a DJ app, not
a desktop app yet. The question this repo answers: can two local songs be
analyzed well enough to suggest plausible mashup pairings?

## Commands

```bash
uv sync                          # install deps (stdlib-only; no MIR libs)
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run mashcheck a.mp3 b.mp3     # run the CLI

uv sync --extra tempo-librosa    # opt in to the optional librosa tempo backend
uv run --extra tempo-librosa scripts/eval_tempo.py --backend librosa index.json
```

For real-audio tempo eval, prefer `uv run --extra tempo-librosa
scripts/eval_tempo.py --backend librosa ...`; use `energy_flux` for
zero-dependency checks; do not treat `autocorrelation` confidence as
meaningful. See `docs/tempo-eval.md` ("Current backend recommendation")
for the evidence and caveats.

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
- `src/mashpad/scoring/` — real, tested logic: candidate-aware tempo
  compatibility (`score_tempo_candidates`, searches every candidate-pair
  across both tracks' `tempo_candidates`, including half/double-time),
  harmonic compatibility (circle-of-fifths key relations), phrase fit
  (section-confidence based), arrangement contrast and vocal/bass
  collision penalty (real math, but need caller-supplied inputs — no
  analyzer produces them yet), composite scoring with configurable
  weights, candidate ranking. `evaluate_move()` in `scoring/__init__.py`
  is the top-level entry point; when a track has no `tempo_candidates` it
  falls back to a synthesized candidate set (clearly labeled
  `[fallback: ...]` in `CompatibilityProfile.tempo_explanation`), not a
  silent single-BPM comparison. This is a **hypothesis over structured
  analysis inputs, not validated real-audio judgment** — v0-usable with
  confidence scores and manual override, not "reliable." `hook_collision`
  / `rhythmic_graft` / `genre_contrast_blend` (`PARTIAL` support) use this
  same generic scoring and are explicitly *not* validated for their
  move-specific criteria — see the warning section in
  `docs/mashup-move-taxonomy.md`.
- `src/mashpad/scoring/verdict.py` — an **evidence-first calibration layer
  over the scores, not a scorer.** `assess_compatibility()` turns a
  `CompatibilityProfile` into a `CompatibilityVerdict`
  (`COMPATIBLE`/`MAYBE`/`UNLIKELY`/`UNCERTAIN`) with cited `EvidenceItem`s;
  it never recomputes or re-weights a component score. Confidence is
  deliberately asymmetric and **per-dimension**: a confident COMPATIBLE
  requires every dimension the move *decides on* to be `MEASURED` on **both**
  tracks (`CONFIDENCE_DECIDING_DIMENSIONS` — overlay needs
  tempo/key/sections/beatgrid/stems; transition_blend needs tempo/sections),
  while ruling a pair *out* (UNLIKELY) needs only tempo measured (easier to
  rule out than in). Partial moves have no row and stay capped at MAYBE; an
  empty deciding set is treated as "cannot be confident," never vacuously
  satisfied. So v0's filename-seeded `STUB` analysis can only reach MAYBE or
  UNCERTAIN — the default CLI no longer emits a flattering "strong"
  composite as the answer. Five gates force an explicit **UNCERTAIN**
  abstention: unsupported move, missing role premise, ambiguous BPM,
  multiple plausible tempo ratios, and a required low-confidence tempo
  override. Tempo ambiguity is read from a track's *real* `tempo_candidates`
  only (never the synthesized fallback), and a dominant-primary set like the
  stub's 0.6/0.25/0.15 is *not* flagged. See `docs/compatibility-verdict.md`
  (compatibility is **move-relative**, not a universal song-pair score).
- Provenance is **field-level** (`docs/design-memo-analyzer-provenance-contract.md`,
  substrate implemented). Each analysis dimension (tempo, beatgrid, key,
  sections, stems, role — `PROVENANCE_DIMENSIONS`) carries a
  `ProvenanceRecord {tier, method, confidence, note}` where `tier` is a
  `ProvenanceTier` (`STUB`/`UNAVAILABLE`/`USER_ASSERTED`/`MEASURED`).
  `TrackAnalysis.field_provenance` holds explicit records;
  `TrackAnalysis.provenance_of(dim)` falls back to the whole-analysis
  `AnalysisProvenance` **base tier** (`STUB`/`MEASURED`, default `STUB`) for
  any dimension without one, and `derived_provenance()` is the min-tier
  rollup. `confidence` is the estimator's self-consistency, held **separate**
  from `tier` and never promoting it (librosa: 123 BPM @ 0.92 on pink noise).
  `analyze_track` still emits `STUB` on every dimension — production cannot
  mark `MEASURED`; the substrate is the seam a real analyzer flips one
  dimension at a time. Eight anti-laundering guard tests live in
  `tests/test_provenance_contract.py`.
- `src/mashpad/analysis/tempo_backend.py` — a pluggable tempo-estimation
  *interface*, **not a BPM detector**. A `TempoBackend` Protocol
  (`estimate_candidates(path) -> tuple[TempoCandidate, ...]`) plus a
  name-keyed registry, so a backend can `register_backend(...)` and become
  selectable by name with no caller change. Two stdlib-only backends ship
  (`wave`/`struct`/`math`, 16-bit PCM WAV only, MP3 unsupported), both
  honest *estimates* expected to fail on weak/syncopated pulses:
  `autocorrelation` (the original toy: RMS-envelope autocorrelation,
  preserved as a baseline) and `energy_flux` (default: onset-strength
  envelope + perceptually-weighted, lag-smoothed autocorrelation +
  parabolic interpolation — better, still an estimate). A third backend,
  `librosa`, is the **first optional external** tempo backend: it wraps
  `librosa.beat.beat_track` and is gated behind the `tempo-librosa` extra
  (**never a core dependency**; `dependencies = []` stays empty). librosa
  is imported *lazily*, so importing this module never needs it; the
  backend is registered unconditionally, and requesting it without the
  extra raises a clear `ImportError` naming `tempo-librosa` rather than an
  "unknown backend". It is the first *practical* external candidate, still
  **not** a blessed production detector, and is tempo-candidate extraction
  only (no chroma/key/section/beat-grid). aubio was evaluated first and
  rejected — its only PyPI release (0.4.9, 2019) is source-only and fails
  to build against numpy 2.x on Python 3.13 / Apple Silicon (see
  decision-log). No backend is wired into `analyze_track`/`mashcheck` —
  all are reachable only via `scripts/eval_tempo.py` (`--backend` selects
  one) against a user-supplied local audio index
  (`tests/fixtures/audio_index.example.json` shape).
  `src/mashpad/analysis/wav_tempo_probe.py` is now a thin deprecated shim
  forwarding to the `autocorrelation` backend.
- `src/mashpad/tempo_eval.py` — the local-only tempo-evaluation corpus
  workflow behind `scripts/eval_tempo.py` (now a thin CLI shim over it).
  Loads a private fixture index (id / path / expected_bpm / accepted_bpms
  / tolerance_percent / category / expected_relation / source_kind /
  do_not_commit / notes), runs one backend per invocation, classifies
  each result as direct / half_time / double_time / other (**half- and
  double-time are valid interpretations, not failures**, unless a fixture
  pins `expected_relation`), reports percent error and per-fixture
  warnings, flags "suspicious" high-confidence failures (heuristic
  threshold — backend confidence is never a calibrated probability), and
  summarizes pass rate + failures grouped by category. Missing local
  files are *skipped*, never failed, so an index works across machines.
  `--json` writes machine-readable results for cross-backend comparison.
  Operational guide: `docs/tempo-eval.md`. Tested in
  `tests/test_tempo_eval.py` with fake in-memory backends and
  synthesized-in-test WAVs only — no committed audio, no real paths.
- `src/mashpad/overrides.py` — applies a `ManualOverride` (BPM
  multiplier, key replacement, phrase-boundary shift) to a
  `TrackAnalysis`. An override marks the touched dimension's provenance
  `USER_ASSERTED` (method `manual_override`), **never** `MEASURED`, and
  leaves the whole-analysis enum untouched: a human assertion is trusted as
  the value but caps the verdict at MAYBE with attribution, so the tool
  cannot echo a user's own BPM/key claim back as its confident measurement.
  Downbeat/stem-gain overrides are modeled but not yet applicable (no
  beat-grid/stem data) — raises `NotImplementedError` rather than silently
  no-op.
- `src/mashpad/io/audio_file.py` — file validation only, no decoding yet.
- `src/mashpad/report/` — text report rendering; states the assumed move
  type and role assignment explicitly, and splits the output into two
  zones that must not be conflated: **Musical judgment** (the
  `CompatibilityVerdict` + cited evidence — the answer) and **Analysis
  evidence (backend components — not the verdict)** (the raw
  tempo/harmonic/phrase fits and the composite, shown subordinate). Per-track
  values are tagged `[stub estimate …]` vs `[measured]`.
- `src/mashpad/cli.py` — `mashcheck` entry point. `build_report()` is
  pure (no file I/O) so tests can drive it with fixture `TrackAnalysis`
  objects; it runs `evaluate_move()` then `assess_compatibility()` and
  renders both; `run()`/`main()` wire it to real files.

## Guardrails

- Do not commit audio files, even short clips. See `fixtures/README.md`.
- Do not add real DSP dependencies (aubio, demucs, spleeter, essentia,
  madmom, BeatNet, etc.) without discussing it first — the stubs are
  intentional for this stage. `librosa` is the one sanctioned exception,
  and only as an **optional** extra (`tempo-librosa`) feeding the
  `librosa` tempo backend; it must stay out of `dependencies` (core stays
  `[]`), lazily imported, and out of `analyze_track`/`mashcheck`. Do not
  expand librosa use beyond tempo-candidate extraction (no chroma, key,
  onset/section, or beat-grid work) without discussing it first.
- Do not make licensing claims about audio sources.
- Keep stub seams explicit (`TODO(real analysis)` + deterministic
  placeholder) rather than faking a "complete" implementation.
- Tests must stay deterministic — no *committed* real audio in the test
  suite; use JSON fixtures (`tests/fixtures/*.json`), the seeded stubs, or
  (as in `tests/test_wav_tempo_probe.py`) synthetic audio generated on the fly
  inside the test itself.
- Don't score out-of-scope move types as if supported (`scores=None`,
  not a fabricated number) and don't claim a dimension is measured
  (`CollisionProfile.measured`, `arrangement_contrast_score`) when
  nothing actually estimated it.
- Composite score weights are configurable defaults
  (`CompatibilityWeights`), not tuned/validated truth — see
  `docs/eval-plan.md`.

See `docs/decision-log.md` for why things are built this way, and
`docs/mashup-move-taxonomy.md` / `docs/eval-plan.md` for the move-type
and evaluation-corpus design. `docs/compatibility-verdict.md` explains the
evidence-first verdict; `docs/fixture-planning-matrix.md` maps each move
type to its required/available/missing evidence, expected v0 verdict,
false-positive risks, and fixture cases (what v0 may judge vs. must return
`UNCERTAIN`) — locked by `tests/test_move_abstention.py`.
