# Fixture-planning matrix: what v0 may responsibly judge

This matrix converts the mashup-move research into a decision about **what
v0 is allowed to be confident about, what must return `UNCERTAIN`, and
which future analyzers are the precondition for confidence.** It is a
planning artifact for fixtures and abstention behavior — it adds no
analyzers, weights, or scoring changes.

Sources:
- `docs/Mashup Compatibility Tool Taxonomy.md` — the research report. Its
  two mapping tables are load-bearing here: move → required criteria
  ("Target BPM Window / Max Pitch Shift / Downbeat & Boundary Precision /
  Required MIR Source Separation") and feature → reliability tier
  (Category 1 reliable / 2 error-prone / 3 subjective).
- `docs/mashup-move-taxonomy.md` — the operational condensation, including
  per-move "known failure modes."
- `docs/compatibility-verdict.md` — the verdict semantics this matrix
  targets (`mashpad.scoring.verdict.assess_compatibility`).

The current-behavior claims below are executable, not aspirational: they
are locked by `tests/test_move_abstention.py`.

## The v0 evidence ledger

What each evidence dimension needs, and what v0 actually has. **Everything
v0 produces is `STUB` provenance** (seeded from the file name, not the
audio; see `AnalysisProvenance`), which is why v0 can never reach a
*confident* verdict — see "The confidence gate" below.

| Evidence dimension | Research reliability tier | v0 status | Producer / gap |
| :-- | :-- | :-- | :-- |
| Global tempo (BPM) | Cat 1 (reliable) | **stub only** | `analysis/tempo.py` (filename-seeded). Real backends exist (`tempo_backend.py`) but are **not** wired into `analyze_track`, and none set `MEASURED`. |
| Beat / downbeat grid | Cat 1 | **absent** | No beat-grid representation exists (`ManualOverride.DOWNBEAT` raises `NotImplementedError`). |
| Global key | Cat 1 (moderate) | **stub only** | `analysis/harmony.py` (filename-seeded). |
| Stem separation (vocal/drums/bass/other) | Cat 1 (Demucs) | **absent** | `analysis/stems.py` is an explicit `NotImplementedError` seam. Guardrail: no stems in v0. |
| Phrase / section boundaries | Cat 2 (error-prone) | **stub only, low-confidence** | `analysis/sections.py` (deterministic layout, confidence ~0.45–0.55). |
| Time-varying chords | Cat 2 | **absent** | Only a single global key stub exists. |
| Vocal presence / speechiness | Cat 2 | **absent** | No vocal-activity signal. |
| Swing / micro-timing groove | Cat 3 (subjective) | **absent** | No transient/swing analysis. |
| Semantic / lyrical contrast | Cat 3 | **absent** | No lyric transcription or NLP. |
| Vocal intelligibility under masking | Cat 3 | **absent** | No psychoacoustic model. |
| Arrangement contrast (harmonic density) | — | **caller-supplied only** | `arrangement_contrast_score.py` is real math but no analyzer estimates its input; default `None`. |
| Vocal/bass collision | — | **caller-supplied only** | `collision_score.py` real math; `CollisionProfile.measured=False` by default (needs stems). |

## The confidence gate (why v0 abstains so often)

`assess_compatibility` will only emit a *confident* verdict — `COMPATIBLE`
or `UNLIKELY` — when **both** tracks carry `AnalysisProvenance.MEASURED`.
No v0 analyzer sets `MEASURED`; `analyze_track` sets `STUB` explicitly.
Therefore, in production today:

- **supported / partial moves → `MAYBE`** (a hypothesis, never a confident yes),
- **out-of-scope moves → `UNCERTAIN`** (not scored at all),
- and additionally, role-dependent moves with an unestablished role split → `UNCERTAIN`.

The `COMPATIBLE`/`UNLIKELY` columns in the per-move tables below are what
would become *reachable* once real analyzers set `MEASURED` — they are the
target, and they are gated, not current behavior.

Observed verdicts for a clean, agreeable pair (A=B=120 BPM, C major,
confident sections), by provenance and roles:

| Move type | support | role-gated? | STUB, roles set | MEASURED, roles set | MEASURED, both FULL_MIX |
| :-- | :-- | :-- | :-- | :-- | :-- |
| vocal_over_instrumental_overlay | supported | yes | `MAYBE` | `COMPATIBLE` | `UNCERTAIN` |
| transition_blend | supported | no | `MAYBE` | `COMPATIBLE` | `COMPATIBLE` |
| hook_collision | partial | yes | `MAYBE` | `MAYBE` (capped) | `UNCERTAIN` |
| rhythmic_graft | partial | yes | `MAYBE` | `MAYBE` (capped) | `UNCERTAIN` |
| genre_contrast_blend | partial | **no** | `MAYBE` | `MAYBE` (capped) | `MAYBE` |
| harmonic_reinterpretation | out_of_scope | — | `UNCERTAIN` | `UNCERTAIN` | `UNCERTAIN` |
| lyrical_conceptual_juxtaposition | out_of_scope | — | `UNCERTAIN` | `UNCERTAIN` | `UNCERTAIN` |
| sample_collage | out_of_scope | — | `UNCERTAIN` | `UNCERTAIN` | `UNCERTAIN` |

**Documented modeling gap (not changed here):** `genre_contrast_blend`'s
definition is a vocal/melodic stem over a contrasting backing — it implies
a vocal/instrumental split — yet it is **not** in
`verdict.ROLE_DEPENDENT_MOVES`, so a `FULL_MIX`/`FULL_MIX` genre-contrast
pairing does **not** abstain on the role premise the way an overlay does.
`transition_blend` is correctly not role-gated ("full mix is usually
fine"). Whether `genre_contrast_blend` should join the role-gated set is a
future decision; this pass records the current behavior rather than
altering it.

---

## Per-move matrix

Each block: **required evidence** (research) · **available in v0** ·
**missing** · **expected v0 verdict** · **false-positive risks** ·
**fixture cases needed**.

### vocal_over_instrumental_overlay — *supported, role-gated*

- **Required evidence:** tempo within ~±6% (transient-blur limit); high-purity 2-stem vocal isolation; downbeat-to-downbeat lock with phrase boundaries matched within ½ beat; Camelot-compatible keys or vocal pitch-shift ≤ ~2 semitones; **harmonic-complexity contrast** (dense vocal over sparse backing); sparse instrumental midrange so the vocal band is unmasked; no sub-bass/kick collision; matched groove feel.
- **Available in v0:** stub BPM, stub key, stub sections (low confidence), asserted roles. Tempo half/double-aware; key circle-of-fifths; phrase = section-confidence proxy.
- **Missing:** real tempo/key/section (MEASURED); stems (masking + collision are unmeasurable without them); beat/downbeat grid; arrangement-contrast density; groove/swing.
- **Expected v0 verdict:** `MAYBE` with an asserted vocal/instrumental split; `UNCERTAIN` if the split is not supplied (`FULL_MIX`). Never `COMPATIBLE` in v0 (stub provenance).
- **False-positive risks:** octave tempo error read as a clean match; a modal song misread as major/minor; **endorsing a spectrally-masking pair** (dense backing) that v0 literally cannot see (no stems); a user reading the still-computed `composite` as the answer.
- **Fixture cases needed** *(all present in `tests/test_verdict.py`)*: clean stub → `MAYBE` (confidence withheld though composite is STRONG); measured clean → `COMPATIBLE`; `FULL_MIX` roles → `UNCERTAIN`; ambiguous BPM → `UNCERTAIN`; low-confidence tempo override required → `UNCERTAIN`.

### transition_blend — *supported (basic only), not role-gated*

- **Required evidence:** tempo + phrase alignment at the outro→intro seam; progressive energy-curve handoff; the 16–32 bar transition window evaluated **in isolation**; identical/adjacent Camelot key.
- **Available in v0:** stub tempo + phrase over the *whole track*; stub key (less load-bearing here).
- **Missing:** energy-curve modeling; windowed (outro/intro) scoring; beat grid; crossfade suggestion.
- **Expected v0 verdict:** `MAYBE` (stub). `FULL_MIX` is acceptable (not role-gated), so it does not abstain on roles.
- **False-positive risks:** whole-track scoring endorses a pair that would not transition locally, or rejects one that would — the window is never isolated.
- **Fixture cases needed:** clean stub → `MAYBE`; measured clean → `COMPATIBLE` (reachable because non-role-gated); a wide-tempo pair → not confident (leaning-no on stub is `UNCERTAIN`, not a fabricated low score).

### hook_collision — *partial, role-gated*

- **Required evidence:** motivic/hook similarity; isolated hook stems from both tracks; a 2–4 bar scoring window; phase-locked downbeats; tempo matched exactly at beat level.
- **Available in v0:** the three core dimensions over the *whole track* — no hook stem, no short window, no motivic signal.
- **Missing:** hook-stem extraction; short-window (2–4 bar) granularity; motivic-similarity model; beat grid.
- **Expected v0 verdict:** `MAYBE`, **capped below `COMPATIBLE` even when measured** (partial support). `FULL_MIX` → `UNCERTAIN`.
- **False-positive risks:** a high track-level score approves a pairing whose hooks never actually coincide (the operational taxonomy's stated failure mode).
- **Fixture cases needed:** measured clean → `MAYBE` (capped, `move_support` conditional evidence present); `FULL_MIX` → `UNCERTAIN`.

### rhythmic_graft — *partial, role-gated*

- **Required evidence:** isolated drum/percussion stem; transient-level kick/snare onset alignment to B's beat grid; matched swing/shuffle feel; BPM within stretch limits.
- **Available in v0:** stub tempo + phrase. Harmonic fit is a **poor proxy** (not a harmonic move).
- **Missing:** drum-stem separation; transient-onset alignment; swing-ratio analysis (Category 3 — may never be reliably automatable); beat grid.
- **Expected v0 verdict:** `MAYBE`, capped below `COMPATIBLE`. `FULL_MIX` → `UNCERTAIN`.
- **False-positive risks:** BPM matched but groove mismatched (straight vs. swung) → numerically "in time," perceptually unstable, undetectable without swing analysis.
- **Fixture cases needed:** measured clean → `MAYBE` (capped); `FULL_MIX` → `UNCERTAIN`.

### genre_contrast_blend — *partial, not role-gated (see gap above)*

- **Required evidence:** strict tempo/phrase congruence *despite* stylistic friction; Camelot key matching; 2/4-stem separation to minimize bleed; **an aesthetic judgment of whether the contrast is good** (Category 3 — subjective, left to the user).
- **Available in v0:** stub tempo/key/phrase; no contrast-quality model.
- **Missing:** a "is this clash interesting vs. bad" model (may stay human-only); stems; role gating.
- **Expected v0 verdict:** `MAYBE`, capped. Currently does **not** abstain on `FULL_MIX` (documented gap).
- **False-positive risks:** two directions. (1) A naive similarity scorer *rejects* the very pairings that make this move interesting — a false **negative** the operational taxonomy warns against; v0 avoids this only because it does not model contrast at all. (2) A `MAYBE` read as an endorsement of the contrast quality it never assessed.
- **Fixture cases needed:** measured clean → `MAYBE` (not `COMPATIBLE`); (future, if role-gated) `FULL_MIX` → `UNCERTAIN`.

### harmonic_reinterpretation — *out of scope*

- **Required evidence:** pitch-shift synthesis; a vocal-safe-shift judgment (~2 semitones before "chipmunk"); extreme vocal isolation to avoid key bleed; full-length chord-boundary alignment.
- **Available in v0:** none relevant. No audio synthesis exists.
- **Missing:** everything — this is a synthesis move, not a measurement move.
- **Expected v0 verdict:** `UNCERTAIN` (abstain); `evaluate_move` returns `scores=None`.
- **False-positive risks:** the sharpest one in the whole taxonomy — reading `harmonic_score`'s circle-of-fifths *closeness* as a reinterpretation-viability proxy. It measures "are these already close," which is close to the **opposite** of the question. v0 avoids this by returning no score.
- **Fixture cases needed:** any inputs → `UNCERTAIN` with `scores=None`.

### lyrical_conceptual_juxtaposition — *out of scope*

- **Required evidence:** lyric transcription + semantic/NLP thematic modeling; clean vocal extraction; phrase-level alternation.
- **Available in v0:** none. "v0 treats vocals strictly as structured melodic waveforms."
- **Missing:** all lyric/semantic data.
- **Expected v0 verdict:** `UNCERTAIN`; `scores=None`.
- **False-positive risks:** presenting *any* acoustic score as if it spoke to lyrical/thematic fit.
- **Fixture cases needed:** any inputs → `UNCERTAIN` with `scores=None`.

### sample_collage — *out of scope*

- **Required evidence:** N-source fragmented micro-stems; micro-transient onset alignment; a data model beyond the two-track pair.
- **Available in v0:** none — the tool models exactly two tracks with one role each.
- **Missing:** the N-source model itself; pairwise-combinatorics compute (excluded by design as prohibitive for local-first v0).
- **Expected v0 verdict:** `UNCERTAIN`; `scores=None`.
- **False-positive risks:** implying a two-track compatibility number says anything about an N-fragment collage.
- **Fixture cases needed:** any inputs → `UNCERTAIN` with `scores=None`.

---

## Analyzers required before confidence is allowed

Ordered by what each unlocks. Nothing here is implemented in this pass.

1. **Any confident verdict at all** requires real tempo + key + section
   analyzers wired into `analyze_track` and setting
   `AnalysisProvenance.MEASURED`. Until then every supported/partial move
   is capped at `MAYBE`. (Tempo backends exist but are unwired; key and
   section are stubs.)
2. **Responsible `COMPATIBLE` for `vocal_over_instrumental_overlay`** additionally
   needs stem separation (to measure vocal/bass collision and midrange
   masking) and a beat/downbeat grid (phrase-boundary lock within ½ beat).
   Without these, "measured + clean" is *structurally* compatible but blind
   to the spectral-masking failure mode.
3. **Promoting the PARTIAL moves out of the `MAYBE` cap:**
   - `hook_collision` → hook-stem extraction + 2–4 bar windowed scoring + motivic-similarity signal.
   - `rhythmic_graft` → drum-stem separation + transient-onset alignment + swing-ratio analysis (Category 3; may remain a manual override).
   - `genre_contrast_blend` → an aesthetic-contrast model (Category 3; likely stays a human judgment) **and** a decision on role-gating.
4. **The out-of-scope moves** need capabilities outside the current data
   model: pitch-shift synthesis (`harmonic_reinterpretation`), lyric
   transcription + NLP (`lyrical_conceptual_juxtaposition`), and an
   N-source collage model (`sample_collage`). These remain `UNCERTAIN` by
   design, not by omission.

## Current abstention behavior is test-locked

`tests/test_move_abstention.py` encodes the *current* v0 behavior in this
matrix (it asserts abstention/confidence-withholding only — it does not
assert any composite band, and tunes nothing):

- every out-of-scope move → `UNCERTAIN` with `scores=None`;
- every role-gated move with `FULL_MIX`/`FULL_MIX` → `UNCERTAIN` (missing role premise), even with MEASURED provenance;
- every partial move (measured, clean, roles set) → `MAYBE`, never `COMPATIBLE`;
- **every** move type, on `STUB` provenance, is non-confident (never `COMPATIBLE`/`UNLIKELY`).
