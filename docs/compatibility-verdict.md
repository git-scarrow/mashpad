# Compatibility verdict: evidence first, move-relative, willing to abstain

`mashcheck` does not emit a universal "these two songs are N% compatible"
number. It emits a **verdict about one specific mashup move** — Track A in
a role over Track B in another role, using a specific move type — together
with the evidence behind it. This document explains what the verdict means,
why it abstains, and why "compatibility" here is move-relative, not a
property of a song *pair*.

See also: `docs/mashup-move-taxonomy.md` (move types + support status),
`docs/eval-plan.md` (scoring-model validation), and
`mashpad.scoring.verdict` (the implementation).

## Compatibility is move-relative, not a song-pair score

There is no single "A × B" score, on purpose. The same two tracks produce
**different** verdicts depending on:

- **Which move type** you evaluate. `vocal_over_instrumental_overlay`,
  `hook_collision`, and `transition_blend` ask different questions of the
  same pair, and some move types are out of scope entirely (the verdict for
  those is UNCERTAIN — not evaluated — never a number).
- **Which track plays which role.** Compatibility is asymmetric: the
  `vocal`-role track anchors tempo/key because vocals tolerate far less
  stretch/pitch-shift than instrumentals. Swapping the roles is a genuinely
  different evaluation (see `mashpad.scoring.evaluate_move`), so it can
  yield a different verdict.

So a verdict is always reported *against a stated move + role assignment*,
and the report prints that assignment. "Are these two songs compatible?"
is not a well-formed question here; "does A-vocal over B-instrumental work
as an overlay?" is.

## The four verdict levels

`CompatibilityVerdictLevel` — from `assess_compatibility(profile, a, b)`:

| Verdict | Meaning | How hard to earn |
| :-- | :-- | :-- |
| **COMPATIBLE** | Confident yes: the evidence lines up. | Hardest. Requires MEASURED analysis and unambiguous, unconditional evidence. |
| **MAYBE** | A real leaning-yes, but conditional. | Stub data, a partial-support move, a fixable key clash, or a required octave (half/double-time) reading. |
| **UNLIKELY** | Confident no: a necessary condition fails. | Requires MEASURED analysis (e.g. tempos that cannot beat-match at any octave). |
| **UNCERTAIN** | Explicit abstention. | The default whenever evidence is missing, ambiguous, or the move's premise is unverified. |

### The confidence asymmetry

It is easier to **rule a mashup out** than to **rule one in**. Ruling out
means a *necessary* condition failed (you can't beat-match 150 against 90 at
any octave — a structural fact). Ruling in means enough *sufficient*
conditions hold that the tracks will actually work together — a much larger
claim that we cannot support from placeholder analysis.

So confident verdicts (COMPATIBLE / UNLIKELY) require **MEASURED** analysis
provenance. Everything in v0 is `STUB` — BPM/key/sections are seeded from
the *file name*, not the audio (see `AnalysisProvenance` and
`mashpad.analysis`). On stub inputs the harness therefore never says
COMPATIBLE or UNLIKELY: a clean, agreeable pair lands on **MAYBE**, and a
structurally-poor pair lands on **UNCERTAIN** (leaning-no, but we can't even
confirm the rejection from fake numbers). This is the point: the old path
emitted a flattering "composite 0.82 (strong)" for filename-hash inputs;
the verdict layer withholds that confidence and says why.

## When it abstains (UNCERTAIN)

The verdict layer adds the honesty gates the raw scorer lacks. Any of these
forces UNCERTAIN, regardless of how nice the component scores look:

1. **Unsupported move type** — an out-of-scope move is *not evaluated*, so
   there is nothing to judge (abstain, don't fabricate).
2. **Missing role premise** — a move that presupposes a vocal/instrumental
   split (e.g. `vocal_over_instrumental_overlay`) evaluated on two
   `full_mix` tracks. With no stem separation the split is unverified, so
   the move's premise is not established.
3. **Ambiguous BPM** — a track's own analyzer offers two competing,
   non-octave tempo estimates of comparable confidence (e.g. 128 vs 132).
   We don't know the tempo, so we don't pretend to.
4. **Multiple plausible tempo ratios** — a track is octave-ambiguous (e.g.
   85 vs 170 both plausible), so whether the mix is direct or double-time is
   undetermined.
5. **Manual override required** — the only alignment that fits uses a
   half/double-time reading the analyzer itself rates as low-confidence,
   while the track's primary reading does not fit. Compatibility then hinges
   on a manual tempo override the user must confirm.

Cases 3 and 4 are detected from a track's *real* `tempo_candidates` only,
never from the synthesized half/double fallback (whose confidences are all
1.0 by construction) — a fallback is a search space, not an ambiguity
signal. A normal candidate set with one dominant primary (like the stub's
0.6/0.25/0.15 split) is **not** flagged as ambiguous.

## Evidence, not just a label

Every verdict carries `EvidenceItem`s, each a `(dimension, polarity,
detail)` triple. The contract:

- A **confident** verdict cites its `SUPPORTS`/`OPPOSES` items — *what
  evidence supports the confidence*.
- An **UNCERTAIN** verdict cites its `AMBIGUOUS`/`MISSING`/`CONDITIONAL`
  items — *what evidence is missing or ambiguous*.

`verdict.supporting_evidence` and `verdict.caveats` expose these two views.

## Report layout: judgment vs. backend evidence

`mashcheck`'s report is split into two zones so they are never conflated:

- **Musical judgment** — the verdict and its evidence. This is the answer.
- **Analysis evidence (backend components)** — the raw tempo/harmonic/phrase
  fits and the composite *component* score, each shown for transparency and
  explicitly labelled *not the verdict*. Per-track BPM/key/section lines are
  tagged with their provenance (`[stub estimate …]` vs `[measured]`).

The composite score still exists and is unchanged — the verdict layer never
recomputes or re-weights it. It is demoted from "the result" to "one input
the judgment tempers."

## What this is not

- **Not a scoring change.** No weights were tuned; `evaluate_move` and every
  component score are byte-identical. This is a calibration/evidence layer
  on top, and its job is to withhold confidence, never to inflate it.
- **Not real-audio validation.** With v0 stubs the harness cannot reach a
  confident verdict at all. COMPATIBLE/UNLIKELY become reachable only when a
  real analysis backend sets `AnalysisProvenance.MEASURED` — the seam is in
  place, the measurement is not.
