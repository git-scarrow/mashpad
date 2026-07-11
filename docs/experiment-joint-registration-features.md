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

## Blinded audition workflow (grounded labels)

Module `mashpad.research.audition`, CLI
`scripts/audition_registrations.py` (`render` / `unseal`). Labels become
evaluation truth only through this path: a human listening **blind**, on
**identical comparison windows**, with **consistent normalization** —
never the known construction, never an analyzer.

- One session = one host bar window rendered against every tested
  offset. Per side RMS is matched (−20 dBFS) before mixing and every
  clip peaks at the same level, so loudness cannot leak a preference.
- Clip IDs are a seeded random permutation (`clip_a`, `clip_b`, ...);
  filenames and the response template contain no offsets. The mapping is
  sealed in `key.json` (do not open until `responses.json` is saved).
- Responses per clip: `viable` (true/false/"unsure"), 1–5 ratings for
  rhythmic / harmonic / phrase-section coherence and masking-density
  conflict (1 = severe), confidence (low/medium/high), notes. **Multiple
  clips may be viable** — the workflow never presumes one winner or that
  neighbors are negatives.
- `session.json` records complete provenance: source paths + sha256,
  host metrical interpretation, pitch shift, window bars and seconds,
  stretch handling, normalization targets, seed, librosa version.
- `unseal` refuses half-filled or invalid responses, joins the key, and
  emits label records with `method = blinded_audition:<session_id>`.
  Mapping records into the corpus taxonomy is a human-reviewed fixture
  edit, deliberately not automated. Rendered clips are copyrighted
  derived audio: they live under gitignored `fixtures/local/` and are
  never committed (verified via `git check-ignore`).

### Sessions rendered 2026-07-11 (labels pending listening)

- `fixtures/local/auditions/anchor_neighborhood/` — offsets **−3..+3**
  around the anchor success, host bars 8–16 (~27.6–53.2 s), +2 st,
  seed 41, 7 blinded clips.
- `fixtures/local/auditions/delayed_neighborhood/` — offsets **17..23**
  around the attested delayed success, host bars 28–36, +2 st, seed 87,
  7 blinded clips.

The −3..+3 labels for this pair are therefore **unresolved until these
sessions are auditioned**; nothing below treats them as negatives.

## Phrase-scale trajectory probe

Module `mashpad.research.trajectories`, CLI `scripts/trajectory_probe.py`.
Extends the span-average probe to **ordered structural trajectories**:
per-aligned-bar series per side (onset density, RMS, low/mid/high band
energy, chroma, harmonic-change rate, tonal tension, novelty,
repetition, `midband_salience` [crude melodic/vocal proxy], build, drop,
`cadence_proxy` [crude]) and shape-preserving comparisons per
registration: whole-span curve agreement, **local** windowed correlation
(mean and minimum), complementarity (turn-taking) index, change-point
co-occurrence (novelty / harmonic-change / cadence peaks matched within
±1 bar), foreground-density collision, and **localized conflict maxima**
(per-bar loudness-weighted joint dissonance: max, location, mean) — not
only whole-span means. Cadence-to-*entry* relationships are declared out
of scope: an entry is an arrangement decision a bare registration does
not define. Locked by `tests/test_trajectories.py` (synthetic series
whose *order* differs where their averages do not).

## Stem-aware path (experimental instrumentation)

Module `mashpad.research.stems`, CLI `scripts/stem_probe.py`. Research
instrumentation only — never a production dependency or gate. External
stems are **data, not a dependency**: user-provided `<role>.wav` files
separated outside this repo (`vocals`/`drums`/`bass`/`other`).
`--pseudo` adds a crude librosa-only fallback (HPSS percussive/harmonic
+ low-passed-harmonic bass), with keys prefixed `pseudo_` so it can
never masquerade as real separation, and **deliberately no vocal
pseudo-stem** — a bad vocal mask would corrupt the one measurement
(vocal masking) stems exist to make honest. Measurements per
registration, each naming its stem sources: vocal masking, bass
interference, transient reinforcement/flam, competing foreground
activity; missing stems abstain with None.

## Within-pair ranking evaluation

Module `mashpad.research.evaluation`, CLI `scripts/ranking_report.py` —
the one sanctioned consumer of corpus labels. Per feature and per
direction (both directions always reported; choosing one is in-sample
fitting): pairwise preference accuracy (success vs negative, ties count
half), 1-based success ranks, top-3 recall, abstention counts. Only
`annotated` labels are truth; `hypothesis` labels enter only with an
explicit flag and mark the whole report `provisional` (audition
planning, never evidence). Too few labels ⇒ an abstention report, not
metrics.

### 2026-07-11 — ranking results, Skyfall / In the End (n=1 pair)

Strict run (annotated labels only: successes 0 and 20 vs the three
user-attested negatives 17/18/19 — 6 comparisons total): five features
reach pairwise 1.0 in the *lower-is-better* direction
(`bar_energy_corr`, `lf_interference`, `midband_salience.agreement`,
`midband_salience.complementarity`, `rms.agreement`), success ranks
(1,2). **Read with both confounds in view:** (a) four of the six
comparisons pit success@0 against negatives 20 bars away, where slow
position-in-song drift (e.g. `lf_interference` rises almost
monotonically with offset) does the separating — only the
success@20-vs-17/18/19 contrast is local, and there `bar_energy_corr`
at 20 (0.468) does sit below all three neighbors (0.522–0.560); (b) the
direction was selected in-sample, and the 17/18/19 negative labels are
user attestations without per-offset auditions on record. Suggestive at
most; converted into nothing.

Provisional run (hypothesis labels included, 2 successes vs 12
presumed negatives, flagged PROVISIONAL): the top feature is
`novelty.peak_cooccurrence` at 0.854 — in the **lower**-is-better
direction, i.e. the witnessed registrations show *less* structural
change-point alignment than their corrupted neighbors (offset 0 scores
0.000). That inverts the intuitive story and is exactly the kind of
witness-specific, likely-noise winner the ground rules forbid
promoting. No feature ranks both successes in the top 3 with a
coherent direction. Contradictions on record: the two successes again
disagree in sign on `onset_density.agreement` (+0.016 at 0, −0.192 at
20). Pseudo-stem measures (bass interference, percussive transients)
drift smoothly with offset — no separation.

**Conclusion this run supports:** with current features and current
(mostly unaudited) labels, the probe does not reliably rank validated
registrations above corruptions. The binding constraint is labels, not
features — the blinded sessions above are the next action, and every
metric here must be recomputed once they are resolved.

## Multi-pair benchmark and corpus acquisition plan

Target: **10–15 pairs stratified by mashup-move family**
(`docs/mashup-move-taxonomy.md`): 4–5 `overlay`, 2–3 `transition_blend`,
2–3 `rhythmic_graft`, 2 `hook_collision`, 1–2 `genre_contrast_blend` —
materially different construction techniques, so a feature that only
works for vocal-over-instrumental overlays is exposed as such. Sourcing,
in priority order:

1. **Published mashup recipes**: mashups with known source pairs where
   the user owns both recordings — the arrangement is an existence proof
   (witness), and discovery + blinded audition localize the registration.
2. **Library pairs proposed by discovery**: run
   `propose_construction.py` across the user's library, audition the
   top proposals blind; viable ones become successes, their neighbors
   become the near-negative sessions.
3. **Deliberately incompatible control pairs** (expected all-negative):
   guard against features that "succeed" by preferring any registration.

Per pair: one or two 7-clip blinded sessions (±3 bars around each
candidate success), at least one hard harmonic negative (a
chroma-admissible offset judged bad by ear), one random negative.
Labeling budget ≈ 10–15 min listening per session ⇒ roughly 4–6 hours
of listening for the full benchmark. Evaluation keeps song-pair
identity **grouped** (no clip-level shuffling across pairs) and requires
**leave-one-pair-out** results before any feature is proposed for
production. Until then, production compatibility scoring does not
change.
