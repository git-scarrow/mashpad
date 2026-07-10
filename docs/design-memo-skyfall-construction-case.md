# Design memo: the Skyfall / In the End construction case

**Status:** research spike, parallel to the main roadmap. Nothing here
changes production scoring weights, verdict thresholds, provenance
semantics, or analyzer qualification gates.

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

- Skyfall as host, read at **~75 BPM — not the doubled tempo djay
  initially inferred**. (A live instance of the octave-ambiguity failure
  mode the production verdict layer abstains on; the human override to
  ~75 is exactly the `USER_ASSERTED` path the override model describes.)
- Both decks synchronized at **74 BPM**; In the End slowed substantially
  from its source tempo — resolving the earlier open question: the tempo
  treatment is a large single slow-down of the guest, not a half/double
  reading or re-phrasing.
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
   shared grid: host ~75 BPM (hypothesis, session-observed), shared grid
   74 BPM (annotated: human-auditioned session setting), guest stretch
   ratio 74/source (bounds 0.67–0.74 until the source BPM is measured),
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
