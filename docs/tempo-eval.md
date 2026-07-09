# Tempo evaluation: local corpus workflow

How to find out, with your own audio, which tempo backend
(`energy_flux`, `autocorrelation`, `librosa`) is currently most useful
for Mashpad — without committing a single audio file or local path.

This is the *tempo backend* evaluation loop (real audio, local-only,
manual). It is separate from `docs/eval-plan.md`, which validates the
*scoring model* against structured JSON fixtures inside pytest.

## Why local-only

The corpus is your music library plus anything you synthesize. Audio
files, and even index files containing your real local paths, stay out
of git (`fixtures/README.md` has the rules; `.gitignore` blocks common
audio extensions repo-wide). The committed
`tests/fixtures/audio_index.example.json` shows the schema with
placeholder paths only. Mark private entries `"do_not_commit": true` as
a reminder, and keep your real index somewhere like
`fixtures/local/audio_index.json` (gitignored).

## 1. Build a private fixture index

Copy `tests/fixtures/audio_index.example.json` somewhere local and point
it at real files. One entry per fixture:

| Field | Required | Meaning |
| :-- | :-- | :-- |
| `id` | yes | Stable unique name for the fixture. |
| `path` | yes | Local audio path. stdlib backends need 16-bit PCM WAV; `librosa` decodes more. Missing files are **skipped**, not failed. |
| `expected_bpm` | yes | The pulse you'd tap. If a track is genuinely ambiguous, pick one reading and let `accepted_bpms`/relations cover the rest. |
| `accepted_bpms` | no | Explicit list of acceptable BPM values. **Default when omitted:** all three octave readings of `expected_bpm` (direct, half-time, double-time) are accepted. |
| `tolerance_percent` | no | Match tolerance, percent of the target BPM (default 4.0). Widen for drift/rubato fixtures. |
| `category` | no | Which tempo risk this fixture probes (see below). |
| `expected_relation` | no | `any` (default), `direct`, `half_time`, or `double_time`. Narrows which relations count as a pass. |
| `source_kind` | no | `synthetic_click`, `public_domain`, `creative_commons`, `owned_file`, `user_private` — your licensing bookkeeping, not enforced. |
| `do_not_commit` | no | Reminder flag for private entries. |
| `notes` | no | Free text, echoed into results. |

### Categories to build first

Categories reflect real mashup tempo risks. You do not need all of them —
start with the first three:

- `steady_quantized_pop` — the baseline; if a backend fails here it's unusable.
- `half_time_ambiguous` — e.g. DnB/trap where 170 vs 85 are both defensible.
- `double_time_ambiguous` — slow tracks a tracker tends to read fast.
- `sparse_intro` — long low-onset intros before the beat starts.
- `drumless_or_soft_onset` — ballads, pads; envelope backends should struggle honestly here.
- `tempo_drift_live` — live drummers, rubato; widen `tolerance_percent`.
- `syncopated_or_swing` — displaced accents that fool autocorrelation.
- `known_bad_or_unusable` — material you expect no backend to handle; documents the boundary.

A useful starter corpus is ~2 fixtures per category you care about, with
at least one synthetic click track (`source_kind: synthetic_click`) as a
sanity check you can regenerate anywhere.

## 2. Run backends

```bash
# stdlib backends (no extras needed)
uv run scripts/eval_tempo.py --backend energy_flux --index path/to/local_audio_index.json
uv run scripts/eval_tempo.py --backend autocorrelation --index path/to/local_audio_index.json

# optional librosa backend (requires the tempo-librosa extra)
uv sync --extra tempo-librosa
uv run --extra tempo-librosa scripts/eval_tempo.py --backend librosa --index path/to/local_audio_index.json
```

Requesting `--backend librosa` without the extra aborts with a clear
`ImportError` naming `tempo-librosa` (exit code 2), rather than failing
every fixture.

To compare backends across runs, save machine-readable results per
backend and diff/inspect them later:

```bash
uv run scripts/eval_tempo.py --index my_index.json --backend energy_flux --json results_energy_flux.json
uv run --extra tempo-librosa scripts/eval_tempo.py --index my_index.json --backend librosa --json results_librosa.json
```

Exit code: 0 when every evaluated fixture passed (skips don't count
against you), 1 when anything failed or errored, 2 for setup problems
(bad index, missing librosa extra).

## 3. Read the results

Per fixture, the table shows the backend's candidates (`bpm@confidence`),
the selected match, its **relation**, percent error, and warnings. The
summary shows totals, pass rate over *evaluated* fixtures, failures
grouped by category, and suspicious cases.

### Direct / half-time / double-time

The evaluator classifies the matched candidate against `expected_bpm`:

- `direct` — within tolerance of `expected_bpm`.
- `half_time` — within tolerance of half of it.
- `double_time` — within tolerance of double it.
- `other` — matched an explicitly listed `accepted_bpms` value unrelated
  to the expected pulse (or, on a FAIL row, matched nothing).

**Half-time and double-time are not failures.** For mashup work they are
often exactly the pulse you'd mix at; Mashpad's candidate-aware scoring
(`score_tempo_candidates`) searches those interpretations on purpose. A
pass via `half_time` tells you the backend found a *usable* pulse, and
the relation tells you which one — that's the answer Mashpad needs, not a
single "true BPM". If a specific fixture must be read at direct time,
say so with `expected_relation: "direct"`.

A pass can carry a warning that the match came from a **non-primary**
candidate: the backend's top choice was a different reading, and only a
companion candidate matched. That's still usable (Mashpad scores all
candidates) but worth tracking — a backend that routinely buries the
accepted pulse in a companion slot is leaning on the octave companions,
not detecting well.

### Suspicious results and confidence

`suspicious` flags a fixture that **failed** while the backend's primary
candidate carried confidence ≥ 0.75. Backend confidence is estimator
self-consistency (autocorrelation strength, librosa frame agreement) —
**not a calibrated probability**. Suspicious cases are the most dangerous
kind of wrong ("confidently wrong"), so they're listed explicitly;
a backend with a decent pass rate but many suspicious failures is worse
for Mashpad than its pass rate suggests.

### Deciding which backend is most useful

Compare, in order: (1) pass rate on `steady_quantized_pop` (must be
~perfect), (2) pass rate on the ambiguous/soft-onset categories, (3) how
few suspicious failures, (4) how often passes needed a non-primary
candidate. Percent error breaks ties.

## Current backend recommendation

Based on the first private local tempo corpus (July 2026):

- **Real-audio tempo evaluation: prefer `librosa`.**
  `uv run --extra tempo-librosa scripts/eval_tempo.py --backend librosa ...`
- **Zero-dependency checks: `energy_flux`** — the stdlib default, useful
  when you don't want to install the `tempo-librosa` extra.
- **`autocorrelation`: historical/diagnostic baseline only.** Do not rely
  on it for real decisions; treat its confidence as meaningless.

Why: all three backends tied on raw pass rate, so pass rate did **not**
separate them — *failure quality* did. `librosa` was the only backend to
pass the real steady-quantized-pop case, handled half-/double-time as
usable interpretations rather than errors, and refused to invent a tempo
for some low-evidence (transient-free) input. `autocorrelation`, by
contrast, produced confidently *wrong* answers — high confidence on a
failed real-music case and on pure noise — which is the single most
dangerous failure mode for a mashup tool.

**Caveat — `librosa` confidence is not a pulse-presence signal.** Its
"confidence" is estimator self-consistency, not a probability that a beat
exists. `librosa` refuses or low-confidences on *some* pulseless input (a
transient-free pad, white noise) but not all: on pulseless *broadband*
material it can lock onto a spurious period and report it confidently — an
expanded-corpus pink-noise fixture produced 123 BPM at confidence 0.92,
where a FAIL was the desired outcome. Never use `librosa` (or its
confidence) as an "is there a usable beat at all?" gate.

**This is not a production-validation claim.** `librosa` is not blessed as
a production detector and is **not** wired into the default `mashcheck` /
`analyze_track` path — it is reachable only through this manual
evaluation loop. The evidence is also thin: only 8 fixtures, only 2 real
songs, and the `sparse_intro`, `double_time_ambiguous`, and
`tempo_drift_live` categories are still missing entirely. The next
validation step is **expanding the private corpus** (more real songs, the
missing categories) *before* wiring real tempo candidates into non-stub
track analysis.

## Testing the harness itself

`tests/test_tempo_eval.py` unit-tests the evaluator (schema loading,
skip behavior, relation classification, summary math, JSON output) using
synthetic WAVs generated inside the tests and fake in-memory backends —
no real audio in the repo, ever.
