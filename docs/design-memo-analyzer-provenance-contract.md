# Design memo: analyzer provenance contract

**Status: memo only. No code changes.** This defines the bar a *future*
production analyzer must clear before it may mark any `TrackAnalysis`
evidence as `MEASURED` — written now, before analyzers exist, so the
contract is fixed before there is any incentive to bend it. It extends the
existing `AnalysisProvenance` seam (`STUB`/`MEASURED`, single field, default
`STUB`; `analyze_track` sets `STUB`) and the verdict's confidence gate
(`assess_compatibility` requires *both* tracks `MEASURED` for a confident
`COMPATIBLE`/`UNLIKELY`).

Related: `docs/compatibility-verdict.md` (the verdict this gates),
`docs/fixture-planning-matrix.md` (per-move evidence requirements),
`docs/tempo-eval.md` (why backend confidence is not truth).

## The one principle everything follows from

**Provenance and confidence are orthogonal axes, and `MEASURED` is about
provenance, never confidence.**

- **Provenance** = *how the value was produced*. Was it read from the audio
  signal by a trustworthy method, asserted by a human, or fabricated by a
  placeholder?
- **Confidence** = *how internally consistent the method's own answer was*
  (autocorrelation strength, frame agreement). It is **not** a calibrated
  probability and **not** evidence of provenance. The stub tempo estimator
  already emits confidences of 0.6/0.25/0.15; `librosa` returned **123 BPM at
  confidence 0.92 on pink noise** (a signal with no pulse). A high number
  proves nothing about whether the value reflects reality.

Therefore: **no analyzer may set `MEASURED` because a confidence is high.**
`MEASURED` is earned by *method and input*, and is then further qualified by
confidence/ambiguity inside the verdict. Collapsing the two axes is the
central laundering risk this contract exists to prevent.

## Decision 1 — Provenance becomes field-level, not one enum per TrackAnalysis

**Recommendation: adopt per-dimension provenance.** The single
`TrackAnalysis.provenance` enum is all-or-nothing, and that is wrong in both
directions:

- If whole-analysis `MEASURED` requires *every* field to be real, a track
  with a real tempo backend but a stub key can never be `MEASURED`, so no
  move can ever be confident — even `transition_blend`, which does not
  decide on key. Real progress is under-credited.
- If whole-analysis `MEASURED` is set once *some* field is real, the verdict
  then trusts the still-stub fields (a filename-hash key scored as a real
  harmonic relation). That is laundering.

Field-level provenance resolves both and is exactly what the move-relative
verdict needs: **a move's confident verdict is gated on the provenance of
the dimensions that move actually decides on.**

Recommended shape (illustrative, not prescriptive code):

- Each analysis dimension carries a `ProvenanceRecord { tier, method,
  confidence, note }`, where `tier ∈ {STUB, USER_ASSERTED, MEASURED,
  UNAVAILABLE}` (see Decisions 2 and the failure section) and `method` names
  the backend/estimator (or `"stub"`). `confidence` lives here too, kept
  deliberately separate from `tier`.
- Dimensions that get their own record: `tempo`, `beatgrid`, `key`,
  `sections`, `stems`, `role`. (`tempo` and `beatgrid` are **separate** —
  see the ledger.)
- `TrackAnalysis.provenance` (the current enum) becomes a *derived* view for
  display/back-compat: the minimum tier across whichever dimensions a caller
  names — never a stored source of truth. No analyzer writes it directly.

Migration is safe to specify now: nothing sets `MEASURED` today, so
introducing per-dimension records later breaks no current behavior; the
verdict's `both-MEASURED` check simply becomes `both-MEASURED on each
deciding dimension`.

## Decision 2 — Manual overrides get their own tier: `USER_ASSERTED`

**Recommendation: yes — a third tier, distinct from `STUB` and `MEASURED`.**

Today `apply_override` preserves provenance via `replace()`, so a `STUB`
override stays `STUB` (locked by
`test_manual_override_does_not_launder_stub_provenance_into_confidence`).
That is safe but blunt: a user tapping the true BPM is neither a fabricated
stub nor a machine measurement — it is a *human assertion*, and conflating it
with either is dishonest.

- Overriding a field sets that field's tier to **`USER_ASSERTED`** and its
  `method` to `"manual_override"`. It never touches other fields' tiers
  (field-level, per Decision 1), and it **never** promotes a field to
  `MEASURED`.
- **Policy on confidence: `USER_ASSERTED` does not satisfy the confident-verdict
  gate.** A dimension that is only user-asserted lifts that dimension out of
  `STUB` (so an override can, e.g., resolve an ambiguity or supply a missing
  value and move a verdict off `UNCERTAIN`), but a `COMPATIBLE`/`UNLIKELY`
  verdict may not rest on user-asserted deciding evidence. Rationale: the
  tool must not echo the user's own inputs back as *its* confident,
  measurement-based judgment — "you told me the BPMs match, therefore I
  confidently judge them compatible" is circular. Such a pairing caps at
  `MAYBE`, and the evidence item must attribute the dimension ("tempo: from
  your override, not measured").
- This is a policy lever, not a law of physics: a future product could let
  trusted ground-truth override satisfy confidence, but only as an explicit
  opt-in that still *attributes* every user-supplied dimension in the
  verdict. The safe default is the conservative one above.

## The per-dimension `MEASURED` bar

A production analyzer may set a dimension to `MEASURED` only when **all** of
that dimension's row holds. "Decoded real audio" everywhere means actual PCM
samples from the file — never the filename-seeded `stable_seed` path.

| Dimension | `MEASURED` requires | Explicitly **not** sufficient |
| :-- | :-- | :-- |
| **tempo / BPM** | decoded audio; a registered non-stub backend run on the samples; output is a `TempoCandidate` set with octave alternatives represented (not one scalar). | a high self-consistency confidence; a global BPM alone with no octave alternatives. |
| **beatgrid / pulse** | actual per-beat + downbeat positions over time with a stable meter. A **separate** dimension from global tempo. | a global BPM being `MEASURED`. Tempo says "how fast," beatgrid says "where the beats are"; one does not imply the other. |
| **key** | decoded audio; a real key/chroma estimator; value carries a mode and a modal-ambiguity signal. | a stub key of any confidence; a global key standing in for time-varying chords. |
| **section structure** | decoded audio; real structural segmentation; **per-boundary** confidence that honestly reflects boundary drift. | the deterministic stub layout, even at moderate confidence. |
| **stems / source separation** | a real separation model run, producing stems with a separation-quality (e.g. SDR) estimate. | assuming stems exist; a bleed-heavy separation reported as clean. |
| **role / lead-bed split** | stem + vocal-activity evidence that the *asserted* role actually holds (A has an isolable vocal, B is vocal-free for an overlay). | a caller-asserted `VOCAL`/`INSTRUMENTAL` label. Absent stems, a role is at best `USER_ASSERTED`, never `MEASURED`. |

Collision (vocal/bass overlap) and arrangement contrast are **downstream of
stems**: they cannot be `MEASURED` until `stems` is, and until then
`CollisionProfile.measured=False` must stand (it already does).

## Failure vs. ambiguity — two different states, only one blocks

- **Measurement failed** (undecodable file, backend error, no pulse found):
  the dimension is **not** `MEASURED`. Use `UNAVAILABLE` (attempted, failed)
  or leave it `STUB` (never attempted) — but a backend **must not** fall back
  to a stub value and tag it `MEASURED`. Failure is the single most dangerous
  path (see false-confidence path #2).
- **Measurement succeeded but is ambiguous** (two competing tempo readings;
  librosa's confident-but-wrong pink-noise pulse): the dimension **is**
  `MEASURED`, and the *verdict's existing ambiguity/override gates* abstain to
  `UNCERTAIN`. Provenance records that a real method ran; the verdict decides
  it cannot commit. Do not conflate "we could not measure" with "we measured
  and it is unclear."

## Decision 3 — Minimum evidence for a confident compatibility verdict

Provenance is a **necessary, not sufficient** gate. It stacks *under* the
existing verdict gates (support status, role premise, ambiguity, override
dependence). A `COMPATIBLE`/`UNLIKELY` verdict requires **all** of:

1. the move is `SUPPORTED` (partial moves stay capped at `MAYBE` regardless
   of provenance; out-of-scope stays `UNCERTAIN`);
2. no ambiguity/override/role-premise gate fires (current behavior);
3. **every dimension the move decides on is `MEASURED` on *both* tracks** —
   not `STUB`, not `USER_ASSERTED`, not `UNAVAILABLE`.

Per-move deciding dimensions (which must be `MEASURED` for confidence):

| Move | Deciding dimensions that must be `MEASURED` for a confident verdict | Ceiling without them |
| :-- | :-- | :-- |
| vocal_over_instrumental_overlay | tempo, key, sections, beatgrid, **stems** (→ role + collision) | `MAYBE`. Without stems the spectral-masking failure mode is unassessable, so a masking-aware `COMPATIBLE` is not earnable even with tempo/key/section measured. |
| transition_blend | tempo, sections (beatgrid for a lock claim); not role-gated | `MAYBE` |
| hook_collision / rhythmic_graft / genre_contrast_blend | **n/a — capped at `MAYBE`** until move-specific analyzers exist (hook window/motif; transient+swing; contrast model). Provenance cannot lift the partial cap. | `MAYBE` |
| harmonic_reinterpretation / lyrical / sample_collage | **n/a** — out of scope; `UNCERTAIN`, no score. | `UNCERTAIN` |

The general rule to encode: *a dimension may contribute to confidence only if
its `MEASURED` bar is met on both tracks; a move may be confident only if
every dimension it decides on qualifies and no shape-gate fires.*

## Decision 4 — Tests that must fail if a backend launders weak evidence

The contract is only real if these guard tests exist and fail on violation.
They are **specified here, to be written with the first analyzer PR** (not
now — no analyzer exists to exercise them):

1. **Confidence is not provenance.** A value of stub origin with confidence
   0.99 must resolve to tier `STUB`; nothing may derive `MEASURED` from a
   confidence field.
2. **No decoded audio → no `MEASURED`.** An analyzer that did not decode PCM
   (filename-only, or decode failed) must never emit `MEASURED`.
3. **Failed measurement does not fall through.** A backend error / "no pulse"
   must leave the dimension `UNAVAILABLE`/`STUB`, never a stub value tagged
   `MEASURED`.
4. **No partial-field promotion.** `tempo=MEASURED` with `key=STUB` must not
   yield a whole-analysis `MEASURED`; a move that decides on key cannot reach
   `COMPATIBLE`.
5. **Overrides do not launder.** An override sets `USER_ASSERTED`, never
   `MEASURED`; a verdict resting on a user-asserted deciding dimension caps at
   `MAYBE` with attribution. (Extends the existing override test.)
6. **Beatgrid is independent of tempo.** `tempo=MEASURED`,
   `beatgrid=STUB/absent` must not license a phrase-lock ("within ½ beat")
   claim or an overlay `COMPATIBLE`.
7. **Roles are not measured without stems.** Asserted roles with no stem
   evidence stay `USER_ASSERTED`; the stem-dependent overlay confidence tier
   stays out of reach.
8. **Stub-floor invariant (umbrella).** For every move, if *any* deciding
   dimension on either track is not `MEASURED`, the verdict is not confident.
   (The field-level generalization of today's
   `test_stub_provenance_is_never_confident_for_any_move`.)

## Explicit false-confidence paths this contract blocks

1. **Confidence-as-provenance.** A backend reports 123 BPM @ 0.92 on pink
   noise; inferring `MEASURED` from the 0.92 would feed a confident verdict on
   a pulseless signal. *Blocked by:* provenance set by method+input, not
   confidence (principle + test 1); ambiguity gate still abstains.
2. **Silent stub fallback tagged `MEASURED`.** A real tempo backend is wired,
   but on decode failure `analyze_track` falls back to the filename-seeded
   BPM and forgets to downgrade provenance → a fabricated BPM marked
   `MEASURED` → `COMPATIBLE`. *Blocked by:* failure clears `MEASURED` (test 2,
   3).
3. **Partial-analysis promotion.** Tempo backend lands; someone flips the
   whole-analysis enum to `MEASURED` for convenience while key/sections are
   stubs → the verdict scores a filename-hash key as a real harmonic relation
   → `COMPATIBLE`. *Blocked by:* field-level provenance; harmonic gated on
   `key` provenance (Decision 1, test 4).
4. **User-input echo.** A user overrides both tracks' BPM and key to match,
   and the tool returns `COMPATIBLE` — which the user reads as the tool having
   *measured and validated* the audio, when it only did arithmetic on their
   claims. *Blocked by:* `USER_ASSERTED ≠ MEASURED` for confidence, with
   attribution (Decision 2, test 5).
5. **Role assertion as measurement.** A/B labeled vocal/instrumental with no
   stems; overlay returns `COMPATIBLE` claiming a clean layering, though B may
   carry masking vocals never checked. *Blocked by:* role/collision provenance
   requires stems; overlay capped below the masking-aware tier without them
   (bar + test 7).
6. **Beatgrid overclaim.** Global tempo measured → the report asserts phrase
   boundaries aligned "within ½ beat," implying a downbeat lock that no
   beatgrid established. *Blocked by:* beatgrid is a distinct dimension (bar +
   test 6).
7. **Backend self-declaration.** A newly registered backend returns a trivial
   heuristic (or constants) and marks itself `MEASURED`. *Blocked by:*
   `MEASURED` requires meeting the per-dimension bar (decoded audio, method
   identity, ambiguity representation), enforced by tests 1–3, not by the
   backend's say-so.

## What this memo does not decide

- The concrete Python shape of `ProvenanceRecord` and how it attaches to
  `TrackAnalysis`/`TempoCandidate`/`Section` (a follow-up implementation
  design, when the first real analyzer is proposed).
- Whether a *disclosed* "structural `COMPATIBLE`" tier (tempo/key/section
  measured, stems absent) should exist for overlay, or whether such pairings
  stay `MAYBE`. This memo recommends `MAYBE` as the safe default and flags the
  tier as an explicit future policy choice.
- Any calibration of backend confidence into a real probability — out of
  scope and, per `docs/tempo-eval.md`, not currently available.
