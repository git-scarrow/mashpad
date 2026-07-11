# Experiment: joint-overlay features for registration discrimination

Status: design + minimal probe implemented, first probe run recorded
below. Research layer only. 2026-07-11.

## Objective

Identify measurable properties that emerge from the **synchronized
combination** of two audio streams and distinguish successful mashup
registrations from unsuccessful nearby registrations, **across multiple
song pairs**.

This replaces the phrase-class search gate (reverted the same day — see
`docs/decision-log.md`). That gate excluded the −1/−2/−3 neighbors of a
known-good registration because they violated a presumed 4-bar phrase
convention derived from the one witness pair's attested members. It was
an overfit workaround, not evidence of analytical capability. The
standard now: a successful result must explain why the known good
registration differs from its −1/−2/−3 neighbors using
**waveform-derived evidence that was not encoded from that example**.

## Ground rules

1. No feature or rule may be derived solely from the current witness
   pair (Skyfall / In the End). It is one evaluation case, nothing more.
2. No negative registration may be excluded because it violates a
   presumed phrase convention. Discovery evaluates all offsets; the
   probe measures all requested offsets.
3. Features are computed from the joint overlay or from explicitly
   synchronized cross-source representations — never by scoring each
   song independently and combining the scores afterward.
4. Weak correlations stay reported observations. No gates, no
   thresholds, until leave-one-song-pair-out evaluation shows a feature
   generalizes. Failures and contradictory examples are recorded in the
   results log below.
5. Production compatibility scoring is untouched until cross-pair
   generalization is demonstrated.

## Dataset: the registration corpus

Fixture: `tests/fixtures/registration_corpus_v1.json`
(schema `mashpad.registration_corpus.v1`), guarded by
`tests/test_registration_corpus.py`. Labels are **evaluation truth
only** — no discovery or probe code may read them as input.

Per pair:

| field | meaning |
|---|---|
| `pair_id`, `technique_family` | family from the mashup-move taxonomy (`overlay`, `transition_blend`, …) |
| `host` / `guest` | title + machine-local uncommitted path (`fixtures/local/…`); missing files are skipped, never failed |
| `conform` | the shared grid BPM and pitch shift the labels attach to (a different conform is a different audition), each with a resolution state |
| `registrations[]` | `{offset_bars, label, state, method, note}` — offsets in the anchor frame (guest delayed N host bars past the first-stable-downbeat coincidence; negative = guest earlier) |

Label taxonomy: `success`, `near_offset_negative` (a −1/−2/−3-style
whole-bar corruption of a success), `hard_harmonic_negative`
(per-track-compatible, fails in combination — the false-positive
killers), `random_negative`. Label states mirror the research layer's
resolution discipline: `annotated` (human audition or explicit user
attestation, method required), `hypothesis` (presumed, awaiting
audition — usable to plan listening sessions, **never** as evaluation
truth), `unresolved`.

Growth target before any generalization claim: **≥ 6 pairs spanning
≥ 2 technique families**, each pair carrying at least one success, its
−1/−2/−3 neighbors, one hard harmonic negative, and one random
negative. As of 2026-07-11 the corpus has n=1 pair and most of its
near negatives are hypotheses (not yet auditioned) — the fixture says
so in `honesty_notes`, and auditioning those neighbors is the
highest-value labeling work.

## Candidate joint phenomena

From the directive, with implementation status in the minimal probe
(`mashpad.research.joint_features`):

| phenomenon | probe feature | status |
|---|---|---|
| transient collision / reinforcement | `transient_sync_corr` (onset-envelope correlation at lag 0 on the shared timeline) + `transient_near_lag_excess` (how much better a ±1..4-frame lag fits — positive = flamming/near-miss signature) | measured |
| rhythmic periodicity | partially covered by the transient pair above; comb-filter periodicity of the *joint* onset train | partial / deferred |
| spectral masking | `spectral_masking` — loudness-weighted cosine overlap of synchronized band-energy profiles | measured |
| low-frequency interference | `lf_interference` — mean simultaneous low-band (< 150 Hz) loudness, each side normalized to its own 95th percentile | measured |
| harmonic roughness over time | `harmonic_roughness` — loudness-weighted pitch-class dissonance between synchronized chroma, guest rotated by the registration's pitch shift; kernel is a declared heuristic, not Plomp–Levelt | measured (crude) |
| phrase-energy complementarity | `bar_energy_corr` — Pearson correlation of per-aligned-bar mean RMS (negative = complementary) | measured |
| event-density complementarity | `bar_density_corr` — same over per-bar mean onset strength | measured |
| vocal intelligibility | — | **not measured**: requires stem separation, which this repo deliberately does not have |

Declared approximations: synchronization is a piecewise-linear time
warp between corresponding bar downbeats (no audio is rendered or
mixed); pitch shift is applied to chroma only (band/LF envelopes
compared unshifted); heavy per-frame features are sampled at a stride
(~90 ms). All constants are uncalibrated policy defaults declared at
the top of the module.

## Evaluation protocol

The unit of evidence is the **within-pair contrast**: feature value at
a `success` registration minus the value at each of its
`near_offset_negative` neighbors (and, separately, versus
`hard_harmonic_negative`s). A feature is a candidate discriminator only
if the contrast's *sign* is consistent across pairs; effect direction
is not assumed in advance (e.g. spectral overlap might help blends and
hurt overlays — that is for the data to say, per technique family).
Generalization test: leave-one-song-pair-out — a feature (or small
combination) must separate success from negatives on the held-out pair
using only the other pairs' data. Contradictory pairs are reported
here, not dropped.

## Minimal probe

```bash
uv run --extra tempo-librosa scripts/probe_registration_features.py \
    fixtures/local/skyfall.wav fixtures/local/in_the_end.wav \
    --offsets -3..26 --mark 0,20 \
    --json fixtures/local/skyfall_in_the_end.joint_probe.json
```

One row per offset — nothing excluded, nothing ranked. `--mark` is a
display-only flag for known witnesses; the module has no knowledge of
which offsets are labeled what.

## Results log

### 2026-07-11 — first probe run, Skyfall / In the End (n=1 pair)

Setup: host = Skyfall at the half-time reading (tracked 143.6 → 76.0
BPM), guest = In the End tracked 103.4 BPM, pitch shift +2 st (chroma
rotation), offsets −3..26 (30 registrations, all measured), stride 4.
Artifact: `fixtures/local/skyfall_in_the_end.joint_probe.json`
(machine-local, not committed).

**Result: failure to discriminate — reported as such.** No probe
feature separates the two attested successes (offsets 0 and 20) from
their −1/−2/−3 neighbors on this pair:

- `transient_sync_corr` is flat (0.24–0.33 across all 30 offsets;
  success@0 = 0.287 vs −1 = 0.293, +1 = 0.292) and
  `transient_near_lag_excess` is negative *everywhere* (−0.03..−0.08).
  This exposes a structural fact, not a tuning problem: **a whole-bar
  shift lands on another beat of the same grid**, so sub-beat transient
  alignment is preserved at every whole-bar offset by construction.
  Frame-scale transient features measure grid quality (shared by all
  candidates), not registration quality.
- `harmonic_roughness` is essentially constant (0.453–0.457). Full-mix
  chroma of these two productions is too smeared for a 12-bin
  pitch-class kernel to register which *bars of material* coincide.
- `spectral_masking` (0.646–0.664) and `lf_interference` (0.28–0.34,
  a slow drift tracking which song sections overlap, i.e. overlap
  length/position, not offset quality) are likewise non-discriminating.
- The bar-level correlations vary meaningfully but not in the witnesses'
  favor: `bar_energy_corr` peaks at offsets 4–8 (~0.59), not at 0
  (0.344) or 20 (0.468); `bar_density_corr` is 0.016 at success@0 but
  −0.192 at success@20 — the two successes disagree in *sign*, a
  contradictory example on record.

Interpretation (hypothesis, not conclusion): every probe feature
averages over the whole overlapped span, and whole-bar offsets preserve
beat alignment — so the discriminating evidence, if it exists in the
waveforms, likely lives at **phrase/section content scale** (which
material coincides: phrase-boundary and cadence co-occurrence,
energy-arc alignment, localized clash windows) rather than in
span-averaged frame statistics. Candidate next probes: time-resolved
per-bar feature *series* compared as curves (not means), joint
phrase-boundary co-occurrence from novelty functions, and
cadence-region convergence. Also worth noting: the near negatives on
this pair are mostly *hypothesis* labels — auditioning them is needed
before treating any of this as a discrimination test at all.

No feature earned gate status; nothing changes in discovery ranking or
production scoring from this run.
