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

---

# Built 2026-07-10: the label-import seam

The smallest missing executable path identified in the previous section
now exists — and nothing more:

- **`mashpad.research.annotations`** — the importable, unit-tested core:
  - `parse_label_file` reads an Audacity-style label export (plain
    tab-separated `start  end  label`; point and region labels, blank
    lines and extended-format frequency lines tolerated; malformed rows
    fail loudly with their line number).
  - `import_labels` matches one side's rows against the construction: a
    label naming an `event_id` annotates that event (region labels use
    their start time; a cross-side match is a loud error — a label file
    annotates one recording; a duplicate named-event label is a loud
    error); a label naming an `EventKind` value ("downbeat", "cadence",
    "phrase_onset", "section_boundary", "lyric_stress_onset") appends to
    that side's grid events; everything else is *reported* unmatched,
    never silently dropped. Pure function — merging returns a new
    `AnnotationSet`.
  - `AnnotationSet` is the local annotation store the schema always
    anticipated: named-event times plus per-side grid-event lists,
    JSON-round-tripped under `fixtures/local/` (real timestamps of
    commercial recordings — gitignored, never committed, the
    `audio_index.json` policy; `fixtures/README.md` updated).
  - `apply_annotations` returns a construction whose matched event times
    are `ANNOTATED` — never `MEASURED`; the `AnchorEvent` guard would
    reject that independently.
  - `basin_events` emits one side's `TimedEvent`s (grid + annotated
    named events, weight-per-kind as an explicit experimental knob) for
    `alignment_basin`.
- **`scripts/import_labels.py`** — thin CLI shim, `eval_tempo.py`
  convention:

      uv run scripts/import_labels.py \
          --construction tests/fixtures/construction_skyfall_in_the_end.json \
          --side host --labels fixtures/local/skyfall_labels.txt \
          --annotations fixtures/local/skyfall_in_the_end.annotations.json

  It prints what matched, what went to the grid, what didn't match, and
  which of that side's event times remain unresolved; `--dry-run` writes
  nothing; a run that matches nothing exits nonzero and writes nothing.
- **`tests/test_annotation_import.py`** — including one end-to-end test
  that writes synthetic label files for both sides, runs the CLI twice
  into one annotation store, applies it to the committed construction
  fixture, builds basin events, and shows the basin distinguishing the
  intended offset from whole-bar corruptions. The full seam is
  executable without any real audio in the repo.

The honest workflow is now: audition and decide in djay → click
timestamps in a label editor against each source recording (label text =
the `event_id` from the construction fixture, or a kind like `downbeat`)
→ export → `import_labels.py` per side → the basin experiment runs on
the result. Still deliberately absent: audio loading/decoding for this
purpose, playback, and any interactive UI.

---

# Re-centering 2026-07-10: automatic discovery is the objective

The spike had drifted toward annotation tooling. The objective is
restated and now governs: **give Mashpad two songs; Mashpad analyzes
them and proposes one or more plausible constructions** — and one
proposal should recover the broad structure of the witnessed
arrangement *without manual event pins*. No Audacity, no djay, no
hand-edited JSON in the normal path. The witnessed values (74 not 148;
105; guest slowed; downbeat anchor; muted clashing intro; ~bar-8
entrance; +2 st; extended windows) are **acceptance evidence for this
one case**, never constants inside the discovery rules.

## Review of the spike's pieces under this standard

**Supports automatic discovery — remains:**

- the construction schema + fixture (the machine's target
  representation and the acceptance witness);
- `alignment_basin` (offset scoring — evaluation now, a candidate
  ranking component later);
- the executable negative results (production offset-blindness;
  window-blind harmonic evidence) — the capability boundary discovery
  must beat;
- the timeline (the record a resolved discovery run should be able to
  fill).

**Evaluation-only — demoted, not removed:**

- the label-import seam (`annotations.py`, `import_labels.py`): hidden
  evaluation truth and debugging aid. Never required for normal
  operation; never the primary workflow. CLAUDE.md updated accordingly.

**Premature — deprioritized:**

- the manual listening protocols (offset/tempo audition ledgers) as the
  *primary* experimental instrument. They remain valid human acceptance
  evidence, but the next experiments run through discovery output, not
  through more manual auditions.

## The automatic slice (built): `mashpad.research.discovery`

Two files in, ranked `ConstructionHypothesis` objects out:

1. **Decode + features** — `extract_features` (librosa, lazily imported,
   optional `tempo-librosa` extra): onset envelope, tracked beat grid,
   per-beat chroma and normalized RMS, plus octave-aware tempo
   candidates via the existing sanctioned librosa tempo backend.
   *Guardrail note:* this expands librosa use beyond tempo candidates
   (onset/beats/chroma/RMS) — authorized by the user's re-centering
   directive, **research layer only**; the production guardrail stands
   (nothing added to `analyze_track`/`mashcheck`, core deps stay empty).
2. **Metrical interpretations** — the tracked reading plus any half-time
   candidate (bar = 8 tracked beats). Double-time readings are declared
   unsearched (v1 limitation), not silently dropped.
3. **Shared-tempo candidates** — anchored at the host's metrical tempo,
   stepping toward the guest, ranked by **role-asymmetric transformation
   cost** (host stretch weighted 3x guest — an uncalibrated policy
   default encoding host preservation as selection pressure, not a
   rule). This is what makes the octave-corrected host reading outrank
   the doubled reading *without* a hard-coded preference for slower.
4. **Pitch shift** — guest mean-chroma rotation vs host, best and
   runner-up reported.
5. **Structural anchor** — first *stable* downbeat per side: downbeat
   phase by onset-strength share, stability by inter-beat-interval
   settling (so an irregular opening gesture falls outside the regular
   grid mechanically, not by hand-flagging).
6. **Admissibility + entry windows** — per aligned bar (bar-index
   mapping from the anchors): chroma fit after the shift + both-loud
   density; maximal runs above threshold become ranked entry windows;
   bars before the first window are the implied mute window
   (aligned-but-muted, machine-derived).
7. **Both host/guest assignments searched** — the role decision is part
   of the ranking, not an input.

Every hypothesis carries `evidence` (where each element came from) and
`uncertainty` (assumed 4/4; heuristic downbeat phase; unsearched
double-time; proxy admissibility; uncalibrated thresholds; global-not-
per-section pitch shift). Nothing produces or implies `MEASURED`
provenance.

CLI: `scripts/propose_construction.py` (thin shim):

    uv run --extra tempo-librosa scripts/propose_construction.py \
        SKYFALL_FILE IN_THE_END_FILE \
        --witness tests/fixtures/construction_skyfall_in_the_end.json \
        --json fixtures/local/hypotheses.json

`--witness` prints the acceptance report: `witness_agreement` compares
the top hypothesis field-by-field against the committed fixture
(AGREES/DIFFERS lines) — expectations read from fixture data, never from
code constants.

## Verification

- 12 new tests (`tests/test_discovery.py`): the pure core (phase choice,
  stability, transposition recovery, half-time interpretation from the
  candidate set, host-preserving grid ranking, octave-corrected-beats-
  doubled cost ordering, clash-then-bar-8 entry windows with the mute
  window derived, ranked/serializable hypotheses, fixture-driven witness
  agreement) plus one librosa-gated end-to-end on WAVs synthesized
  in-test.
- CLI smoke test on synthesized 74 vs 105 BPM chord/click WAVs: top
  hypothesis chose the slow track as host, preserved it (grid ~73.8,
  guest x0.714), aligned first stable downbeats, recovered the built-in
  transposition, and the witness report correctly AGREED on tempo/grid
  fields and DIFFERED where the synthetic pair genuinely differs from
  the witnessed case.

## The acceptance run (next, requires the two local files)

    uv run --extra tempo-librosa scripts/propose_construction.py \
        <skyfall> <in_the_end> \
        --witness tests/fixtures/construction_skyfall_in_the_end.json

Success = a top-ranked hypothesis recognizably related to the witnessed
arrangement: host read near 74 (not 148), guest near 105, grid in/near
the viable region with the guest slowed, a downbeat anchor, a muted
opening, an entrance near guest bar 8, and +2 st — each AGREES/DIFFERS
line is a finding either way (a DIFFERS on the entrance, for example,
localizes exactly which admissibility signal is too crude). Manual
annotations, if ever gathered, serve only to diagnose *why* a field
differed.

---

# Acceptance run 2026-07-10: discovery recovers the witnessed construction

The two source recordings were present locally
(`fixtures/local/skyfall.wav`, `fixtures/local/in_the_end.wav` — mono
22050 Hz conversions of the owned FLAC/mp3, already indexed for tempo
eval). The acceptance run:

    uv run --extra tempo-librosa scripts/propose_construction.py \
        fixtures/local/skyfall.wav fixtures/local/in_the_end.wav \
        --top 3 --witness tests/fixtures/construction_skyfall_in_the_end.json

**Result: every comparable field of the top-ranked hypothesis AGREES
with the witnessed construction.** No manual pins, no annotations, no
song-specific constants:

| element | witnessed | proposed (top hypothesis) |
| :-- | :-- | :-- |
| roles | Skyfall host / In the End guest | same (assignment search) |
| host metrical BPM | ~74 (corrected from djay's ~148) | 76.0 — half-time reading of the tracker's 143.6 (the same octave error, corrected mechanically) |
| guest BPM | 105 | 103.4 |
| shared grid | 74, viable region 74–90 | 76.0, host preserved, guest −26.5% |
| pitch shift | +2 st (verify from session) | +2 st (chroma score 0.977) |
| opening | guest aligned-but-muted (piano clash) | no sustained admissible window in bars 1–7 → muted through bar 7 |
| entrance | ~guest bar 8 | guest bar 8, opening an unbroken run to bar 84 (mean chroma fit 0.862) |

The per-bar profile substantiates the entrance rather than it being a
threshold accident: bars 1–7 oscillate between 0.30 and 0.79 (volatile —
individual bars pass but no run of MIN_WINDOW_BARS sustains), and bar 8
begins a 77-bar sustained admissible window. The extended window also
matches the witnessed "sustains a convincing multi-section construction"
observation, not merely a lyric coincidence.

**Independent replication of the human path:** librosa's tracker made
the *same* octave error djay made (143.6 ≈ the ~148 reading), and the
role-asymmetric cost model made the same correction the user made —
evidence that the cost asymmetry captures something real about
host-preserving construction search, not just this pair.

**Honest caveats, so this is not over-read:**

- The half-time candidate carried confidence **0.08** from the tempo
  backend. The correct interpretation won on transformation cost, not
  on tempo evidence — if the backend had omitted the half-time
  candidate, discovery would have missed 76 entirely. The octave
  interpretation remains the single most fragile link.
- The rejected role assignment ranked close (0.115 vs 0.092): the role
  decision is currently a lean, not a separation.
- The +2 runner-up (−3 st at 0.968) is nearly tied; the pitch decision
  is also a lean.
- Entry-bar agreement is measured guest-side (guest bar 1 = its first
  stable downbeat, matching the djay frame); the *host*-side anchor
  (1.63 s) has no resolved witnessed timestamp to compare against and
  still needs a listening check.
- n = 1 construction. This is acceptance on the witnessed case, not
  validation of the discovery model; the same run on other pairs (and
  on deliberately incompatible pairs) is the next falsification step.

This satisfies the spike's success criterion as restated: *Mashpad
received the two recordings and independently proposed a construction
recognizably related to the witnessed arrangement, with explicit
uncertainty and without manual pins.*

---

# Registration search 2026-07-10: the "+22" family member, machine-corroborated

**Question (user):** does discovery also propose the original ~+22
relation? The user attests it is structurally compatible as well — a
distinct family member, not merely a frame readout of the anchor
alignment (recorded in the timeline's offset ledger, `user_attested`).

**Answer, before this change: no — structurally it could not.** The
first slice evaluated exactly one registration (first stable downbeats
coincident) and only varied where the guest becomes *audible* within it.
Alternative registrations were not in the hypothesis space.

**The extension:** `search_alignments` now searches guest-delay offsets
0..48 host bars, scores each registration by admissible coverage × mean
window fit, proposes the top `ALIGNMENT_CANDIDATES` — and **always
proposes the anchor-coincident registration alongside them** (it is the
registration the downbeat anchors define; delayed registrations
implicitly discard host opening material, so dropping it would hide the
canonical family member rather than rank it). The witness report now
scans all proposals and prints the best-agreeing one, since acceptance
is "does Mashpad *propose* a recognizable construction," not "is it #1."

**Result on the real recordings** (Skyfall host, half-time 76 reading,
+2 st):

- The **delayed region is the global fit maximum**: anchor-frame offsets
  20–26 score 0.88–0.90 (peak 0.902 at offset 25), and the machine's
  #1–#3 hypotheses are now delayed registrations — corroborating the
  user's attestation that the ~+22 relation is structurally compatible,
  and matching the alignment basin's periodic-ridge prediction at
  section scale (a broad compatible ridge, not one sharp optimum).
- The **anchor registration** (offset 0, muted intro, bar-8 entrance)
  scores 0.772 — lowest of all 49 registrations by this metric — yet
  ranks #4 overall and carries the **full 5-AGREES witness match**.
- Frame caveat: djay's +22 maps to anchor-frame ~+20 *if* our detected
  host bar 1 equals djay bar 3; our peak sits at 25, and offsets 20/22
  themselves rank 14th/12th within 0.02 of the peak. The exact witnessed
  offset within the ridge is unresolved pending host bar-1 frame
  verification (the host anchor timestamp, 1.63 s, is still unchecked by
  ear).

**Modeling insight exposed, recorded rather than patched:** the
coverage-based fit metric structurally *penalizes* the witnessed
muted-intro arrangement — its intentionally silent bars count against
coverage, while delayed registrations skip them for free. An
arrangement-aware score should evaluate coverage over the *audible plan*
(post-entrance), not the whole aligned span. That is the next honest
refinement of the ranking, not a tweak to force the anchor registration
back to #1 — by raw simultaneous-compatibility the delayed registrations
may genuinely be stronger, and which family member is *artistically*
preferable (the dramatic muted-intro build vs. the immediate overlay) is
a human judgment the ledgers exist to capture.

---

# Phrase-class constraint 2026-07-11: loose-bar registrations are structurally wrong

**Question (user):** does discovery *exclude* djay-frame +19/+20/+21 —
the loose-bar neighbors of the valid +22 relation? Hint: it should.

**Answer before this change: no.** The chroma-coverage ridge was nearly
flat (anchor-frame 17–26 all 0.87–0.89): bar-level chroma is almost
blind to phrase grouping, so registrations that break the 4-bar phrase
structure scored about the same as ones that respect it.

**The constraint:** valid family members differ from the anchor
registration by **whole phrases** — offsets ≡ 0 (mod `PHRASE_BARS`) —
because both anchors are first metrically established downbeats,
*assumed* to open a 4-bar phrase (a declared assumption in every
hypothesis's uncertainty list, not a measurement; 8-bar hypermeter is
not modeled). Off-phrase offsets are structurally wrong, not merely
weaker, and are no longer searched. The witnessed family is itself the
internal evidence for this class: the two attested members (anchor 0 and
~+20) differ by exactly five 4-bar phrases.

A strength-based hypermetric phase estimate (the downbeat heuristic one
level up, on bar-downbeat onset strengths) is computed as
**corroboration only**. On this pair it *disagrees* (estimates residue
2) at confidence 0.29/0.28 against a 0.25 chance floor — too weak to
trust, and the disagreement is printed in every hypothesis rather than
silently resolved either way. If a future, better phrase estimator
confidently contradicts the anchor-derived class, that is a finding
about the anchors (a mid-phrase first stable downbeat), not a reason to
delete the constraint.

**Result on the real recordings:** proposed registrations are now 36,
24, 40 (all ≡ 0 mod 4) plus the always-proposed anchor (0, the 5-AGREES
witness match at #4). djay +19/+20/+21 (anchor-frame 17/18/19 ≡ 1/2/3)
are excluded exactly as the user's hint requires — by a general phrase
constraint, not by any witnessed constant. The attested ~+22 member
(anchor-frame 20, fit 0.882) is in-class and searchable but currently
ranks 4th within the class, 0.013 below the class peak — surfacing it
among the proposals is a ranking question (arrangement-aware coverage,
or a larger ALIGNMENT_CANDIDATES), not an admissibility one.

Locked by `test_off_phrase_registrations_are_not_proposed`: with guest
material matching host content that begins at an off-phrase offset (18),
the search must not propose 17/18/19 and instead proposes the nearest
phrase-consistent registration, accepting the partial clash.

## Redirect: the phrase-class gate was overfit — reverted (2026-07-11)

The user's correction, verbatim in substance: stop treating the current
witness pair as a source of admissibility rules. The offset ≡ 0 (mod 4)
restriction added the previous day was justified by the witness pair's
own attested members (0 and ~+20 differing by whole phrases) — which is
exactly what makes it an **overfit workaround, not evidence of
analytical capability**. It is reverted as a search filter: discovery
evaluates every offset again, including the −1/−2/−3 loose-bar
neighbors of a known-good registration. Phrase-class membership
(offset mod 4) and the strength-based hypermetric estimate remain
computed and reported as descriptive metadata only.
`test_off_phrase_registrations_are_not_proposed` became
`test_off_phrase_registrations_stay_evaluated`, locking the opposite
invariant.

The research objective is re-stated: identify measurable properties
that emerge from the **synchronized combination** of the two audio
streams — not from per-track scores combined afterward — that
distinguish successful registrations from unsuccessful nearby ones,
**across multiple song pairs**, under leave-one-song-pair-out
evaluation. The witness pair becomes one evaluation case in a
registration corpus. A successful result must explain why the known
good registration differs from its −1/−2/−3 neighbors using
waveform-derived evidence that was not encoded from that example. No
weak correlation becomes a gate; production scoring stays untouched
until cross-pair generalization is demonstrated.

Built this turn: the experimental design and dataset schema
(`docs/experiment-joint-registration-features.md`,
`tests/fixtures/registration_corpus_v1.json` — labels carry resolution
states; most near negatives on the first pair are *hypotheses*, not
auditioned negatives, and the fixture says so), and the minimal joint
probe (`mashpad.research.joint_features`,
`scripts/probe_registration_features.py`): guest frames time-warped
onto the host timeline through each registration's bar correspondence,
then transient coincidence, low-frequency interference, spectral-band
overlap, heuristic harmonic roughness, and bar-level energy/density
complementarity measured on the synchronized pairs. Every requested
offset is measured; the probe has no rank, fit, or verdict fields.

First run on the real pair (offsets −3..26, all measured): **no
feature discriminates the attested successes (0, 20) from their
neighbors** — reported as a failure, per the ground rules. The most
instructive part is structural: a whole-bar shift lands on another beat
of the same grid, so sub-beat transient alignment is preserved at every
whole-bar offset by construction (near-lag excess negative everywhere);
frame-scale statistics measure grid quality, which all candidates
share. Full-mix chroma roughness is offset-invariant on this material
(0.453–0.457), and the two successes even disagree in sign on bar-level
density correlation — a contradictory example on record. Hypothesis
for the next probe: the discriminating evidence, if present, lives at
phrase/section content scale (which material coincides — boundary and
cadence co-occurrence, energy-arc alignment, localized clash windows),
i.e. in time-resolved per-bar series compared as curves, not
span-averaged frame statistics. And before any of this counts as a
discrimination test at all, the near negatives need auditioning.

## Grounded labels and phrase-scale structure (2026-07-11, second slice)

The program's next slice, per direction: grounded registration labels
plus phrase-scale joint structure. Production ranking, compatibility
scoring, and search gates untouched.

**Blinded audition workflow** (`research/audition.py`,
`scripts/audition_registrations.py`): identical host-window comparison
clips per tested offset, per-side RMS matching + common peak target,
seeded-permutation blind IDs with the offset mapping sealed in
`key.json`, structured responses (viability true/false/unsure — multiple
viable allowed — plus 1–5 rhythmic/harmonic/phrase-section/masking
ratings, confidence, notes), full provenance (sha256, transformation,
normalization, seed, versions) in `session.json`, and an `unseal` step
that refuses half-filled sessions. Two sessions are rendered for this
pair (gitignored, never committed): `anchor_neighborhood` (offsets
−3..+3, host bars 8–16) and `delayed_neighborhood` (offsets 17..23,
host bars 28–36), 7 blinded clips each. **The −3..+3 labels are pending
these auditions — nothing assumes they are negatives.**

**Phrase-scale trajectory probe** (`research/trajectories.py`): ordered
per-aligned-bar series per side (onset density, band energies, chroma,
harmonic-change, tension, novelty, repetition, crude
midband-salience/build/drop/cadence proxies) compared as *shapes*:
whole-span and local windowed correlation, complementarity index,
change-point co-occurrence within ±1 bar, foreground-density collision,
and localized conflict maxima (value + bar), not only span means.

**Stem-aware path** (`research/stems.py`): research instrumentation
only. External stems are data (user-provided role WAVs separated outside
the repo — no new dependency); `--pseudo` adds crude librosa HPSS
pseudo-stems with `pseudo_` provenance prefixes and deliberately no
vocal pseudo-stem. Measures vocal masking, bass interference, transient
reinforcement/flam, foreground competition; abstains where stems are
missing.

**Within-pair ranking evaluation** (`research/evaluation.py`): pairwise
preference accuracy, success ranks, top-3 recall, abstentions — both
directions always reported; only annotated labels are truth; hypothesis
labels enter only under an explicit flag that marks the whole report
provisional.

**Results on the real pair (labels still mostly ungrounded):** the
strict run (successes 0/20 vs the three user-attested negatives
17/18/19) shows five features at pairwise 1.0 in the lower-is-better
direction, but four of six comparisons are cross-region and ride
position-in-song drift; the one local contrast (20 vs 17/18/19, won by
`bar_energy_corr`) is 3 comparisons with an in-sample direction and
attested-not-auditioned negatives. The provisional run's top feature
(`novelty.peak_cooccurrence`, lower-better, 0.854) *inverts* the
intuitive structural story — a textbook witness-specific artifact,
promoted to nothing. The two successes still disagree in sign on
density agreement. Conclusion: the binding constraint is labels, not
features; the rendered blinded sessions are the next action, and all
metrics get recomputed after unsealing.

**Benchmark plan:** 10–15 pairs stratified by move family (4–5 overlay,
2–3 transition_blend, 2–3 rhythmic_graft, 2 hook_collision, 1–2
genre_contrast_blend), sourced from published mashup recipes over owned
recordings, discovery-proposed library pairs, and deliberately
incompatible controls; song-pair identity grouped; leave-one-pair-out
before any production proposal. Detail in
`docs/experiment-joint-registration-features.md`.

## The audition workbench (2026-07-11, third slice)

Browsing clip files and hand-editing responses.json was not a workable
research loop and would not scale to the benchmark, so the blinded
sessions now have a local web workbench (`research/workbench.py`,
`scripts/audition_workbench.py`): stdlib `http.server` only — no new
dependencies, no accounts/auth/cloud, loopback by default with `--lan`
for a phone on the local network. One blinded clip at a time with
play/pause/replay/prev/next, keyboard controls, and A/B comparison
against the immediately previous clip at the matched position; captures
the existing response fields (viable yes/no/unsure — multiple viable
allowed — the four 1–5 coherence/conflict ratings, confidence, notes);
autosaves atomically (temp file + os.replace under a lock) after every
tap; shows progress without offsets. The blind is enforced server-side:
`key.json` is never read before finalization and any request touching
it returns 403; no API payload contains an offset until finalized
(locked by tests at both the app and HTTP layers). Finalization refuses
incomplete sessions with the same validation `unseal` enforces, then
writes decoded `labels.json` + `ranking_refreshed.json` *beside* the
untouched sealed artifacts, and shows the by-offset judgment table plus
the refreshed strict ranking computed from this session's
blinded-audition labels (viable→success, no→near_offset_negative,
unsure→excluded). Corpus fixture updates remain a manual reviewed step.
12 new tests (292 total). Production scoring, ranking, gates, and
feature definitions untouched.

## First grounded blind labels: the witness fails in its own window (2026-07-14)

The `anchor_neighborhood_v2` session was auditioned blind and finalized.
The result is the most informative datum of the program so far, and it
is a *negative* one:

| offset | viable | rhythm | harmony | phrase/section | masking | conf |
|---|---|---|---|---|---|---|
| −3 | unsure | 5 | 5 | 2 | 3 | high |
| −2..+3 (all) | **no** | 5 | 5 | **1** | 3 | high |

Three observations, in decreasing order of confidence:

1. **Rhythm and harmony do not discriminate offsets — now confirmed by
   ear, not just by probe.** Every offset, witnessed or corrupted,
   scored 5/5 on rhythmic and harmonic coherence. This is the human
   counterpart of the probes' structural finding (whole-bar shifts
   preserve beat alignment; full-mix harmony is offset-insensitive on
   this material). Whatever separates a working registration from a
   corrupted one, it is not beat-level rhythm or aggregate harmony.
2. **Viability is window/arrangement-scoped, not registration-global.**
   The witnessed offset 0 itself was judged NOT viable (phrase/section
   1, high confidence) as a bare 8-bar overlay of the early region
   (host bars 8–16) — while the witnessed construction's conviction
   came from an *arrangement*: muted intro, an entrance placed at a
   cadential moment, and the chorus-2→final-chorus region. The corpus
   now records this as a conflict on record, and the schema lesson is
   explicit: labels must attach to (registration, window/arrangement),
   not to a registration alone. This also retroactively explains why
   ranking probes against registration-global labels found nothing
   coherent.
3. **The −3 "unsure" (phrase 2 vs 1 everywhere else) is a mild
   inversion** — the only clip the listener did not reject outright is
   a *corrupted* neighbor. n=1 judgment; noted, not interpreted.

Instrument caveat before treating phrase-1-everywhere as fact about the
overlay: a constant guest phrase-boundary extraction error (e.g. the
guest window starting mid-phrase in every clip due to a downbeat/bar
indexing fault) would produce exactly this all-offsets pattern. The
next session must include a **guest-only reference clip** so the
listener can hear whether the guest excerpt itself starts on a phrase
boundary. Next probes, in order: (a) guest-only reference + re-check;
(b) a window sweep for the anchor registration — same offsets, windows
in the witnessed convincing region (chorus 2 onward) — to test the
window-scoped-viability reading directly; (c) finish the
delayed-neighborhood session. The delayed session's key remains sealed.

## Second blind session: the gate's vindication and a viable off-class offset (2026-07-14)

`delayed_neighborhood_v2` (host bars 28–36) finalized blind:

| offset | viable | rhythm | harmony | phrase | conf |
|---|---|---|---|---|---|
| 17 | unsure | 5 | 5 | 3 | medium |
| **18** | **yes** | 5 | 5 | **4** | medium |
| 19 | no | 5 | 5 | 1 | high |
| 20 | unsure | 5 | 5 | 3 | medium |
| 21 | unsure | 5 | 5 | 3 | medium |
| 22 | no | 5 | 5 | 1 | high |
| 23 | no | 5 | 5 | 1 | high |

What this changes:

1. **The reverted phrase-class gate is now empirically refuted, not just
   methodologically suspect.** The one blind-viable registration in this
   window is offset 18 ≡ 2 (mod 4) — off the anchor's phrase class. The
   gate would have excluded the best offset. The revert kept it
   evaluable; the blind ear found it.
2. **Witness/attestation conflicts are now bidirectional.** Offset 18
   was attested (2026-07-11) as should-not-propose — blind ear says
   viable. Offset 20 was attested as the compatible family member —
   blind ear says unsure. Offset 19's attested negative is confirmed.
   Grounded labels supersede attestations, as directed; all conflicts
   are on record in the corpus rather than resolved away.
3. **The instrument-fault hypothesis from the anchor session is
   weakened.** Phrase scores vary by offset here (1..4) within one
   session — a constant guest phrase-boundary extraction error cannot
   produce that. The anchor window's flat phrase-1 more plausibly means
   bare early-region overlays genuinely fail there. A guest-only
   reference clip remains worth adding, but the phrase dimension is
   evidently measuring something real.
4. **Rhythm/harmony are again 5/5 at every offset** — third independent
   confirmation (span probe, trajectory probe, now two blind sessions)
   that beat-level rhythm and aggregate harmony carry no registration
   information on this pair. Phrase/section structure is the live
   dimension.
5. **The session's strict ranking (ten features at pairwise 1.0, rank 1)
   is in-sample noise and now demonstrably so:** several directions
   flipped relative to the earlier strict run on the same pair (e.g.
   `lf_interference` won as lower-better against the old labels and
   higher-better against these). Single-pair perfect accuracy carries no
   evidential weight — exactly why leave-one-pair-out across the
   benchmark is the bar.

Methodological consequence queued: probe features are currently
whole-overlap-span statistics while grounded labels are window-scoped —
the next probe iteration must compute features over the audited window
so evidence and truth share a scope. Then: guest-only reference clips,
and a window sweep for the anchor registration in the witnessed
convincing region (chorus 2 onward).
