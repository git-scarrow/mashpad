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
