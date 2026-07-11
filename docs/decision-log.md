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

## 2026-07-08 (cont.) — Candidate-aware tempo scoring + first real-audio seam

`TrackAnalysis.tempo_candidates` moved from an unconsumed model-level seam
to something `evaluate_move()` actually scores against.

**`score_tempo_candidates()` searches every (candidate_a, candidate_b)
pair, not just each track's primary BPM.** Deviation is normalized
against `candidate_a.bpm`, mirroring `score_tempo_fit`'s `bpm_a`-anchor
convention, so the existing anchor-based asymmetry (vocal-role track
anchors tempo) still holds — only which candidate list plays "a" changes
with role assignment.

**`evaluate_move()` always calls the candidate-aware path.** When a track
has no `tempo_candidates` (the common case today — the CLI's stub
analyzer produces them, but hand-built/JSON-fixture `TrackAnalysis`
objects generally don't), it's not simply passed through as a single
value. The **anchor** side falls back to one synthesized candidate at its
nominal BPM (it was never multiplier-searched before either). The
**adjustable** side falls back to three synthesized candidates at
`TEMPO_MULTIPLIERS` (0.5x/1x/2x) of its nominal BPM — this exactly
reproduces `score_tempo_fit`'s old half/double-time search, so tracks
without real candidate data don't silently lose octave-ambiguity
matching. Either fallback sets `CompatibilityProfile.tempo_explanation`
with an explicit `[fallback: ...]` prefix so it's never confused with a
real multi-candidate resolution.

**`CompatibilityProfile` gained `tempo_relation`/`tempo_explanation`.**
`tempo_relation` is one of `direct`/`a_half_time`/`a_double_time`/
`b_half_time`/`b_double_time`/`unresolved`; `tempo_explanation` is the
human-readable string the text report now prints as a "Tempo
interpretation:" line, so a report never just asserts a tempo score
without saying which BPM interpretation produced it.

**First real-waveform code: `mashpad.analysis.wav_tempo_probe`,
stdlib-only.** (Named `real_tempo.py` in an earlier draft of this pass;
renamed before commit — see the cleanup note below.) Per the "no MIR
dependency without discussing it first" guardrail, this implements a
crude frame-RMS-envelope autocorrelation BPM *probe* using only `wave` +
`struct` (no numpy/librosa/aubio) — good enough to exercise
`TempoCandidate` plumbing against a real local WAV file, explicitly not a
claim of trustworthy BPM detection. Explicitly **not** wired into
`analyze_track`/`mashcheck` — it's reachable only via
`scripts/eval_tempo.py`, a manual, local-only harness that reads
`tests/fixtures/audio_index.example.json`-shaped indexes of
user-supplied local audio (paths never committed, per
`fixtures/README.md`). MP3 decoding is out of scope (no stdlib decoder);
the script requires 16-bit PCM WAV. `tests/test_wav_tempo_probe.py`
verifies the probe against a synthesized-in-test click track (generated
code, not committed audio), not against `scripts/eval_tempo.py` itself.

**Explicit non-validation warning added for `hook_collision`,
`rhythmic_graft`, `genre_contrast_blend`** in
`docs/mashup-move-taxonomy.md` — their `PARTIAL` composite score is a
generic tempo/harmonic/phrase compatibility number, not a judgment on the
move-specific criteria (hook timing, groove/transient fit, contrast
quality) at all.

**Not built yet, on purpose (still, additionally):** real MP3 decoding
for `wav_tempo_probe.py` (WAV-only for now), any evaluator that consumes
real audio inside the automated pytest suite (deliberately kept out —
tests stay deterministic per the project guardrail), swing/groove-ratio
analysis, hook-length windowed scoring.

## 2026-07-08 (cont.) — Pre-commit cleanup pass

Renamed `mashpad.analysis.real_tempo` to `mashpad.analysis.wav_tempo_probe`
(and its test file to `tests/test_wav_tempo_probe.py`) before this work
was ever committed. `real_tempo` read as "the real tempo detector" next
to the filename-seeded stub in `analysis/tempo.py`, which overstated what
a toy single-file autocorrelation estimate actually is. `wav_tempo_probe`
names both constraints at once: WAV-only input, and a probe for the
candidate/fallback/relation harness, not a BPM detector. Docstrings and
error messages were reworded to match (no behavior change).

Verified (see `score_tempo_candidates`'s docstring and
`tests/test_tempo_candidates.py`) that the candidate-matching contract is
exactly: search every candidate pair, select the pair with the lowest
tempo deviation (ties broken toward higher combined confidence), report
`selected_bpm_a`/`selected_bpm_b` for the winning pair, expose
`required_stretch_ratio`, and label the match `direct` unless one side's
winning candidate is a half/double-time interpretation of its own
primary. Confirmed unrelated-tempo pairs stay `WEAK` even when both
sides carry a full half/direct/double candidate set (no candidate
combination closes the gap) — see
`test_no_valid_candidate_interpretation_stays_weak` and the new
`test_wide_tempo_gap_is_not_rescued_by_any_candidate_combination`.

**Fallback candidates are asymmetric by design, not generated identically
for both tracks.** The anchor side (the vocal-role track, or Track A by
default) gets exactly one synthesized candidate at its nominal BPM — it
was never multiplier-searched even before candidates existed, so a
missing-candidate anchor doesn't change behavior. The adjustable side
gets three synthesized candidates at `TEMPO_MULTIPLIERS` (0.5x/1x/2x) of
its nominal BPM, reproducing the pre-candidate `score_tempo_fit` search
space exactly. `CompatibilityProfile.tempo_relation` is the "best pulse
relation" (which candidate combination matched, e.g. `b_double_time`);
`tempo_explanation` embeds that plus the `[fallback: ...]` marker when
synthesized data was used. The **recommended stretch target** is a
separate concept, carried in `adjustments` (e.g. "Stretch B to 140.0
BPM") — `TempoMatch.required_stretch_ratio` is the numeric form of that
same recommendation, not a restatement of `relation`.

## 2026-07-08 (cont.) — Tempo backend *interface*, not a real detector

Replaced the single toy `wav_tempo_probe` function with a pluggable
`mashpad.analysis.tempo_backend` — a `TempoBackend` Protocol
(`estimate_candidates(path) -> tuple[TempoCandidate, ...]`) plus a
name-keyed registry. This is the "real backend" the goal asked for read
honestly: **a real interface, not real detection.** No MIR dependency was
added (the CLAUDE.md guardrail stands); the guardrail was explicitly
re-confirmed with the user before this pass, who chose "no new dep — real
interface only" over adding aubio/librosa.

**Why an interface and not a better algorithm renamed "real."** The
immediately-prior pass already learned this lesson: it drafted a
`real_tempo.py` (byte-identical RMS-autocorrelation algorithm) and then
renamed it to `wav_tempo_probe` precisely because calling a stdlib
autocorrelator "real" overstated it (see the 2026-07-08 "Pre-commit
cleanup" entry). Re-introducing a `real_tempo.py` would have walked
straight back into that. Instead, the honest "real" thing is the seam: a
future aubio/librosa/BeatNet backend registers with
`register_backend(...)` and becomes selectable by name from
`scripts/eval_tempo.py` (`--backend`) with **zero** change to any caller.
`analyze_track`/`mashcheck` remain on the filename-seeded stub, untouched.

**Two stdlib backends ship.** `autocorrelation` is the original toy,
preserved verbatim as a baseline (its behavior and
`tests/test_wav_tempo_probe.py` don't move — `wav_tempo_probe` is now a
thin shim forwarding to it). `energy_flux` (the default) is a genuinely
better *estimate*, still stdlib-only and still labeled an estimate, not a
detector: a half-wave-rectified log-energy onset-strength envelope
(transients over sustained loudness), autocorrelated with a log-Gaussian
perceptual tempo prior (~120 BPM, Ellis 2007) to bias primary selection
away from octave errors, triangular lag-smoothing before peak-picking,
and parabolic interpolation for sub-frame BPM.

**The triangular smoothing earns its place — it fixes a real octave
error.** A beat period that isn't an integer number of frames (e.g. 132
BPM ≈ 22.7 frames at 20 ms) splits its autocorrelation between adjacent
integer lags, halving each, while the 2x-period lag stays integer-
consistent and spuriously wins — so an unsmoothed `energy_flux` reported
132 BPM tracks as ~66 (half-time) *as the primary*. Smoothing recombines
the split fundamental; `test_energy_flux_primary_is_the_fundamental_not_
half_time` guards it. Octave error is still an expected failure mode on
real syncopated audio (that's what the half/double `TempoCandidate`
companions are for) — smoothing only removes the *synthetic* frame-grid
version of it.

**Honest naming, again.** The improved backend is `energy_flux`, not
"spectral_flux": it operates on the time-domain energy envelope, not a
frequency-domain spectral flux (there's no stdlib FFT and none was
added). Naming it "spectral" would have repeated the `real_tempo`
overstatement in a new spot.

**Not built yet, on purpose (still, additionally):** any backend that
consumes a real spectrogram/FFT (no stdlib FFT, no numpy), any MIR
dependency (the registry is the drop-in point when that conversation
happens), MP3 decoding (WAV-only), and wiring any backend into
`analyze_track`/`mashcheck` (still stub-only by design).

## 2026-07-08 (cont.) — First optional external tempo backend: librosa (aubio rejected)

Filled in the "MIR drop-in point" the registry was built for, with an
explicit dependency decision made per-library rather than lifting the
guardrail wholesale.

**aubio evaluated first, rejected as a platform blocker — not forced.**
Its only PyPI release is 0.4.9 (2019), source-only (no wheels for any
platform), and its `python/ext/ufuncs.c` uses the pre-2.0 numpy C API
(`PyUFuncGenericFunction` signatures), so it fails to compile against
numpy 2.x under Python 3.13 on Apple Silicon (clang
`-Wincompatible-function-pointer-types`, exit 1). It also needs the aubio
C lib + `libavresample` via pkg-config, absent here. `uv pip install
--only-binary :all: aubio` confirms "no usable wheels." Forcing it would
mean system libs + compiler-flag hacks for an unmaintained build — out of
scope for a local-first prototype. No aubio code or dependency was added;
the interface was left unchanged during that evaluation.

**librosa adopted instead, as an optional extra only.** `librosa>=0.11`
resolves entirely from prebuilt wheels for py3.13/arm64 (29 deps incl.
numba/llvmlite/scipy — no source build) and `librosa.beat.beat_track`
works. It is added as `[project.optional-dependencies] tempo-librosa`,
**never** a core dependency: `dependencies` stays `[]`, so `uv sync` /
`uv run pytest` / `mashcheck` install nothing new and stay
stdlib-deterministic. Opt in with `uv sync --extra tempo-librosa`.

**`LibrosaTempoBackend` is registered unconditionally but imports librosa
lazily.** Registering it always (rather than only when the extra is
present) means `--backend librosa` is a *known* name whose failure mode,
when the extra is missing, is a clear `ImportError` naming
`tempo-librosa` — not a confusing "unknown backend". The lazy import keeps
`import mashpad.analysis.tempo_backend` (and the whole stub pipeline) free
of any librosa requirement, so the stdlib backends are unaffected by its
absence. Tests skipif-branch on `importlib.util.find_spec("librosa")` so
both the missing-dependency error and the installed output-shape path are
covered depending on the env (`uv run pytest` vs
`uv run --extra tempo-librosa pytest`).

**Scope held to tempo-candidate extraction.** The backend calls
`beat_track` for the primary BPM and derives an honest confidence from
`librosa.feature.tempo` frame agreement (fraction of per-frame tempo
estimates within 4% of a candidate) — explicitly not a calibrated
probability. Candidate shape matches every other backend (primary at
`multiplier_from_primary=1.0` plus 0.5x/2x companions). No chroma, key,
onset/section, or beat-grid use — those remain out of scope and stubbed.
librosa is documented as the *first practical external candidate*, not a
blessed production detector.

**Not built yet, on purpose (still, additionally):** wiring `librosa`
(or any backend) into `analyze_track`/`mashcheck` (still stub-only),
aubio/BeatNet/madmom/essentia backends, and any librosa use beyond tempo
(chroma/key/section/beat-grid).

## 2026-07-08 (cont.) — Tempo evaluation corpus workflow (backends become comparable)

**Problem: three backends, no way to learn which one is useful.**
`scripts/eval_tempo.py` was a pass/fail spot check with a fixed ±2 BPM
tolerance and no notion of *which* tempo interpretation matched. Per the
"stop adding backends before we can compare them" principle, this pass
built the first serious evaluation loop instead of a fourth backend.

**Core moved to `mashpad.tempo_eval`; the script is a shim.** The eval
logic is now an importable, unit-tested module
(`tests/test_tempo_eval.py`, fake in-memory backends + synthesized-in-test
WAVs, zero committed audio). `scripts/eval_tempo.py` just calls its
`main()`. This keeps the harness honest the same way `cli.build_report()`
is kept pure for tests.

**Fixture schema grew to express real mashup tempo risk.** An index entry
now carries `accepted_bpms`, `tolerance_percent` (percent of target, not
absolute BPM — 2 BPM at 60 is not 2 BPM at 180), `category` (recommended
set: steady_quantized_pop, half_time_ambiguous, double_time_ambiguous,
sparse_intro, drumless_or_soft_onset, tempo_drift_live,
syncopated_or_swing, known_bad_or_unusable), `expected_relation`
(`any`/`direct`/`half_time`/`double_time`), `source_kind` (licensing
bookkeeping), and `do_not_commit`. Unknown keys are rejected loudly (a
hand-maintained index deserves typo detection). When `accepted_bpms` is
omitted, **all three octave interpretations of `expected_bpm` are accepted
by default** — the evaluator encodes the Mashpad stance that half-/double-
time are valid pulse readings, not detector mistakes; a fixture that truly
needs direct time pins `expected_relation: "direct"`.

**Relation classification is explicit output, not an internal detail.**
Every pass says whether it matched direct / half_time / double_time (or
"other" for an explicitly accepted unrelated BPM) and its percent error,
because "found a usable pulse, at half-time" is exactly the answer
`score_tempo_candidates` needs — a single BPM verdict is the failure mode
this repo exists to avoid. The primary candidate is selected when it
matches; a pass via a companion candidate is a pass *with a warning*, so a
backend that leans on its octave companions is visible.

**Failure honesty over run convenience.** Missing local files are
*skipped* (an index shared across machines degrades gracefully), backend
`ValueError`s are per-fixture *errors*, and a missing librosa extra aborts
the whole run with the real cause (exit 2) instead of failing every row.
Failed fixtures whose primary confidence ≥ 0.75 are flagged
**suspicious** — confidently-wrong is the most dangerous outcome for a
mashup tool, and backend confidence is estimator self-consistency, never a
calibrated probability (the report says so on every run). `--json` writes
a versioned record (`mashpad-tempo-eval-results/v1`) per run so backends
can be compared later without a database.

**Not built yet, on purpose (still, additionally):** any new backend
family, cross-run diffing/tooling beyond the JSON records, wiring any
backend into `analyze_track`/`mashcheck`, and everything already excluded
(key/chroma/section/stems/UI). Operational guide: `docs/tempo-eval.md`.

## 2026-07-08 (cont.) — First backend recommendation from the private corpus

Ran the evaluation loop above against the first private local tempo
corpus (July 2026) and recorded a recommendation. **Decision: prefer
`librosa` for real-audio tempo evaluation, keep `energy_flux` as the
stdlib zero-dependency fallback, and treat `autocorrelation` as a
historical/diagnostic baseline only.** Documented in
`docs/tempo-eval.md` ("Current backend recommendation").

**Pass rate tied; failure quality decided it.** All three backends scored
the same raw pass rate on the corpus, so pass rate did not distinguish
them. `librosa` was the only backend to pass the real
steady-quantized-pop case, handled half-/double-time as usable
interpretations rather than mistakes, refused to invent a tempo for
low-evidence (transient-free) input, and reported low confidence on
no-pulse noise. `autocorrelation` produced misleadingly *high* confidence
on wrong and no-pulse cases — the "confidently wrong" failure mode the
`suspicious` flag exists to catch, and the most dangerous outcome for a
mashup tool. That behavior, not a lower score, is why it drops to
baseline-only.

**Deliberately *not* a production-validation claim, and no code changed.**
This pass was evidence-gathering plus documentation only: no new backend,
no scoring change, and `librosa` stays out of the default
`mashcheck`/`analyze_track` path (still stub-only, reachable only via the
manual eval loop). The evidence is deliberately limited and should be
treated as provisional: 8 fixtures, 2 real songs, and
`sparse_intro`/`double_time_ambiguous`/`tempo_drift_live` categories still
absent. Private corpus files (audio, the local
`audio_index.json`, and `results_*.json`) remain gitignored and
uncommitted per `fixtures/README.md`.

**Next validation step:** expand the private corpus (more real songs, the
missing categories) before wiring real tempo candidates into non-stub
track analysis.

## 2026-07-08 (cont.) — Evidence-first compatibility verdict (a calibration layer)

Added a `CompatibilityVerdict` (COMPATIBLE / MAYBE / UNLIKELY / UNCERTAIN)
and `mashpad.scoring.verdict.assess_compatibility`, layered over
`CompatibilityProfile`. **This is explicitly a calibration/evidence harness,
not a scoring improvement:** `evaluate_move` and every component score are
byte-identical (verified by the unchanged score-oriented tests). The verdict
layer only *reinterprets* those numbers through an honesty lens and adds the
abstention gates the raw scorer never had. Full rationale in
`docs/compatibility-verdict.md`.

**The core move: an asymmetric confidence bar that withholds flattering
scores.** It is easier to rule a mashup *out* (a necessary condition like
beat-matchability fails) than to rule one *in* (needs sufficient conditions
we can't verify from placeholders). So confident verdicts (COMPATIBLE /
UNLIKELY) require `AnalysisProvenance.MEASURED`; v0's filename-seeded stubs
cannot reach them. The success condition — "more willing to say UNCERTAIN
where the old version emitted a flattering but unsupported score" — is
demonstrated in the golden CLI test itself: the same fixtures that still
compute `composite 0.8177 (strong)` now return a **MAYBE** verdict whose
caveats name the stub provenance, the tentative sections, and the unverified
role split.

**New `AnalysisProvenance` field on `TrackAnalysis` (default `STUB`).** This
is the honest seam a real analyzer flips, not a knob: `analyze_track` sets
`STUB` explicitly, and the verdict layer reads it to decide whether any
deciding evidence is real. Optional + defaulted, so JSON fixtures and
round-trips are unaffected (`test_models` still passes).

**Five abstention gates → UNCERTAIN**, each covered by a fixture test in
`tests/test_verdict.py`: unsupported move type, missing role premise,
ambiguous BPM, multiple plausible tempo ratios, and a low-confidence tempo
override being required. Tempo ambiguity is read from a track's *real*
`tempo_candidates` only (never the all-1.0-confidence synthesized fallback),
and a dominant-primary set like the stub's 0.6/0.25/0.15 is deliberately
*not* flagged, so the default CLI path stays MAYBE rather than collapsing to
a useless always-UNCERTAIN.

**Report restructured to separate musical judgment from backend evidence.**
The verdict + its cited evidence lead; the tempo/harmonic/phrase fits and the
composite are demoted to an "Analysis evidence (backend components — not the
verdict)" block, and per-track values are tagged `[stub estimate …]` vs
`[measured]`. The old `EXPECTED_REPORT` golden string was updated to match.

**Not built (still, and on purpose):** any real analysis backend that would
set `MEASURED` (the field exists, the measurement doesn't — no stems, key,
section, or beat-grid detection was added), and no move-specific criteria for
the PARTIAL moves (those remain capped at MAYBE). No weights were tuned.

## 2026-07-09 — Fixture-planning matrix (docs artifact, no behavior change)

Converted the mashup-move research (`docs/Mashup Compatibility Tool
Taxonomy.md` + `docs/mashup-move-taxonomy.md`) into
`docs/fixture-planning-matrix.md`: for each of the eight move types, its
required evidence, what v0 actually has, the gap, the expected v0 verdict,
false-positive risks, and the fixture cases needed. The point was to decide
**what v0 may responsibly judge, what must return `UNCERTAIN`, and which
analyzers are the precondition for confidence** — not to add capability. No
analyzers, weights, stems, key/section detection, or backend changes.

**Two facts the matrix makes explicit.** (1) Because `analyze_track` only
ever emits `STUB` provenance, *no* move type can reach a confident verdict
in v0 — supported/partial cap at `MAYBE`, out-of-scope abstain to
`UNCERTAIN`; the `COMPATIBLE` cells in the matrix are gated future behavior
that a real `MEASURED` analyzer would unlock. (2) A recorded modeling gap:
`genre_contrast_blend` implies a vocal/backing split but is not in
`verdict.ROLE_DEPENDENT_MOVES`, so it does not abstain on a `FULL_MIX`
pairing the way an overlay does. This was **documented, not changed** —
altering the role-gated set is a future verdict-behavior decision.

**Tests added encode current abstention only** (`tests/test_move_abstention.py`,
parametrized from `MOVE_SUPPORT`/`ROLE_DEPENDENT_MOVES`): out-of-scope →
`UNCERTAIN` with `scores=None`; role-gated + `FULL_MIX` → `UNCERTAIN` even
when measured; partial + measured → `MAYBE` (never `COMPATIBLE`); and every
move on `STUB` provenance is non-confident. No composite band is asserted;
nothing is tuned.

## 2026-07-09 (cont.) — Resolve the genre_contrast_blend role-gating gap (Option A)

Implemented the decision from
`docs/design-memo-genre-contrast-role-gating.md`: added
`GENRE_CONTRAST_BLEND` to `verdict.ROLE_DEPENDENT_MOVES`. Its taxonomy
definition is a lead (vocal/melodic) stem over a contrasting bed — the same
lead/bed premise as `vocal_over_instrumental_overlay` — so it now abstains
(`UNCERTAIN`, missing role) on a `FULL_MIX`/`FULL_MIX` pairing instead of
reading as `MAYBE` as though the split were established. The sole difference
from an overlay (aesthetic contrast) is a Category-3 judgment v0 does not
model, so it does not justify a different role premise.

**Narrow by construction.** One frozenset member + doc/test updates. No new
`TrackRole`, analyzer, scoring weight, stem/contrast/key/section logic, or
backend change — the role gate lives only in `assess_compatibility`, so
`evaluate_move`/composite are byte-identical and the eval corpus is
unaffected. Rejected Option B (splitting into lead/bed vs. full-mix moves)
as premature taxonomy sprawl with no measurable v0 payoff.

**Behavior delta:** genre-contrast + `FULL_MIX` flips `MAYBE → UNCERTAIN`
(visible even on stub, since the role gate precedes the provenance gate); a
proper vocal/instrumental split still proceeds to `MAYBE` and — because v0 is
stub-only — still cannot reach `COMPATIBLE`. Locked by
`tests/test_move_abstention.py::test_genre_contrast_blend_is_role_gated` (plus
the existing derived-list parametrized tests, which now cover it
automatically).

## 2026-07-09 (cont.) — Implement the field-level provenance substrate

Turned `docs/design-memo-analyzer-provenance-contract.md` from memo into
code, substrate only — **no analyzer wired, no scoring weight touched, no
backend added, and production still emits only `STUB`.**

**What landed.** `ProvenanceTier` (`STUB`/`UNAVAILABLE`/`USER_ASSERTED`/
`MEASURED`) and `ProvenanceRecord {tier, method, confidence, note}` in
`mashpad.models`; `TrackAnalysis.field_provenance` (dict keyed by the six
`PROVENANCE_DIMENSIONS`: tempo, beatgrid, key, sections, stems, role) with
`provenance_of()` (explicit record else base-tier fallback) and
`derived_provenance()` (min-tier rollup to the coarse enum). The old
`AnalysisProvenance` enum stays as the **base tier / display view**, so every
existing `provenance=MEASURED` fixture and the CLI golden are byte-identical.

**Confidence gate is now per-dimension.** `assess_compatibility` reads
`CONFIDENCE_DECIDING_DIMENSIONS` (overlay → tempo/key/sections/beatgrid/stems;
transition_blend → tempo/sections) and requires every deciding dimension
`MEASURED` on *both* tracks for `COMPATIBLE`; ruling *out* (`UNLIKELY`) needs
only tempo measured — the memo's easier-to-rule-out asymmetry. Partial moves
have no row and stay capped at `MAYBE` (empty deciding set is treated as
"cannot be confident," never vacuously satisfied). `beatgrid` and `stems` are
separate deciding dimensions, so a measured global tempo alone cannot license
an overlay `COMPATIBLE` (blocks the beatgrid-overclaim and role-without-stems
laundering paths).

**Overrides now assert, not measure.** `apply_override` sets the touched
dimension to `USER_ASSERTED` (method `manual_override`), never `MEASURED`, and
never touches the whole-analysis enum. A user-asserted deciding dimension caps
the verdict at `MAYBE` with explicit attribution, so the tool cannot echo a
user's own BPM/key claim back as its confident measurement.

**Guards.** `tests/test_provenance_contract.py` encodes all eight
anti-laundering tests from Decision 4 (confidence≠provenance, no-decoded-audio,
failed-measurement, no-partial-promotion, override-no-launder, beatgrid-
independent, roles-need-stems, stub-floor umbrella) plus serialization and
dimension-key validation. Full suite: 180 passed, 1 skipped; ruff + format
clean. The load-bearing success criterion — a fixture may mark only tempo
`MEASURED` without laundering key/sections/beatgrid/stems/role — is locked by
`test_only_tempo_measured_does_not_launder_other_dimensions`.

## 2026-07-09 — Skyfall/In the End construction spike (research layer)

A parallel research spike around one piece of trusted artistic ground
truth: "Skyfall" as retained foundation, "In the End" entering as an
added vocal at a Skyfall chorus, with the stressed "hard" ("I tried so
hard") intended to land on (or within ~1 beat of) the sung "fall". The
construction's viability is treated as known; every alignment parameter
is treated as unresolved. Full analysis:
`docs/design-memo-skyfall-construction-case.md`.

**New `mashpad.research` package, strictly parallel.** Nothing in
`analysis`/`scoring`/`report`/`cli` imports it; no weights, thresholds,
provenance semantics, or qualification gates changed. It holds
`MashupConstruction` — a ground-truth record for a *directed,
section-anchored, event-aligned arrangement* (host/guest asymmetry as a
structural axis distinct from `TrackRole`, anchor events, convergences
with bounded offset/tolerance hypotheses) — and `alignment_basin`, a
title-blind point-process scorer over annotated event times.

**Every empirical field carries an explicit resolution state**
(`measured`/`annotated`/`hypothesis`/`unresolved`) with anti-laundering
guards mirroring the provenance contract: `MEASURED` refuses laundering
methods, event times refuse `MEASURED` entirely (no sanctioned seam for
them exists yet), and human annotation is `ANNOTATED` — the research
twin of `USER_ASSERTED`, so it can never feed a confident verdict.
The committed fixture (`tests/fixtures/construction_skyfall_in_the_end.json`)
is identity + bounded hypotheses only; real event times go in a local,
uncommitted annotation file.

**The load-bearing negative result is now executable.**
`tests/test_construction_case.py` locks that production `evaluate_move`
is *structurally offset-blind*: shifting every guest section by any
offset yields a byte-identical `CompatibilityProfile` (phrase fit reads
only confidences, never times). v0 cannot represent, measure, or rank
*where* the guest enters — an input gap, not a tuning gap. The basin
tests lock the complementary positive shape: beat-grid events alone
leave the intended offset tied with whole-bar shifts (periodic ridge);
one aperiodic lyric-anchor pair breaks the tie. That anchor event is the
smallest feature production scoring is missing.

**No taxonomy change.** The case is overlay-shaped at macro scale,
hook-collision-shaped at the anchor, genre-contrast in aesthetic,
lyrical-juxtaposition in mechanism — evidence that move types are
time-scoped aspects, recorded as data in the fixture's
`taxonomy_gap_notes`. Revisit only when ≥2–3 constructions show the same
gaps. ML judged premature: the defensible ladder is alignment search →
calibration over a handful of constructions → within-pair
learning-to-rank, never a general compatibility regressor.

## 2026-07-09 — Construction case sharpened by a human-auditioned witness

The Skyfall/In the End construction now has real session evidence: the
user reproduced the mashup in djay Pro and found a stable arrangement —
host read at ~75 BPM (djay initially inferred the doubled tempo: a live
instance of the octave-ambiguity failure mode the verdict layer abstains
on), both decks synced at 74 BPM, guest slowed substantially, measure
offset host = guest + 22 (77↔55, 78↔56), effective from ~Skyfall chorus 2
through the bridge and final chorus, guest apparently +2 semitones
(explicitly to be verified from the session, not the screenshot).

**Witness, not target.** The 22-measure alignment is one successful
construction example — an existence proof — not the only valid overlay
and not an arrangement Mashpad must uniquely recover.
`MashupConstruction.claim_scope` is now schema-enforced to `"witness"`,
and success criteria are "score the witness region viable and its
degraded neighbors worse," never "rank this above every other overlay."

**Three-level hypothesis in the schema.** (1) Global conformance —
tempo interpretation + tempo/pitch transformation onto a shared grid;
(2) structural alignment — new `GridAlignment`/`AlignedWindow` types:
measure offset, internal-consistency-checked example correspondences,
offset-constancy as its own empirical question, windows with human
judgments; (3) local convergence events — the existing `Convergence`
records, reframed as candidate explanations for why the window works.

**Provenance of session evidence.** Human listening judgments are
`ANNOTATED` (the ground-truth kind this case exists for); values read
off djay's display/beat grids are `HYPOTHESIS` with methods naming the
source (`djay_session_observation`, `djay_beatgrid_readout`,
`djay_display_user_observed`) — user-observed, never authoritative,
never a path to `MEASURED`.

**New artifact: the construction timeline** (`mashpad.research.timeline`
+ `tests/fixtures/timeline_skyfall_in_the_end.json`): one row per
annotated host measure on the corrected grid (both songs' section
labels, derived guest measure, events, judgment) plus an
`OffsetAudition` ledger — witness offset +22 annotated, ±1-measure
neighbors explicitly unresolved, so "nearby offsets degrade the whole
passage" stays a recorded question, not an assumption.

The immediate empirical task inverts the earlier protocol order: correct
both beat grids first, then verify offset exactness/constancy, window
entry/exit measures, the +2 st question, where "hard"/"fall" land on the
corrected grid (is the lyric landing implied by the structural offset?),
other convergences across the window, and neighbor-offset degradation.
Production scoring, verdict thresholds, provenance semantics, and
qualification gates remain untouched.

## 2026-07-09 — Tempo corrections: octave error was the host's; viability is a region

Two corrections to the construction-case tempo evidence.

**Who erred.** djay correctly measured In the End at 105 BPM (now a
research-layer `measured` value, method `djay_tempo_analysis`, subject
to ordinary source re-verification — not an unbounded estimate). The
octave error was on Skyfall: djay read ~148, the user corrected the
metrical-octave doubling to ~74 (`annotated`,
`user_octave_correction_of_djay_reading`). The correction changed the
available transformation path: guest slowed 105→74 (~−29.5%) instead of
accelerated 105→~148 (~+41%). The broad 0.67–0.74 ratio hypothesis is
replaced by the witnessed point ratio 74/105 ≈ 0.705, explicitly marked
grid-choice dependent and non-definitional. Severity minimization is
recorded as a candidate-selection feature that helped find the
construction, not a universal rule.

**Region, not point.** 74 BPM is the witnessed working point, not the
unique/optimal common grid. New `GridAlignment.viable_grid_bpm_region`
(hypothesis, ~74–90 BPM) records a provisional human-auditioned
viability interval with an asymmetric constraint: the host sets the
main upper bound (Skyfall increasingly sounds rushed), the guest
tolerates deep slowing; acceptability is host-character preservation,
not minimal aggregate transformation (at 90 the aggregate change is
smaller but viability less certain). Transformation cost is therefore
role-asymmetric and cannot be judged by absolute percentage — a
modeling requirement recorded in the fixture's taxonomy_gap_notes,
alongside: octave-differing tempo estimates require comparing
octave-equivalent interpretations and their implied transformation
costs before rejecting a pairing.

**Next experiment pre-registered.** `timeline.TempoAudition` ledger +
`TEMPO_SWEEP_ASPECTS` (host naturalness, guest intelligibility, groove,
dramatic weight, overall effectiveness): a semi-blind sweep at the same
+22 structural offset — 74 annotated witness, 78/82/86/90 unresolved
candidates, 96 as a beyond-region probe to locate the failure boundary.
Goal: estimate a viability curve/interval, never fit one chosen BPM.
The case remains one witnessed construction *family*; sweep points that
work are family members, not independent examples. Production remains
untouched.

## 2026-07-09 — Downbeat anchor, aligned-but-muted, selective entrance

Third session refinement of the Skyfall/In the End construction.

**Primary anchor is downbeat-to-downbeat.** The songs align structurally
by placing each recording's first *metrically established* downbeat at
the same moment (djay displays ~"Skyfall bar 3 = In the End bar 1" —
session-specific labels, not ground truth: Skyfall's opening brass
gesture may be counted as a measure, pickup, or nothing by an analyzer).
New `GridAnchor` on `GridAlignment` references two downbeat
`AnchorEvent`s whose (unresolved) source timestamps are the ground
truth; measure-offset bookkeeping is now secondary and frame-dependent.
The earlier +22 readout contradicts the anchor frame's ~+2 on a single
grid — recorded as RECONCILIATION PENDING (same alignment in different
numbering frames, or two family members?), locked by
`test_offset_frames_await_reconciliation`, not silently resolved.

**Synchronized ≠ audible.** The guest's first ~7 bars clash with the
host (piano intro vs piano intro): meters align, active material does
not. The witnessed strategy keeps the host solo and brings the guest in
around its bar 8, where cadential motion converges (hypothesis recorded
as the `cadential_entrance` convergence). New `GuestAudibility`
(muted/entering/audible) on `AlignedWindow` and timeline entries makes
aligned-but-muted a first-class state. Four distinctions now structural:
temporal alignment ≠ harmonic compatibility; synchronized ≠ audible;
valid grid ≠ valid full-duration overlay; app bar numbering ≠ source
structure.

**Timeline expanded** per aligned measure: source-relative downbeat
timestamps (ground truth of the grid), app bar labels kept separately,
sections, guest audibility, harmonic judgment, texture conflict,
cadential events. Re-keyed to the anchor strategy (djay-label frame,
host = guest + 2, frame stated in transformation_note).

**Experiment split into two independent questions:** (A) can Mashpad
recover the metrically correct downbeat alignment despite the ambiguous
opening (a natural adversarial case for any future downbeat analyzer);
(B) given the grid, can it distinguish the clashing guest bars 1–7 from
the viable bar-8 entrance — production's one-global-key harmonic
evidence is window-blind by construction, the harmonic analogue of the
offset-blindness result. Construction search is layered: grid →
admissible audible windows → entrances/mutes/stems → local
convergences; production operates only at global pair level. Witness
framing preserved; production untouched.

## 2026-07-09 — +2 frame relation user-attested; annotation gap stated plainly

**Reconciliation resolved by the user, not by annotation.** The witnessed
djay-frame structural relation is +2 (djay Skyfall bar 3 = djay In the
End bar 1); the earlier "+22" observation was a later local
measure-number readout from a different numbering frame, not a rival
alignment. `grid.measure_offset` is now 2.0 / `annotated` /
`user_attested`; "reconciliation pending" and the stale different-frame
ledger entries are removed. Epistemic layering preserved: the musical
anchor stays downbeat-to-downbeat with (unresolved) source timestamps as
ground truth, djay labels stay session-specific, and +2 is the witnessed
relation in the djay frame, not a frame-independent constant.

**Annotation tooling honesty.** The memo previously said "annotate
locally" as if a workflow existed. It does not, and the memo now says so
plainly: nothing in the repo loads both audio files (load_track never
decodes; only the tempo backends decode, one file at a time, tempo-only),
nothing plays audio, nothing accepts downbeat/section/window/judgment
input, nothing persists annotations into the research fixtures (they are
hand-edited JSON; the "local annotation file" the docstrings reference
has no loader), and no command or UI exposes any of this. The smallest
missing executable path is identified but deliberately not built yet: a
label-import seam (parse an external label-editor export → local
annotations JSON keyed by event_id → flip matched construction event
times to ANNOTATED, never MEASURED → emit TimedEvents for the alignment
basin). External tools already cover audition (djay) and
click-to-timestamp (any label editor); the repo only needs the importer.

## 2026-07-10 — Label-import seam built

The annotation gap's smallest missing piece now exists:
`mashpad.research.annotations` + `scripts/import_labels.py` (thin shim,
eval_tempo convention). Parses Audacity-style label exports (stdlib
only), matches per side — label text naming a construction `event_id`
annotates that event (cross-side match and duplicate named-event labels
are loud errors), text naming an `EventKind` value becomes a grid event,
everything else reported unmatched — merges into a local, gitignored
`AnnotationSet` JSON under `fixtures/local/` (real timestamps: never
committed, audio_index.json policy, fixtures/README.md updated),
`apply_annotations` flips matched event times to `ANNOTATED` (never
`MEASURED`), and `basin_events` emits `TimedEvent`s for the alignment
basin. End-to-end test drives label files -> CLI -> annotation store ->
applied construction -> distinguishable basin with synthetic label text,
no audio committed. Deliberately still absent: audio loading for this purpose,
playback, any interactive UI — djay and a label editor remain the
interactive tools; the repo only imports their output. 222 tests pass;
production untouched.

## 2026-07-10 — Re-centered on automatic discovery; first discovery slice built

The spike's objective is restated: Mashpad receives two recordings and
independently proposes ranked construction hypotheses — no manual pins,
no external tools in the normal path. The label-import seam is demoted
to optional evaluation infrastructure (hidden truth / debugging), and
the witnessed Skyfall/In the End values are acceptance evidence only,
compared via `witness_agreement` against the committed fixture — never
constants in the discovery rules.

**New `mashpad.research.discovery`** (+ `scripts/propose_construction.py`
shim): pure hypothesis core over beat-granular `TrackFeatures` (every
decision rule unit-tested with synthetic features) + one thin librosa
extractor. Pipeline: decode both files; octave-aware metrical
interpretations (tracked + half-time from the sanctioned tempo backend's
candidates; double-time declared unsearched); shared-tempo candidates
ranked by role-asymmetric transformation cost (host stretch weighted 3x
guest — uncalibrated policy default; this is what lets the
octave-corrected host reading beat the doubled reading with no
hard-coded slower-is-better rule); pitch shift by mean-chroma rotation;
structural anchor = first stable downbeat per side (phase by
onset-strength share, stability by IBI settling — irregular openings
fall out mechanically); per-aligned-bar admissibility (chroma fit +
both-loud density) yielding ranked entry windows and a derived
aligned-but-muted window; both host/guest assignments searched. Every
hypothesis carries explicit evidence and uncertainty; nothing produces
or implies MEASURED provenance.

**librosa scope, explicitly.** This uses librosa beyond tempo candidates
(onset envelope, beat tracking, chroma, RMS) — authorized by the user's
re-centering directive, confined to `mashpad.research`, still lazily
imported behind the optional `tempo-librosa` extra, still absent from
core `dependencies`, `analyze_track`, and `mashcheck`. The production
guardrail is unchanged.

Verified: 12 new tests (pure core + one librosa-gated end-to-end on
in-test synthesized WAVs); CLI smoke run on synthetic 74/105 BPM pairs
picked the slow track as host, preserved it, slowed the guest ~28.6%,
aligned first stable downbeats, recovered the built-in transposition,
and produced a correct AGREES/DIFFERS witness report. 234 tests total;
production scoring/verdict/provenance/qualification untouched. Next:
the acceptance run against the two real local files.

## 2026-07-10 — Acceptance run: discovery recovers the witnessed construction

`propose_construction.py` was run against the real local recordings
(`fixtures/local/skyfall.wav` / `in_the_end.wav`). The top-ranked
hypothesis AGREED with the witnessed construction on every comparable
field: Skyfall as host at 76 BPM via the half-time reading of the
tracker's 143.6 (librosa made the same octave error djay made; the
role-asymmetric cost model made the same correction the user made),
In the End at 103.4 slowed −26.5% onto a host-preserving 76 BPM grid
(inside the witnessed 74–90 viable region), pitch +2 st (score 0.977),
and — from a generic sustained-run admissibility rule, not tuning —
guest muted through bar 7 with the entrance at guest bar 8 opening an
unbroken 77-bar window (mean chroma fit 0.862). No manual pins.

Caveats recorded in the memo: the winning half-time candidate carried
backend confidence 0.08 (the octave link is the most fragile step); the
role and pitch decisions are close leans, not separations; the host-side
anchor timestamp is unverified; n=1 — next falsification is the same
run on other pairs, including deliberately incompatible ones.

## 2026-07-10 — Registration search: the "+22" family member corroborated

User attested the original ~+22 relation is structurally compatible as
well — a distinct family member. Before this change discovery could not
propose it (one registration only: anchors coincident). Added
`search_alignments`: guest-delay offsets 0..48 host bars scored by
admissible coverage × mean window fit, top candidates proposed, and the
anchor-coincident registration ALWAYS proposed alongside (it is the
registration the anchors define). Witness report now surfaces the
best-agreeing proposal, not only #1.

On the real recordings the delayed region is the global fit maximum
(anchor-frame offsets 20–26 fit 0.88–0.90, peak 0.902 at 25) — the
machine corroborates the user's attestation and the basin's
periodic-ridge prediction at section scale. The anchor registration
(muted intro, bar-8 entrance) scores 0.772 (lowest by this metric) yet
ranks #4 and carries the full 5-AGREES witness match. Recorded insight,
not patched: the coverage metric penalizes intentionally muted bars —
arrangement-aware scoring should measure coverage over the audible plan.
Which family member is artistically preferable is a human judgment;
ledger updated with the user's +22 attestation (user_attested,
machine-corroborated, exact offset within the ridge pending host bar-1
frame verification). 3 new tests (237 total); production untouched.

## 2026-07-11 — Phrase-class constraint: loose-bar registrations excluded

User probe: discovery should NOT propose the +19/+20/+21 neighbors of
the valid +22 relation. It previously could not exclude them — the
chroma-coverage ridge is nearly flat because bar-level chroma is blind
to phrase grouping. Now registrations must differ from the anchor by
whole 4-bar phrases (offset ≡ 0 mod PHRASE_BARS; the anchors' first
stable downbeats are assumed to open phrases — a declared assumption,
with the witnessed family's own geometry as internal evidence: its two
attested members differ by exactly five phrases). Off-phrase offsets are
structurally wrong, not merely weaker, and are not searched. A
strength-based hypermetric estimate is computed as corroboration only;
on this pair it disagrees (residue 2) at near-chance confidence
(0.29/0.28 vs 0.25) and the disagreement is printed in every
hypothesis, not silently resolved. Real-recording proposals are now 36/
24/40 (+ anchor 0 with its 5-AGREES witness match); djay +19/20/21
(anchor 17/18/19) excluded by the general rule; the attested ~+22
(anchor 20, fit 0.882) is in-class, ranked 4th within the class.
Locked by test_off_phrase_registrations_are_not_proposed. 238 tests;
production untouched.

## 2026-07-11 — Phrase-class gate reverted; joint-overlay feature program

User redirect: the offset ≡ 0 (mod 4) search restriction was derived
from the current witness pair's attested members — an overfit
workaround, not analytical capability. Reverted as a gate: discovery
evaluates all offsets again (−1/−2/−3 neighbors included); phrase-class
membership and the hypermetric estimate stay as reported metadata only.
New objective: measure properties of the synchronized combination of
the two streams (never per-track scores combined afterward) that
distinguish successful registrations from unsuccessful nearby ones
across multiple pairs, leave-one-song-pair-out. No feature may be
derived solely from the witness pair; no weak correlation becomes a
gate; production scoring untouched until cross-pair generalization is
shown. Built: experiment design + registration-corpus schema
(docs/experiment-joint-registration-features.md,
tests/fixtures/registration_corpus_v1.json — labels carry resolution
states; near negatives on pair 1 are mostly unauditioned hypotheses)
and the minimal joint probe (research/joint_features.py: synchronized
cross-source frame pairs → transient coincidence, LF interference,
spectral-band overlap, heuristic harmonic roughness, bar-level
energy/density complementarity; measurements only, no verdict fields).
First run on the real pair: no feature separates successes 0/20 from
their neighbors — recorded as a failure with a structural explanation
(whole-bar shifts preserve beat alignment, so frame-scale features
measure grid quality shared by all candidates) and a contradictory
example (the two successes disagree in sign on bar-density
correlation). Next candidates: time-resolved per-bar series compared
as curves; phrase-boundary/cadence co-occurrence; audition the near
negatives. 242 tests; production untouched.

## 2026-07-11 — Grounded labels + phrase-scale slice

Built per direction (production untouched): (1) blinded audition
workflow (research/audition.py) — identical comparison windows per
offset, consistent RMS/peak normalization, seeded blind IDs with the
mapping sealed in key.json, structured viability/coherence responses
allowing multiple viable offsets, full provenance, unseal step that
refuses incomplete sessions; clips are derived copyrighted audio under
gitignored fixtures/local/, never committed. Two sessions rendered for
the current pair (anchor −3..+3 @ host bars 8–16; delayed 17..23 @
28–36) — labels pending human listening, neighbors NOT assumed
negative. (2) Phrase-scale trajectory probe (research/trajectories.py):
ordered per-bar series compared as shapes (local correlation,
complementarity, change-point co-occurrence, localized conflict maxima).
(3) Experimental stem-aware path (research/stems.py): external stems as
data (no new dependency), crude pseudo_ HPSS fallback with no vocal
pseudo-stem, provenance-naming measurements that abstain when stems are
missing. (4) Within-pair ranking evaluation (research/evaluation.py):
pairwise accuracy / success rank / top-k / abstentions, both directions
always reported, hypothesis labels only under an explicit provisional
flag. Ranking on the real pair: strict-run 1.0-accuracy features are
confounded by cross-region drift and in-sample direction choice; the
provisional winner (novelty co-occurrence, lower-better) inverts the
intuitive story — promoted to nothing. Benchmark plan recorded: 10–15
pairs stratified by move family, grouped by pair, leave-one-pair-out
required before proposing any production feature. 280+ tests.
