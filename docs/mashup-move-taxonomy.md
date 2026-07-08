# Mashup move taxonomy

A mashup candidate is not "Track A + Track B." It is **Track A in a role
over Track B in another role, using a specific move type.** The move type
determines which stems matter, what structural unit gets aligned, and
which score dimensions are even meaningful for the pairing.

This taxonomy is derived from `docs/Mashup Compatibility Tool Taxonomy.md`
(the uploaded research report), condensed to what's operationally
relevant for this codebase. See that report for full citations and the
underlying music-theory/MIR literature.

Each move type below is implemented (or not) in `MashupMoveType` /
`MOVE_SUPPORT` in `src/mashpad/models.py`. **v0 status** here must match
that table — if you change support status in one place, change it in the
other.

---

## vocal_over_instrumental_overlay

- **Definition:** The isolated vocal of Track A is layered over the full
  instrumental backing of Track B (or vice versa). The canonical mashup
  move — what most people mean by "mashup."
- **Source roles/stems:** Track A = `vocal` role (isolated vocal stem),
  Track B = `instrumental` role (full backing, ideally vocal-free).
- **Typical structural unit:** Long blocks — a complete verse or chorus.
- **Alignment objective:** Exact macro-structure and phrase-boundary
  alignment; downbeat-to-downbeat lock.
- **v0 status: supported.** This is the default move type assumed by the
  CLI when no explicit move/role is given.
- **Measurable criteria (v0):** tempo compatibility (`tempo_score.py`,
  half/double-aware), harmonic compatibility (`harmonic_score.py`,
  circle-of-fifths relation), phrase fit (`phrase_score.py`, section
  boundary confidence). Arrangement contrast and vocal/bass collision are
  modeled (`CompatibilityProfile`, `collision_score.py`,
  `arrangement_contrast_score.py`) but only computed when the caller
  supplies real stem-derived numbers — no stub estimates them yet, so
  v0 reports these as "not measured" rather than guessing.
- **Known failure modes:** octave error on tempo detection (half/double
  BPM misread as unrelated); key detector confusing a modal song for
  major/minor; vocal stem bleed making collision penalties unreliable
  once stems exist; forcing a match on two tracks that are dissonant by
  design (over-conservative false rejection).
- **Required manual overrides:** BPM half/double correction, key
  override, downbeat nudge, phrase boundary drag, stem gain/mute (once
  stems exist). See `ManualOverride` in `models.py`.

## hook_collision

- **Definition:** Two recognizable hooks (melodic or vocal) from both
  tracks are layered or rapidly alternated over a short window, aiming
  for immediate listener recognition of both sources at once.
- **Source roles/stems:** Recognizable hook stems from both A and B —
  not a strict vocal/instrumental split; both tracks can contribute
  melodic or vocal material simultaneously.
- **Typical structural unit:** Short micro-segments, 2-4 bars.
- **Alignment objective:** Motivic/wordplay alignment at the phrase or
  sub-phrase level, phase-locked downbeats over a narrow window.
- **v0 status: partial.** The generic tempo/harmonic/phrase dimensions
  still run and produce a real score — this move type is *not* silently
  scored as if it were a failed vocal-over-instrumental overlay. What's
  missing is hook-specific logic: there's no isolated "hook" stem, no
  short-window (2-4 bar) scoring granularity, and no motivic-similarity
  signal. The composite score for this move type should be read as "are
  these two tracks generically compatible," not "will this specific hook
  collision land."
- **Measurable criteria (v0):** same three core dimensions as
  vocal_over_instrumental_overlay, evaluated over the whole track rather
  than a hook-length window.
- **Known failure modes:** scoring at track-level instead of hook-level
  can approve a pairing whose hooks don't actually coincide, or reject a
  pairing whose hooks would fit even though the rest of the tracks don't.
- **Required manual overrides:** phrase boundary adjustment is the most
  load-bearing override here (to mark where each hook actually starts),
  plus BPM/key overrides as usual.

## rhythmic_graft

- **Definition:** The isolated drum/percussion stem of Track A drives the
  rhythm under the harmonic/melodic stems of Track B, transplanting a
  groove without disturbing B's melodic content.
- **Source roles/stems:** Track A = `drums` (not yet a modeled
  `TrackRole` value — drum-stem-specific roles are out of scope until
  stem separation exists), Track B = harmonic backing.
- **Typical structural unit:** Continuous looping/transient-heavy
  regions.
- **Alignment objective:** Transient-level alignment of kick/snare onsets
  to B's beat grid, not just BPM matching.
- **v0 status: partial.** Tempo/harmonic/phrase dimensions run and score
  honestly, but nothing here evaluates transient alignment or groove
  (swing/shuffle feel) — the report explicitly puts rhythmic swing ratio
  in "heavy compute or highly subjective," out of scope for v0.
- **Measurable criteria (v0):** tempo and phrase fit only; harmonic fit
  is a poor proxy here since it's not really a harmonic move.
- **Known failure modes:** matching BPM without matching groove feel
  (straight vs. swung) produces a mix that's numerically "in time" but
  perceptually unstable — not detectable without swing-ratio analysis.
- **Required manual overrides:** BPM correction, downbeat nudge (to fix
  transient/phase-shift errors specifically).

## genre_contrast_blend

- **Definition:** A vocal/melodic stem from one style is layered over a
  backing track from a deliberately contrasting style, using the clash
  itself as the artistic point.
- **Source roles/stems:** Vocal/melodic stem of style A, backing track of
  style B.
- **Typical structural unit:** Long parallel sections.
- **Alignment objective:** Strict tempo/phrase congruence *despite* high
  timbral/stylistic friction — the friction is a feature, not something
  to be scored down.
- **v0 status: partial.** This is a direct case of the "heuristic and
  aesthetic failure mode" the report calls out: a naive similarity-based
  scorer would penalize exactly the pairings that make this move type
  interesting. v0 still computes tempo/harmonic/phrase, but doesn't
  attempt to model "is this contrast good or just bad" — that judgment
  is left entirely to the user.
- **Measurable criteria (v0):** tempo and phrase fit are still meaningful
  (you still need the beats to line up); harmonic fit is reported but
  should be read loosely for this move type.
- **Known failure modes:** an over-engineered model rejecting a
  creatively strong pairing because it fails conservative acoustic
  similarity metrics.
- **Required manual overrides:** all of them are relevant; this move
  type leans hardest on the user's ear over the score.

## transition_blend

- **Definition:** Overlapping intros/outros/percussive transitions from
  both tracks create a progressive structural handoff from one song to
  the other.
- **Source roles/stems:** Outro material of Track A, intro material of
  Track B (or reversed), full mix is usually fine — this is closer to DJ
  phrasing/mixing than a stem-level overlay.
- **Typical structural unit:** Extended transition window, 16-32 bars.
- **Alignment objective:** Progressive tempo/energy handoff with aligned
  phrase boundaries at the outro-to-intro seam.
- **v0 status: supported, but basic only.** The existing tempo + phrase
  scoring naturally supports evaluating "do these two tracks' tempos and
  section boundaries line up," which is most of what a basic transition
  blend needs. What's *not* supported: energy-curve modeling, crossfade
  curve suggestions, or evaluating the transition window in isolation
  from the rest of the track. Treat a "supported" transition_blend score
  as "these two tracks could plausibly transition," not "here is where
  to cut."
- **Measurable criteria (v0):** tempo fit, phrase fit. Harmonic fit is
  reported but less load-bearing for a transition than for an overlay.
- **Known failure modes:** scoring the whole track instead of just the
  outro/intro windows can miss a transition that would work locally even
  if the tracks are a poor overall match, or vice versa.
- **Required manual overrides:** phrase boundary adjustment (to mark the
  actual transition window), BPM correction for tempo ramps.

## harmonic_reinterpretation

- **Definition:** A melodic/vocal stem is forced to resolve over a new,
  different harmonic bed, deliberately altering the perceived mode (e.g.
  major-key vocal reinterpreted over a minor-key backing).
- **Source roles/stems:** Vocal/melodic stem shifted onto a new harmonic
  bed; requires clean vocal isolation and controlled pitch-shifting.
- **Typical structural unit:** Full track duration.
- **Alignment objective:** Altering emotional mode via forced
  transposition while keeping the vocal timbre acceptable.
- **v0 status: out of scope.** This requires actual pitch-shift synthesis
  and a judgment call about how far a vocal can be pushed (the report
  puts vocal-safe pitch shift at roughly 2 semitones before "chipmunk"
  artifacts) — there is no audio synthesis in this codebase at all yet.
  `evaluate_move()` returns no composite score for this move type; it is
  not silently scored as if it were a same-key overlay.
- **Measurable criteria (v0):** none. Do not read the harmonic_score
  circle-of-fifths distance as a proxy for reinterpretation viability —
  it measures "are these already close," which is close to the opposite
  question.
- **Known failure modes:** N/A — not implemented.
- **Required manual overrides:** key override, once implemented, would
  be central to this move type (choosing the target reinterpreted key
  explicitly rather than trusting a detector).

## lyrical_conceptual_juxtaposition

- **Definition:** Two highly recognizable vocal tracks are paired for
  thematic irony, humor, or commentary via their lyrical/conceptual
  content (e.g. call-and-response between two well-known songs).
- **Source roles/stems:** Vocal tracks from both A and B, chosen for
  semantic content, not primarily for acoustic compatibility.
- **Typical structural unit:** Call-and-response phrases, parallel
  verses.
- **Alignment objective:** Thematic/lyrical resonance — a listener
  cognition question, not a signal-processing one.
- **v0 status: out of scope.** This requires lyric transcription and NLP
  the report explicitly excludes from v0 ("The v0 system treats vocals
  strictly as structured melodic audio waveforms"). No lyric or semantic
  data exists anywhere in this codebase.
- **Measurable criteria (v0):** none.
- **Known failure modes:** N/A — not implemented.
- **Required manual overrides:** N/A — this move type is entirely a
  human editorial judgment at v0; there's nothing to override because
  there's no automated suggestion in the first place.

## sample_collage

- **Definition:** Many short, heavily processed micro-samples from
  multiple sources are rearranged into a synthetic composition largely
  independent of the original tracks' structures.
- **Source roles/stems:** Fragmented, edited micro-stems from
  potentially more than two sources.
- **Typical structural unit:** Microscopic loops and transient slices.
- **Alignment objective:** Reconstructing a new piece, not aligning two
  existing structures.
- **v0 status: out of scope.** This tool models exactly two tracks with
  one role each; the whole idea of a collage across N fragmented sources
  doesn't fit the `EvaluationPair` / two-track data model at all. The
  report also excludes this via the COCOLA/pairwise-combinatorics
  argument — evaluating collage-viable fragments pairwise across a
  library is computationally prohibitive for a local-first v0.
- **Measurable criteria (v0):** none.
- **Known failure modes:** N/A — not implemented.
- **Required manual overrides:** N/A — not implemented.

---

## Status summary

| Move type | v0 status |
| :-- | :-- |
| vocal_over_instrumental_overlay | supported |
| transition_blend | supported (basic only) |
| hook_collision | partial |
| rhythmic_graft | partial |
| genre_contrast_blend | partial |
| harmonic_reinterpretation | out of scope |
| lyrical_conceptual_juxtaposition | out of scope |
| sample_collage | out of scope |

"Supported" and "partial" both produce a real composite score from the
same three core dimensions (tempo, harmonic, phrase) plus whatever
optional dimensions the caller supplies (arrangement contrast, collision).
The difference is honesty about what that score means: "supported" means
the dimensions being scored are the ones that actually determine whether
the move works; "partial" means the score is a generic compatibility
signal that doesn't capture the move-specific criteria (hook timing,
groove feel, contrast quality, transition window) yet. "Out of scope"
means `evaluate_move()` returns no score at all rather than a
misleadingly confident number.
