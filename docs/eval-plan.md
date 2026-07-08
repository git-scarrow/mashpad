# Evaluation plan

A "falsification harness" for the scoring model: a small corpus of track
pairs with a known expected outcome, run through `evaluate_move()`, to
check the model separates good pairings from bad ones. This is inspired
by the harness in `docs/Mashup Compatibility Tool Taxonomy.md`, adapted
to what's actually testable at v0 — **structured data, not real audio.**

## What this validates, and what it doesn't

This proves the scoring *model* is internally consistent: that near-BPM
identical-key pairs score high, that distant-key/large-stretch pairs
score low, and that half/double-time pairs aren't penalized as if they
were unrelated. It does **not** validate that the model matches human
judgment about real mashups — that would require real audio, real stem
separation, and a real listening test, none of which exist yet. Treat a
passing corpus as "the math does what we said it does," not "these
scores are trustworthy predictions of a good mashup."

## Schema

`EvaluationPair` (`src/mashpad/models.py`) is the schema for one corpus
row:

| Field | Meaning |
| :-- | :-- |
| `pair_id` | Stable identifier for the pair. |
| `validation_class` | One of `positive_ground_truth`, `known_compatible_match`, `negative_ground_truth`. |
| `move_type` | Which `MashupMoveType` this pair is evaluated as. |
| `track_a_role` / `track_b_role` | Role assignment for the evaluation. |
| `expected_score_min` / `expected_score_max` | The composite score band a passing implementation should land in. |
| `expected_features` | Free-text tags describing *why* (e.g. `"identical_key"`, `"half_time"`) — documentation, not machine-checked. |
| `notes` | Free text. |
| `track_a_path` / `track_b_path` | Optional local-only placeholders for real audio, e.g. `"local/song_a.mp3"`. Never resolved, never committed, never point at real files in this repo — see `fixtures/README.md`. |

`EvaluationPair` intentionally does **not** carry BPM/key/section data.
It's metadata about a pair's identity and expectation, not the analysis
input itself. A test that actually runs `evaluate_move()` against a
corpus pair supplies its own `TrackAnalysis` fixtures (synthetic
bpm/key/sections, same pattern as `tests/fixtures/track_a.json`), keyed
by `pair_id`. See `tests/test_evaluation_corpus.py`.

## Validation classes

### `positive_ground_truth`

The report's version: vocal and instrumental stems from the *same*
original recording (so this is a "gimme" — if this doesn't score near the
top, something is broken). v0 has no stems, so this is simulated as two
`TrackAnalysis` fixtures with identical BPM and identical key.

- Expected composite score: **0.85 - 1.0**

### `known_compatible_match`

Different tracks, deliberately constructed to be compatible: identical or
adjacent key (circle-of-fifths distance 0-1), BPM within a few percent.

- Expected composite score: **0.55 - 0.85** (this repo's `STRONG`
  threshold in `composite_score.py` is 0.75 — a known-compatible pair
  should clear `MODERATE` and often clear `STRONG`, but the band is kept
  wide since these are hand-built fixtures, not tuned ground truth)

### `negative_ground_truth`

Distant key (tritone or near-tritone) combined with a BPM relationship
that isn't a clean 1x/0.5x/2x match — a pairing that should force a large
stretch *and* a harsh key clash at the same time.

- Expected composite score: **0.0 - 0.3**

## Why these numbers differ from the report's example thresholds

The report's illustrative harness asserts `>= 0.85` / `0.65-0.85` /
`<= 0.30` against its own example weights (0.30 tempo / 0.50 harmonic /
0.20 contrast, no phrase term). This codebase's `CompatibilityWeights`
defaults (`composite_score.py`) are different — tempo/harmonic/phrase/
contrast at 0.30/0.30/0.20/0.20 — and phrase fit is a real component
here that the report's formula doesn't include. Copying the report's
exact thresholds against a different formula would just be two unrelated
numbers that happen to look similar. The bands above are set against
*this* model's actual output, checked by running the corpus, not derived
from the report by inspection.

## Running it

```bash
uv run pytest tests/test_evaluation_corpus.py -v
```

Each corpus pair asserts `expected_score_min <= composite_score <=
expected_score_max`. A failing assertion means either the scoring model
changed in a way that shifts a known-good/known-bad pair's score, or a
corpus fixture was miscategorized — both are worth investigating, not
silencing by widening the band.

## Growing the corpus

`tests/fixtures/evaluation_corpus.example.json` currently has two example
pairs per validation class — enough to prove the harness works, not a
real evaluation corpus. Expanding it with more structured fixtures (still
no real audio) is the natural next step once real analysis exists and
there's something worth stress-testing beyond hand-picked BPM/key values.
