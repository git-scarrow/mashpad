# Design memo: the Skyfall / In the End construction case

**Status:** research spike, parallel to the main roadmap. Nothing here
changes production scoring weights, verdict thresholds, provenance
semantics, or analyzer qualification gates.

**Reading order:** the numbered sections below record the spike's
original analysis and are kept as written; the dated **Update** and
**Correction** sections at the end supersede them where they conflict
(notably the tempo evidence — host ~74 after octave correction, guest
105 measured, and a ~74–90 BPM viability *region* rather than a single
grid). The fixture (`construction_skyfall_in_the_end.json`) always
carries the current values.

**The case (trusted artistic ground truth):** Adele's "Skyfall" is the
retained foundation. During a Skyfall chorus, Linkin Park's "In the End"
enters as an added vocal layer. One intended convergence: the stressed
"hard" in "I tried so hard" lands on the sung "fall" in "Skyfall" — or
within roughly one beat of it. The *viability* of the construction is
taken as known; the *exact alignment* is unresolved and is the central
empirical anchor.

**Artifacts of this spike:**

- `src/mashpad/research/construction.py` — the ground-truth construction
  schema (`MashupConstruction`, `GroundTruthField`, `AnchorEvent`,
  `Convergence`), with anti-laundering guards mirroring the provenance
  contract.
- `tests/fixtures/construction_skyfall_in_the_end.json` — the committed
  record of this construction: identity metadata plus bounded hypotheses;
  every empirical parameter explicitly `unresolved`/`hypothesis`.
- `src/mashpad/research/alignment_basin.py` — the smallest offset-aware
  scorer: point-process nearest-neighbor distance over annotated events,
  blind to titles by API.
- `tests/test_construction_case.py` — locks the executable negative
  result (production is offset-blind) and the basin's two findings
  (periodic ridge; anchor tie-break).

---

## 1. Diagnosis: what this construction can and cannot establish

### What the current program captures

Run through today's pipeline as a plain pair, the case behaves correctly
*at the pair level*:

- As `vocal_over_instrumental_overlay` with guest=`vocal` and
  host=`instrumental`, tempo/harmonic/phrase scores compute and the
  verdict is `MAYBE` on stub data — correct, and correctly humble.
- The tempo question is genuinely candidate-shaped: the two tracks'
  tempos (roughly 72–82 vs 100–110 BPM, both unverified priors) have no
  clean 1:1/2:1 relation, so the candidate-aware search and the
  ambiguity/override abstention gates are exactly the right machinery for
  deciding *whether any grid relation exists at all*.
- The evidence-first verdict's refusal to be confident on stub data is
  the right behavior here too: nothing about this pair is measured yet.

### What it structurally cannot capture

The construction is not a pair; it is a **directed, section-anchored,
event-aligned arrangement**, and four of its load-bearing properties have
no representation anywhere in the production data model:

1. **Entry point / windowing.** No field in `TrackAnalysis`,
   `evaluate_move()`'s signature, or `CompatibilityProfile` encodes *when*
   the guest enters or *which* host section hosts it. This is not a
   tuning gap but an input gap:
   `test_production_scoring_is_structurally_offset_blind` shows that
   shifting every guest section by arbitrary offsets yields a
   byte-identical profile (phrase fit reads only boundary *confidences*,
   never times).
2. **Selective insertion with a retained host.** The role vocabulary
   (`vocal`/`instrumental`/`full_mix`) cannot say "host full mix whose
   *own vocal remains load-bearing*." The convergence requires Adele's
   "fall" to stay audible — the host is not a bed, and the overlay
   premise (vocal over vocal-free backing) is literally false here. The
   role gate would abstain on `full_mix`/`vocal`... for the wrong reason
   (it abstains because the premise is unverified, not because the
   premise is *different*).
3. **Event-level convergence.** There is no concept of a musical event
   (word onset, accent, arrival) anywhere in the model, so "hard lands on
   fall" is not expressible, let alone measurable.
4. **A move timeline.** The construction is overlay-shaped at macro
   scale, hook-collision-shaped for a bar around the anchor,
   genre-contrast in aesthetic, and lyrical-juxtaposition in mechanism.
   One `MashupMoveType` per evaluation cannot express "these move types
   apply to different time spans of the same arrangement."

### What the case can establish

- A **capability boundary**, now executable: the intended alignment is
  indistinguishable from arbitrarily corrupted alternatives, by
  construction, not by weakness of tuning. Any future claim of
  "alignment-aware scoring" has a concrete falsifier to beat.
- A **representation** for phrase-level ground truth that keeps the
  evidence-first discipline (every field carries its resolution state).
- The **shape of the missing feature**: the basin harness demonstrates,
  on synthetic events, that beat-grid compatibility alone leaves a
  periodic ridge (whole-bar shifts tie with the intended offset) and that
  a single aperiodic lyric-anchor pair breaks the tie. Grid features can
  never explain *where* to land — only anchor events can.

### What it cannot establish

- Anything about **general** compatibility. One construction, however
  well annotated, is n=1. Nearby offsets are perturbations of that one
  example — they share every confound (same recordings, keys, timbres,
  lyrics) — and must never be counted as independent song-pair examples.
- Whether the alignment-basin score matches **perception**. The basin
  ranks offsets by annotated-event geometry; whether the geometric
  minimum coincides with the perceptual optimum is exactly what the
  listening protocol below has to test.
- Validated thresholds of any kind (tolerance in beats, anchor weights).
  These start as bounded hypotheses in the fixture and stay that way
  until resolved by the protocol.

## 2. The ground-truth representation

`MashupConstruction` (research layer only) asserts:

- **Identity:** exact recordings (`RecordingRef` — title/artist/version
  note; duration pinned from the local file before annotating, since a
  different edit shifts every time value).
- **Asymmetry:** `host` vs `guest` as *structural* fields, not a role
  relabeling. `host_retains_own_vocal: true` records that the host is
  not reducible to an instrumental bed. `conformed_side: "guest"` records
  which side gets stretched/shifted. Host/guest is deliberately a
  different axis than `TrackRole`: role says what stem-material a track
  contributes; host/guest says whose timeline is the frame of reference.
- **Anchoring:** the host section (`chorus`, occurrence a bounded
  hypothesis), the guest source phrase, and the guest entry offset
  (unresolved).
- **Treatment:** tempo (BPMs as bounded unverified priors; ratio
  unresolved — with the honest note that the ~77-vs-~105 relation makes
  the tempo treatment a real open question, possibly re-phrasing rather
  than stretching) and pitch (keys as priors; shift unresolved).
- **Events and convergences:** named `AnchorEvent`s (`host.fall`,
  `guest.hard`, plus phrase/section anchors) and a `Convergence` pairing
  a guest event with a host event, carrying the two central unknowns:
  `offset_beats` (hypothesis: 0.0, bounds ±1.0) and `tolerance_beats`
  (hypothesis: bounds 0.25–1.0, to be resolved by ear, not assumed).

Resolution discipline (`GroundTruthField.state`):

- `MEASURED` — sanctioned measurement seam only; refused for laundering
  methods, and refused *entirely* for event times until a real seam
  (forced alignment / onset measurement, built in the
  `tempo_measurement.py` pattern) exists.
- `ANNOTATED` — human annotation against the real recording; the research
  twin of `USER_ASSERTED`. Annotation feeding production `TrackAnalysis`
  must enter as `USER_ASSERTED`, capping verdicts at MAYBE — the research
  layer gets no side door.
- `HYPOTHESIS` — a bounded prior (bounds or a stated candidate value
  required).
- `UNRESOLVED` — the honest default. `unresolved_fields()` is the
  construction's open work list; for this fixture it currently lists
  every empirical parameter.

Committed fixture = identity + hypotheses. Event *times* live in a local,
uncommitted annotation file keyed by `event_id` (the
`fixtures/local/audio_index.json` pattern), because they are annotations
of commercial recordings we don't commit and can't derive in-repo.

## 3. What the convergence is

The "hard"→"fall" landing is a **compound** event, recorded as
`character` tags on the convergence rather than forced into one class:

- **accent alignment** — two stressed monosyllables coinciding at the
  beat/sub-beat level (the measurable core; what the basin scores);
- **lyric/semantic collision** — "tried so *hard*" against "let the sky
  *fall*": striving meeting collapse. This is the component that makes
  the moment *mean* something, and it is squarely in the
  `lyrical_conceptual_juxtaposition` capability v0 excludes;
- **phrase-boundary alignment** — the guest phrase plausibly enters
  relative to the host chorus arrival (unresolved: `guest_entry_offset_beats`);
- **intensity convergence** — chorus-level dynamics meeting the guest
  hook's emphasis (unmeasurable in v0; no energy curve exists).

Which components are load-bearing is an experimental question. The
protocol separates them: offsets that preserve grid alignment but break
the word coincidence (±1 bar) test whether the *semantic/accent* pairing
matters beyond rhythm; offsets that break the grid (±½ beat) test the
rhythmic floor.

**Taxonomy verdict:** this is *not* a new move type, and it should not be
classified prematurely. It is evidence that the taxonomy's move types are
**time-scoped aspects**, not exclusive labels — the missing concepts are
cross-cutting: (a) segment-scoped move application (an arrangement
timeline), (b) an anchor-event convergence constraint attachable to any
move, (c) a host/guest axis distinct from stem roles. The fixture records
this in `taxonomy_gap_notes` as data; changing the taxonomy now, off one
case, would be exactly the hard-coding this memo is trying to prevent.

## 4. Experimental protocol

Stepwise, each step with its verification, all local-only (no audio or
real paths committed):

1. **Pin sources.** Place both recordings under `fixtures/local/`;
   record duration (and a content hash) in the local annotation file.
   → verify: `duration_sec` fields move `unresolved → annotated`.
2. **Measure tempo through the sanctioned seam.** Run
   `scripts/eval_tempo.py --backend librosa` on both files; add them to
   the local tempo corpus. This does *not* wire anything into
   `analyze_track`; it resolves `host_bpm`/`guest_bpm` hypotheses and
   tests whether the 72–82 / 100–110 priors were even right.
   → verify: measured BPMs fall inside (or explicitly contradict) the
   fixture's bounds; contradictions update the fixture with a note.
3. **Annotate events.** In any label editor (e.g. Audacity), mark: host
   anchor-chorus boundaries, every "fall" onset in that chorus, ~8–16
   host downbeats spanning it; guest phrase onset, "hard" onset, guest
   downbeats around the phrase. Export to the local annotation JSON keyed
   by `event_id`. All `ANNOTATED`, never `MEASURED`.
   → verify: annotated downbeat spacing is consistent with the measured
   BPM (residuals ≪ half a beat) — this is the **tempo/beat-grid error
   detector**, see §6.
4. **Compute the basin.** Conform guest event times onto the host grid
   using the chosen tempo treatment (recorded in the fixture), then run
   `alignment_basin.basin()` over an offset grid: the hypothesized
   landing ±{0, ¼, ½, 1, 1½, 2} beats and ±{1, 2} bars.
   → verify: the basin's *shape* — is the intended offset a strict
   minimum (`is_distinguished`), a tie on a periodic ridge, or not a
   minimum at all? Each outcome is informative (see §6).
5. **Listening pass (the actual ground truth for tolerance).** Render the
   same offset grid as rough two-track bounces (any DAW; no repo code —
   rendering is out of scope by guardrail) and blind-rank a handful of
   offsets by ear. Resolve `tolerance_beats` from where the ranking
   collapses.
   → verify: geometric basin vs. perceptual ranking agree/disagree —
   *this* comparison, not the basin alone, is the finding.
6. **Write results back** into the fixture (states flip to `annotated`,
   bounds tighten) and append the outcome to the decision log.

## 5. The smallest parallel slice (built in this spike)

Schema + fixture + basin + tests, as listed at the top. Deliberately
excluded: audio decoding, rendering, forced alignment, any new
`TrackRole`/`MashupMoveType` member, any change under `mashpad/scoring`
or `mashpad/analysis`, and any CLI surface. The slice is complete when
(a) the construction round-trips with honest resolution states, (b) the
production offset-blindness is locked as a test, and (c) the basin
demonstrates ridge + tie-break on synthetic events. All three hold.

## 6. Success, failure, and overfitting criteria

**Success (per stage):**

- Protocol step 3: annotation self-consistency — downbeat residuals
  against the measured BPM small; multiple annotation passes of the same
  events agree within ~30 ms.
- Protocol step 4: `is_distinguished(intended, margin ≥ ~0.25 beats)` is
  True over the corrupted grid *when anchor events are included*, and
  False when they are excluded (the ridge must reappear — if grid-only
  features distinguish the landing, something is leaking).
- Protocol step 5: the perceptual ranking's top region contains the
  geometric minimum; `tolerance_beats` resolves to a bounded interval.

**Failure (each is a finding, not a bug to tune away):**

- Measured tempos contradict the priors so badly that no grid relation
  under 1:1/2:1/1:2 exists → the construction's tempo treatment is
  re-phrasing or free-time vocal delivery, and beat-relative offsets are
  the wrong parameterization. Record it; do not force a ratio.
- The intended offset is *not* the basin minimum → either annotation
  error (check step-3 residuals), a wrong hypothesis (the intended
  landing isn't "hard on fall" — maybe "hard" one beat *after* "fall"),
  or the geometric score mis-models the convergence. Distinguish via §
   "tempo error vs missing feature" below.
- Listening pass finds ±1 bar equally good → the lyric anchor is *not*
  load-bearing; the convergence is mostly grid + intensity. That would
  be a real discovery about what makes it work.

**Distinguishing a tempo/beat-grid error from a missing compatibility
feature:** the construction stores event times in *seconds* (annotated
domain) and evaluates offsets in *beats* (grid domain). A grid error
shows up as inconsistency *within one side* — annotated downbeats
drifting against the measured BPM, or "the intended offset in beats
pointing at the wrong audio moment." A missing feature shows up with a
*consistent* grid: residuals small, events correctly located, and the
scorer still unable to separate offsets. Step 3's residual check runs
before any basin conclusion is trusted.

**Overfitting guards:**

- Nearby offsets are never counted as independent examples; the unit of
  evidence is *one construction*, and its results generalize only as a
  hypothesis to test on the *next* construction.
- No song-specific logic anywhere in `src/` — the schema and basin are
  generic; everything Skyfall-specific is data in one fixture. The basin
  API consumes only times, kinds, weights, and a beat period; it cannot
  see titles.
- Anchor weights and margins in tests are structural (testing tie vs.
  strict minimum), not tuned constants; the fixture's tolerances stay
  `hypothesis` until the listening pass resolves them.
- The anti-laundering guards make the flattering shortcut — marking
  annotated times "measured" so a future confident verdict could lean on
  them — a hard error.

## 7. When would learning be justified?

Not now. The defensible sequence:

1. **Now (n=1):** constrained alignment search + basin analysis +
   listening calibration — system identification of one construction.
2. **Calibration (n≈5–15 constructions):** annotate more known-good
   constructions (each cheap: a dozen events). Check whether one
   weighting of event kinds ranks every intended offset first within its
   own pair. This is *calibrating an existing geometric model* — few
   parameters, leave-one-construction-out validation.
3. **Learning (n≳50, only if calibration fails):** the fitting problem
   is **within-pair learning-to-rank over candidate alignments**
   (listwise, offsets of one pair as one group) — emphatically *not* a
   general pair-compatibility regressor. Features stay the interpretable
   event-geometry residuals; labels come from constructions and
   listening passes. Anything trained here feeds the verdict layer as
   one more evidence dimension with its own provenance, never as a
   replacement for the abstention gates.

## 8. Feedback into the roadmap (without displacing it)

- **Analyzer priorities get sharper, not different.** The case raises
  the value of the already-planned beat-grid dimension (`beatgrid` is
  already in `PROVENANCE_DIMENSIONS` with no producer) and adds one new
  future seam: event/onset times (vocal onsets or forced alignment),
  which should arrive as a `measure_events()` twin of `measure_tempo()`
  when it arrives at all.
- **Verdict/provenance layers are untouched and validated by the case:**
  every abstention the current gates would emit for this pair is
  correct. The research layer routes human truth through
  `ANNOTATED`/`USER_ASSERTED`, so the MAYBE cap holds.
- **Taxonomy:** no change now. The fixture's `taxonomy_gap_notes` and
  `related_move_types` accumulate as evidence; revisit segment-scoped
  moves / anchor constraints / host-guest axis only when ≥2–3
  constructions show the same gaps.
- **Eval plan:** constructions become a fourth kind of corpus row
  eventually (directed arrangement ground truth alongside the three
  `ValidationClass` buckets), but only after the protocol has actually
  resolved one construction end-to-end.

---

# Update 2026-07-09: a human-auditioned witness (djay Pro session)

New empirical information substantially sharpens the case. The user
manually reproduced the mashup in djay Pro and found a stable, musically
convincing arrangement:

- Skyfall as host, read at **~74 BPM — corrected by the user from
  djay's initial ~148 BPM octave-doubled reading**. (A live instance of
  the octave-ambiguity failure mode the production verdict layer
  abstains on; the human correction is exactly the `USER_ASSERTED` path
  the override model describes.) In the End was **correctly measured by
  djay at 105 BPM**.
- Both decks synchronized at **74 BPM** (the witnessed working point —
  see the correction section below for the viability *region*); In the
  End slowed ~29.5% (ratio 74/105 ≈ 0.705) — resolving the earlier open
  question: at the witnessed point the tempo treatment is a single
  slow-down of the guest, not a half/double reading or re-phrasing.
- Visible beat grids support a measure-index offset of
  **Skyfall measure = In the End measure + 22** (77↔55, 78↔56, …).
- With that offset the mashup is particularly effective from
  approximately **Skyfall chorus 2 through the bridge and final chorus**
  — a sustained multi-section construction, not a single lyric-anchor
  coincidence. The "hard"-on-"fall" landing remains one salient event
  *within* that window, no longer the sole ground-truth target.
- In the End appears transposed **+2 semitones** — read off djay's
  display, explicitly to be verified from the saved session/source, not
  accepted from the screenshot.

## Scope of the claim: witness, not target

The 22-measure alignment is **one successful construction example** — an
existence proof — not the only valid overlay between these songs and not
an arrangement Mashpad must *uniquely* recover. This is now enforced in
the schema (`claim_scope` is always `"witness"`; anything else is a
`ValueError`) and changes the success criteria below: the model's job is
to score the witness region as viable and its *degraded neighbors* as
worse, never to rank this construction above every other conceivable
overlay (others may be independently valid and are not counterexamples).

## The three-level ground-truth hypothesis

The schema now distinguishes (documented on `MashupConstruction`):

1. **Global conformance** — tempo interpretation + transformation onto a
   shared grid: host ~74 BPM (annotated: the user's octave correction of
   djay's ~148 reading), guest 105 BPM (research-layer measured: djay's
   analyzer, ratified by ear), shared grid 74 BPM (annotated: the
   witnessed working point, not the unique grid — see the correction
   section), guest ratio 0.705 at that point (grid-choice dependent),
   apparent +2 st on the guest (hypothesis, verify).
2. **Structural alignment** — `GridAlignment`: measure offset +22
   (hypothesis, bounds 21–23 — read off djay's grids, which may
   themselves be mis-gridded), example correspondences (validated for
   internal consistency), `offset_constant_across_window` (unresolved —
   drift would indicate a grid error on one side), and `AlignedWindow`s
   with human judgments (the chorus-2→final-chorus window is ANNOTATED
   "musically convincing"; its precise entry/exit measures are
   unresolved).
3. **Local convergence events** — the existing `Convergence` records,
   now framed as candidate *explanations* for why the window feels
   especially effective, each individually testable.

Provenance treatment of the session evidence: **human listening
judgments are `ANNOTATED`** (they are the ground-truth kind this case
exists for); **values read off djay's display or beat grids are
`HYPOTHESIS`** with method strings naming the source
(`djay_session_observation`, `djay_beatgrid_readout`,
`djay_display_user_observed`) — user-observed, never authoritative, and
never a path to `MEASURED`.

## Revised immediate empirical task

Validate the witness from the exact audio files. In order:

1. **Correct both beat grids** against the source audio (pin files;
   measure tempo via the librosa seam; annotate downbeats; check
   residuals). Everything below is conditional on this step.
2. **Is the +22 offset exact** on corrected grids, and **constant across
   the window** (77↔55 and 78↔56 must both survive grid correction)?
3. **Precise entry and exit measures** of the effective overlap
   (resolves the window's `start/end_host_measure` and
   `guest_entry_offset_beats`).
4. **Is +2 semitones part of the recipe?** Verify from the session; then
   A/B 0 vs +2 st at the witness offset in the listening pass.
5. **Where do "hard" and "fall" land** relative to the corrected grid —
   is the landing *implied* by the structural offset, or does it need
   its own micro-adjustment? (Resolves the convergence's
   `offset_beats`.)
6. **Inventory other convergences** across chorus 2 / bridge / final
   chorus: phrase, section, harmonic-arrival, intensity — each becomes
   an `AnchorEvent`/`Convergence` row and a timeline entry.
7. **Do nearby offsets degrade the whole extended passage**, not only
   the lyric event? Audition ±1–2 measures (and ±1–2 beats) against the
   witness; record each as an `OffsetAudition` (currently: +22
   annotated, ±1 measure explicitly unresolved).

## The new artifact: the construction timeline

`mashpad.research.timeline` + `tests/fixtures/timeline_skyfall_in_the_end.json`:
one row per annotated host measure on the corrected grid — host/guest
section labels, derived guest measure (`host − 22`), notable events,
human judgment — plus the `OffsetAudition` ledger for the witness offset
and its neighbors, and the transformation settings the timeline was
auditioned under. `render_markdown()` produces the human-readable table.
Entries are sparse by design (missing measure = not yet annotated) and
currently hold exactly what the session established: the 77↔55 / 78↔56
anchors and the offset-audition ledger.

## What this changes about the earlier analysis

- The alignment-basin framing survives but the basin's *domain* grows:
  the unit under test is now the extended window (structural level), with
  local convergences as within-window features. "Nearby offsets degrade
  the whole passage" is the structural-level basin question; the earlier
  single-anchor basin is the local-level version of the same experiment.
- The earlier protocol's step order inverts: grid correction and the
  measure-offset check now come *before* any anchor-event annotation,
  because the local convergence may simply be implied by the structural
  offset (that is question 5, and it is empirical).
- The synthetic ridge/tie-break results stand unchanged as capability
  demonstrations; the witness now supplies the real-data counterpart the
  synthetic tests were standing in for.
- Nothing changes for production: same verdict gates, same provenance
  semantics, same qualification bar. The case continues to *validate*
  the octave-ambiguity abstention (djay tripped on exactly that) and the
  USER_ASSERTED cap (every session-derived value is a human claim).

---

# Correction 2026-07-09 (later): tempo evidence, and a viability region instead of a point

Two corrections to the update above, both now reflected in the fixture,
schema, and timeline.

## 1. Who erred, and what the octave correction changed

The tempo-analysis error was on **Skyfall**, not In the End:

- **In the End: 105 BPM, correctly identified by djay.** Recorded as a
  research-layer `measured` value (method `djay_tempo_analysis`, ratified
  by ear at the metrical level), subject to ordinary re-verification
  against the pinned source file — but *not* an unbounded estimate.
  (Research-layer `measured` never flows into a production
  `TrackAnalysis` as MEASURED except through the sanctioned
  `measure_tempo` seam.)
- **Skyfall: a metrical-octave interpretation issue.** djay initially
  read ~148 BPM; the user corrected the octave-doubled reading to ~74
  (recorded `annotated`, method `user_octave_correction_of_djay_reading`).

The correction was not cosmetic — **it changed the available
transformation path**. Read at 148, conforming the pair would have meant
accelerating In the End 105→~148 (~+41%, drastic). Read at 74, In the
End could instead be *slowed* 105→74 (~−29.5%). Estimation correctness,
octave interpretation, and transformation choice are three separate
facts, and the record now keeps them separate.

Minimizing transformation severity was **part of how this viable
construction was found** — an important candidate-selection feature —
but it is *not* a universal rule that the smallest tempo change produces
the best mashup (see correction 2: the construction does not require the
mathematically nearest compromise).

**General requirement exposed for Mashpad:** when two tracks' tempo
estimates differ by a metrical octave, candidate generation should
compare octave-equivalent interpretations *and the transformation
costs each implies* before rejecting or heavily penalizing the pairing.
Production's candidate search already enumerates half/double *relations*;
what it lacks is the coupling to transformation cost — the octave chosen
for one track changes which treatments of the other track are feasible
and how severe they are.

## 2. Tempo compatibility is a bounded region, not a point

74 BPM is **not** the unique or optimal common tempo — it is the
*witnessed working point*. Current human judgment: a region of roughly
**74–90 BPM is likely viable**, recorded as
`grid.viable_grid_bpm_region` (hypothesis — a provisional
human-auditioned interval, not a verified hard range; exact upper
boundary unresolved and suitable for audition testing).

The meaningful constraint is **asymmetric by role**:

- The **host places the main upper bound**: beyond some point Skyfall
  increasingly sounds rushed and loses its intended pacing, weight, and
  dramatic character. The low end preserves Skyfall near its natural
  pace.
- The **guest tolerates substantial slowing** from 105.
- Acceptability = host-character preservation — *not* minimal aggregate
  transformation, and *not* the mathematically nearest compromise.

Endpoint arithmetic that makes the asymmetry concrete:

| shared grid | Skyfall (host) | In the End (guest) |
| --: | :-- | :-- |
| 74 BPM | ~unchanged | −29.5% (105→74) |
| 90 BPM | +21.6% (74→90) | −14.3% (105→90) |

At 90 the *aggregate* transformation is smaller, yet viability is
*less* certain — because the cost that matters is the host's character,
not a percentage. **Modeling requirement:** transformation cost is not
symmetric and cannot be judged by absolute percentage change alone; the
same shift may be acceptable for one role and damaging for another.
Host preservation, song character, vocal delivery, rhythmic feel, and
the intended move must shape the acceptable tempo region. (Production's
anchor/adjustable asymmetry is a first step in this direction, but it
models *which side gets stretched*, not *how much stretch a side's
character tolerates*.)

Superseded wording, explicitly: 74 BPM is not "the sole correct common
grid"; the least-drastic aggregate transformation is not "necessarily
preferred"; the 74/105 ≈ 0.705 ratio is the witnessed point, not the
construction's definition; and tempo compatibility for this pair is a
bounded region, not a single point.

## The next experiment: a tempo sweep over the candidate interval

A small blind or semi-blind sweep across the candidate interval,
preserving the same structural offset (+22 measures) as closely as
possible. For each grid setting, record judgments on the five
dimensions in `timeline.TEMPO_SWEEP_ASPECTS` — host naturalness, guest
intelligibility, groove, dramatic weight, overall effectiveness — and
use the results to **estimate a viability curve or interval**, never to
fit one chosen BPM. The `TempoAudition` ledger in the timeline fixture
pre-registers the sweep: 74 annotated (the witness), 78/82/86/90
unresolved candidates spanning the hypothesized region, and a 96 probe
*beyond* it to locate the host-rushed failure boundary rather than
assume it.

This remains **one witnessed construction family**: different common
tempos may require small alignment adjustments and may produce distinct
but valid versions of the overlay. Each sweep point that works is
another member of the family, not a new independent song-pair example.

---

# Refinement 2026-07-09 (3): downbeat anchor, aligned-but-muted, selective entrance

A further session finding replaces measure-offset bookkeeping as the
primary structural relation and splits "aligned" from "audible."

## The primary anchor is downbeat-to-downbeat

The songs align structurally by placing **the first metrically
established downbeat of each recording at the same moment**. In the djay
session this displays as ~"Skyfall bar 3 = In the End bar 1" — but the
displayed bar numbers are *not* the ground truth. Skyfall opens with a
brass "wahhh" gesture that an analyzer may count as a measure, treat as
pickup material, or omit from the regular grid entirely, renumbering
everything after it. The true anchor is **source-audio timestamps plus
musical function**, now represented as two `AnchorEvent`s
(`host.downbeat.first_regular`, `guest.downbeat.first_regular`) joined
by `GridAlignment.anchor` (`GridAnchor`), with djay's labels kept in
`session_bar_labels` as session-specific annotations. Once those
downbeats are aligned, the songs share a continuous usable measure grid
sufficient to support a structural mashup over later sections.

**Open reconciliation, flagged not resolved:** the anchor frame implies
a djay-label offset of ~+2, while the earlier chorus-region readout was
+22 (77↔55). These contradict each other on a single continuous grid.
Whether they describe the same alignment in different numbering frames
(app renumbering, deck re-cueing) or two distinct members of the
construction family is recorded as pending in the fixture and locked by
`test_offset_frames_await_reconciliation`. This is itself a live
demonstration of the fourth distinction below.

## Synchronized is not audible

Structural synchronization does **not** mean both tracks should be
audible immediately or continuously. The first ~7 bars of In the End
are not a good simultaneous overlay with Skyfall: the two piano
introductions clash — meters align, active harmonic and textural
material does not. The witnessed strategy keeps Skyfall solo through
the early aligned passage and brings In the End into the audible mix
around **its bar 8**, where the two songs' cadential movements become
similar or identical enough to support the overlap (recorded as the
`cadential_entrance` convergence — a hypothesis about the *enabler*,
testable by localizing both cadences on corrected grids).

Schema: `GuestAudibility` (muted / entering / audible) on
`AlignedWindow` and on timeline entries makes **aligned-but-muted a
first-class state**. The fixture now carries three windows: the muted
intro (clash judgment annotated), the ~bar-8 entrance (annotated, with
the cadential hypothesis), and the chorus-2→final-chorus audible window.

Four distinctions the record now keeps apart, permanently:

1. temporal alignment ≠ harmonic compatibility;
2. a track being synchronized ≠ it being audible;
3. a valid construction grid ≠ a valid full-duration overlay;
4. application bar numbering ≠ source-audio musical structure.

## The timeline, expanded

`TimelineEntry` now carries, per aligned measure: source-relative
downbeat timestamps for each song (`GroundTruthField`, unresolved until
annotated — the grid's ground truth), application bar labels *kept
separately* (`host_app_bar`/`guest_app_bar`), section/phrase identity,
`guest_audibility`, a harmonic-compatibility judgment, textural/
orchestration conflict, and relevant cadential events. The timeline
fixture is re-keyed to the anchor strategy (djay-label frame, host =
guest + 2, frame stated in `transformation_note`) and records the
audibility progression: muted (m1–m9) → entering (m10 ≈ guest bar 8) →
audible.

## The experiment now tests two independent questions

**A. Grid recovery.** Can Mashpad recover the metrically correct
downbeat-to-downbeat alignment despite Skyfall's ambiguous opening
gesture? This is a beat-grid/downbeat problem (the `beatgrid` provenance
dimension, still producer-less) and Skyfall's opening is a natural
adversarial test case for any future downbeat analyzer: success =
first-regular-downbeat within tolerance of the human annotation;
failure by an octave or by miscounting the opening is exactly the error
family the session already exhibited (djay's ~148 reading, bar-label
renumbering).

**B. Admissibility on a given grid.** Given the shared grid, can
Mashpad distinguish the clashing first seven guest bars from the viable
entrance around guest bar 8? Production cannot even pose this question:
its harmonic evidence is one global key per track — window-blind by
construction, the harmonic analogue of the offset-blindness result. A
future windowed harmonic/texture comparison has a concrete falsifier:
it must score guest bars 1–7 as inadmissible against the aligned host
material and the bar-8+ region as admissible, using audio evidence, not
titles or annotations.

## Layered construction search

The case demonstrates the search order a construction-aware Mashpad
would need:

1. find a plausible shared metric grid (tempo interpretation + downbeat
   anchor — question A);
2. identify compatible audible windows on that grid (question B);
3. choose entrances, exits, mutes, or stem selections;
4. then evaluate local phrase-level convergences ("hard"/"fall",
   cadences).

Each layer has its own evidence requirements and failure modes; the
production pipeline currently operates only at layer 0 (global pair
compatibility) — layers 1–4 are the roadmap this case keeps exposing,
one witnessed observation at a time.

Witness framing preserved: this is one successful arrangement strategy
for the pair, not the only valid overlay.

---

# Resolution 2026-07-09 (4): +2 confirmed; the annotation gap, stated plainly

## The frame question is resolved by the user

Reconciliation was authorized and settled: **the +2 structural relation
is correct** — djay Skyfall bar 3 = djay In the End bar 1. The earlier
"+22" observation (77↔55) was a later *local measure-number readout from
a different numbering frame*, not a rival alignment hypothesis. The
fixture now records `grid.measure_offset` = 2.0, state `annotated`,
method `user_attested`; the "reconciliation pending" status and the
stale different-frame ledger entries are removed, and no further user
annotation is required to settle this.

The epistemic layering survives the resolution, deliberately:

- the *musical* anchor remains first-established-downbeat to
  first-established-downbeat, with source-audio timestamps (still
  unresolved) as its ground truth;
- djay's visible bar labels remain session-specific annotations;
- Skyfall's opening brass gesture may still shift how another analyzer
  numbers the bars — so +2 is the witnessed relation *in the djay
  frame*, not a frame-independent constant.

## What annotation tooling actually exists: none

Previous sections said things like "annotate events locally" and
"annotate from source audio" as if that were an available step. It is
not. Plain answers to the five questions:

1. **Executable workflow for loading both audio files: none.**
   `mashpad.io.audio_file.load_track` validates a file's extension and
   existence — it never decodes audio. The only audio decoding anywhere
   is inside the tempo backends (stdlib WAV readers; librosa behind the
   optional extra), reachable only through `scripts/eval_tempo.py`, one
   file at a time, producing tempo candidates only. Nothing loads two
   recordings together.
2. **Audition of aligned playback: none.** There is no playback code of
   any kind in the repository — no audio output dependency, no render
   path. Aligned audition happens entirely in external tools (djay),
   which is where every witnessed judgment so far actually came from.
3. **Entering downbeats, section boundaries, mute/entry windows, or
   judgments: none.** There is no interactive interface of any kind —
   no clicking, no tapping, no prompt-driven entry.
4. **Persistence of such inputs into the research fixtures: none.**
   Nothing reads or writes annotations. The construction and timeline
   fixtures are hand-edited JSON. Even the "local annotation file keyed
   by event_id" that the schema docstrings reference has no loader —
   `alignment_basin` consumes `TimedEvent` lists a caller must build
   by hand in code.
5. **Command or UI exposing an annotation workflow: none.** The two
   entry points are `mashcheck` (stub-analysis compatibility report)
   and `scripts/eval_tempo.py` (tempo-backend evaluation). Neither
   touches constructions, timelines, events, or judgments.

Accordingly: earlier protocol steps that read "annotate X" should be
read as "this value must *become* annotated," with the honest current
mechanism being an external tool plus hand-editing JSON — which is not
a workflow. Next-step language elsewhere in this memo is corrected by
this section.

## The smallest missing executable path (identified, not built)

The gap is narrow, because the hard interactive parts already exist
outside the repo: djay provides aligned audition; any label editor
(e.g. Audacity's label track, exported as plain tab-separated
`start\tend\tlabel` text) provides click-to-timestamp entry against one
recording at a time. What the repo lacks is only the **import seam**:

1. parse an exported label file (stdlib text parsing, no new deps);
2. match label text to construction `event_id`s (and timeline measures);
3. write a local, uncommitted annotations JSON keyed by `event_id`
   (the file the schema already anticipates);
4. apply it to a `MashupConstruction` — flipping matched event
   `time_sec` fields to `ANNOTATED` (never `MEASURED`) — and emit
   `TimedEvent` lists for `alignment_basin`.

That single script/module (roughly: `annotations.py` + a small CLI)
would make the existing structures reachable from real audio without
building any annotation application, playback engine, or UI. It is the
next executable artifact worth building — deferred until the user wants
the basin run against real annotations, per the no-broad-tooling
instruction.
