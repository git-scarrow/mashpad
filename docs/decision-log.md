# Decision log

Short, dated entries. Add to this rather than rewriting history.

## 2026-07-07 — Initial scaffold

**uv + pyproject.toml, hatchling backend.** Matches the toolchain already
in use on this machine; no reason to introduce poetry/pip-tools for a
fresh project.

**stdlib `dataclasses` + `enum`, not Pydantic.** Zero runtime
dependencies for a stub-heavy first pass. Revisit if/when we need
validation beyond what tests already cover (e.g. an actual JSON schema
for fixture files, or a persisted project file format).

**stdlib `argparse`, not `click`.** One subcommand (`mashcheck a b`)
doesn't need a CLI framework. Revisit if the CLI grows subcommands
(`mashpad analyze`, `mashpad export`, etc.).

**Deterministic stubs keyed on file name, not file content.**
`mashpad.io.audio_file.stable_seed()` hashes the file's name and feeds
that into `analysis/tempo.py`, `analysis/harmony.py`, and
`analysis/sections.py`. This means:
- The same file always produces the same placeholder analysis (needed
  for reproducible CLI tests without shipping real audio).
- We deliberately do *not* read file bytes in the stubs, so nothing here
  depends on file format/decoding — that's still `io/audio_file.py`'s
  `TODO(real analysis)`.
- This is throwaway once real detection lands; the seam is the stable
  part (`Track -> float`, `Track -> str`, `Track -> tuple[Section, ...]`),
  not the hash trick.

**Harmonic relation table built from circle-of-fifths distance, not a
literal Camelot-wheel lookup table.** Same underlying music theory
(same key, relative major/minor, perfect-fifth neighbor, parallel
major/minor, semitone clash), computed from pitch-class arithmetic
instead of copying an external numbering scheme. Keeps the "known-key
relation table" requirement satisfied without any licensing question
about Camelot's specific numbering.

**Component score weights (tempo 0.35 / harmonic 0.35 / phrase 0.30) are
a placeholder, not a tuned model.** They exist so candidate ranking has
*something* principled to combine, and so the "strong fit beats weak
fit" test has a stable thing to assert on. Expect these to move once
there's real analysis data (or a listening test) to tune against.

**`cli.build_report()` is split from `cli.run()`.** `build_report` takes
already-built `TrackAnalysis` objects and does no I/O — this is the seam
tests use to drive the full scoring+reporting pipeline from
`tests/fixtures/*.json` without touching the filesystem or the stub
analyzers. `run()`/`main()` are the thin, mostly-untested-by-design glue
that loads real files.

**Not built yet, on purpose:** real BPM/key/section detection, stem
separation (interface only, raises `NotImplementedError`), any waveform
or desktop UI, export/rendering, streaming-service import, cloud sync.

## 2026-07-08 — Asymmetric mashup-move compatibility harness

Converted the scoring model from "compare two tracks symmetrically" to
"evaluate one specific mashup move (move type + role assignment)."
Design input: the uploaded research report
(`docs/Mashup Compatibility Tool Taxonomy.md`) and
`docs/mashup-move-taxonomy.md`, which condenses it into an operational
v0/partial/out-of-scope table. No new MIR dependencies were added — this
was purely a data-model and scoring-architecture change.

**`score_compatibility()` was replaced by `evaluate_move()`.** Nothing
outside `mashpad.scoring` called the old function directly (verified by
grep before removing it), so this was a clean replacement rather than an
added parallel API. `evaluate_move()` takes a `MashupMoveType` and a
`TrackRole` for each track and returns a `CompatibilityProfile`.

**Compatibility is asymmetric via anchor selection, not a special case.**
The `vocal`-role track's BPM/key is always the anchor; the
`instrumental`-role track is the one adjustment text targets and the one
whose deviation gets normalized against. This follows the report's
finding that vocals tolerate far less stretch/pitch-shift than
instrumentals before audible artifacts. `tempo_score.py` and
`harmonic_score.py` gained an `adjustable_label` parameter (default
`"B"`, preserving old behavior/tests) rather than a rewrite, so the
existing well-tested distance math didn't change, only which BPM/key
value plays which role.

**Out-of-scope move types return `scores=None`, not a fabricated
number.** `MOVE_SUPPORT` in `models.py` is the single source of truth for
supported/partial/out_of_scope, kept in sync with the status table in
`docs/mashup-move-taxonomy.md` by comment convention (no automated check
yet — small enough to review by eye for now).

**`arrangement_contrast_score.py` and `collision_score.py` have no
stub estimator, unlike tempo/key/sections.** Both are real, tested, pure
math (mirroring the report's formulas) but require the caller to supply
complexity/overlap numbers explicitly. Inventing a plausible-looking
density or overlap number the way the tempo/key/section stubs do would
misrepresent something we have no signal for at all (no chroma analysis,
no stem separation) — omitting the dimension and renormalizing weights
(`composite_score.py`) is the honest default.

**Composite weights (tempo 0.30 / harmonic 0.30 / phrase 0.20 /
arrangement_contrast 0.20, collision penalty 0.4 vocal / 0.3 bass) are
sourced from the report's example but are explicitly not the report's
values used blindly** — the report's formula doesn't include a phrase
term at all, and its weights (0.30/0.50/0.20) don't sum to a covering set
once phrase fit is added. `CompatibilityWeights` in `composite_score.py`
is a plain configurable dataclass; see `docs/eval-plan.md` for why the
evaluation corpus uses different score bands than the report's example
harness.

**`ManualOverride`/`apply_override()` only implement the override kinds
that are pure data transforms on already-estimated values** (BPM
multiplier, key replacement, phrase-boundary shift). `DOWNBEAT` and
`STEM_GAIN` overrides are modeled (first-class in `ManualOverride`) but
`apply_override()` raises `NotImplementedError` for them — there's no
beat-grid representation or stem data yet to apply them to, and a silent
no-op would be worse than an explicit "not yet."

**`TrackAnalysis.tempo_candidates` is a model-level seam, not yet
consumed by scoring.** `tempo_score.py`'s half/double check already
handles octave ambiguity given two single BPM values; `tempo_candidates`
represents what a *single track's* analyzer believes about its own tempo
ambiguity, for future use by a manual-override UI. The stub
(`estimate_tempo_candidates`) is explicitly documented as illustrative,
not a real ambiguity signal.

**Not built yet, on purpose (still):** anything requiring real stem
separation (`CollisionProfile` measurement, `DOWNBEAT`/`STEM_GAIN`
override application), real harmonic-density estimation
(`arrangement_contrast_score` inputs), hook-length/transient-level
scoring granularity for `hook_collision`/`rhythmic_graft`, pitch-shift
synthesis for `harmonic_reinterpretation`, and anything requiring lyric
or semantic analysis.
