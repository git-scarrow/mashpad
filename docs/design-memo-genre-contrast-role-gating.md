# Design memo: should `genre_contrast_blend` be role-gated?

**Status: memo only. No code or tests changed.** This resolves the modeling
gap flagged in `docs/fixture-planning-matrix.md` (genre_contrast_blend is
absent from `verdict.ROLE_DEPENDENT_MOVES`, so a `FULL_MIX`/`FULL_MIX`
genre-contrast pairing does not abstain on the role premise the way an
overlay does).

Sources reviewed: `docs/mashup-move-taxonomy.md`, `docs/Mashup Compatibility
Tool Taxonomy.md` (move→criteria and feature→reliability tables), and
`mashpad.scoring.verdict` (`ROLE_DEPENDENT_MOVES`, Gate 2 role premise).

## What the move actually is

Both docs define `genre_contrast_blend` structurally as a **lead-stem over
a contrasting bed**: "vocal/melodic stem of style A layered over a backing
track of style B," long parallel sections, strict tempo/phrase congruence,
and the research report explicitly lists **2/4-stem separation to minimize
cross-track bleed** as a requirement.

The only thing that distinguishes it from `vocal_over_instrumental_overlay`
is *intent*: the timbral/stylistic distance is high on purpose, and the
friction is the artistic payload. That distinguishing factor is precisely a
**Category 3 (subjective/aesthetic)** judgment the report and the
operational taxonomy both leave entirely to the user. **Structurally, its
role premise is identical to an overlay.**

## Does it require lead/bed (vocal/backing) separation?

Yes. The move is defined as one isolated lead over one backing bed; the
report requires stem separation for it. So the vocal/instrumental split is
load-bearing here in exactly the same way it is for
`vocal_over_instrumental_overlay`. A pairing where that split is not
established is not yet an instance of this move.

## Is full-mix vs full-mix "genre contrast" a valid move type?

Not as *this* move. Playing two whole contrasting-genre records against
each other is a real thing DJs do, but it is a **DJ/genre blend**, closer to
`transition_blend` ("full mix is usually fine") — and it walks straight into
the taxonomy's two-active-vocals cognitive-clutter failure mode that the
lead/bed isolation exists to avoid. It is a *different* operation with a
*lower* structural guarantee, not the "lead over contrasting bed" that
`genre_contrast_blend` names.

## The three options, compared

| | A. Add to `ROLE_DEPENDENT_MOVES` | B. Split into two move types | C. Remain broad (current) |
| :-- | :-- | :-- | :-- |
| **False positives** | Removes one: `FULL_MIX`/`FULL_MIX` stops reading as if the lead/bed premise held. Does not create false *rejections* — the aesthetic-contrast concern is about scoring, not the role gate, so it is untouched. | Fewest, in principle: each variant gets its correct gate. But encodes a distinction v0 cannot act on (neither variant can judge contrast quality), so the precision is on paper only. | Keeps the latent one: a full-mix pairing reaches `MAYBE` (measured) as though a lead/bed split existed. Inconsistent with overlay. |
| **v0 abstention behavior** | Role gate runs *before* provenance, so this changes stub behavior too: genre-contrast + a proper vocal/instrumental split → `MAYBE`; genre-contrast + `FULL_MIX` (or any non-split) → **`UNCERTAIN`**, matching overlay. | Lead/bed variant behaves like A; full-mix variant behaves like `transition_blend` (not role-gated). Two behaviors to specify and test. | Unchanged: genre-contrast → `MAYBE` for *any* roles; `FULL_MIX` never abstains. |
| **Future analyzer needs** | Same as overlay: stem separation to *verify* the split (roles are caller-asserted today); the gate just keeps the abstention honest until then. Promotion past the `MAYBE` cap still needs the Cat-3 contrast judgment (likely stays human). | Lead/bed variant → stems. Full-mix variant → needs vocal-activity detection to avoid the two-active-vocals false positive; could otherwise reach confidence sooner (like transition). More surface to build. | No new gating, but the inconsistency persists until stems + a contrast model exist. |
| **Cost** | One-line set membership + updated abstention tests. | New `MashupMoveType` value(s), `MOVE_SUPPORT` rows, taxonomy-doc entries, verdict/test updates — taxonomy sprawl. | Zero. |

## Recommendation

**Adopt Option A: add `genre_contrast_blend` to `ROLE_DEPENDENT_MOVES`** (when
implementation is authorized — not in this memo).

Rationale: the move's role premise is *identical* to
`vocal_over_instrumental_overlay`; the sole difference is an aesthetic
judgment v0 deliberately does not model. Treating its role premise
differently is an inconsistency, not a feature. Role-gating makes v0 abstain
(`UNCERTAIN`) when the required lead/bed split is not supplied — exactly the
latent false-confidence the verdict layer exists to prevent — while leaving
the aesthetic-contrast concern untouched (the gate does not reject on
contrast, so it cannot cause the over-conservative false *rejection* the
taxonomy warns about for this move).

**Reject Option B (split) for now** as premature: it encodes a lead/bed vs.
full-mix distinction that yields no different *measurable* outcome at v0
(both cap at `MAYBE`; neither can judge contrast), so it is bookkeeping
without payoff and adds taxonomy to maintain. The full-mix "genre blend"
operation, if it ever earns a first-class slot, is better modeled later as a
distinct move (a deferred Option B) than folded into this one now.

**Reject Option C (status quo)** because it is the documented inconsistency
itself.

### Tradeoffs / caveats to weigh before implementing

- **Role vocabulary is narrower than "lead/bed."** `TrackRole` only offers
  `VOCAL`/`INSTRUMENTAL`/`FULL_MIX`, and the gate checks for one `VOCAL` +
  one `INSTRUMENTAL`. Genre contrast can be an *instrumental* melodic lead
  over a bed, which today can only be expressed by (mildly) overloading
  `INSTRUMENTAL` as "lead." This is the same imperfect fit already tolerated
  for `hook_collision` (whose definition — "both tracks can contribute
  vocal/melodic material" — is not a strict vocal/instrumental split, yet it
  is role-gated). Option A inherits that imperfection; a future,
  larger change would generalize the role vocabulary to lead/bed. That
  generalization is out of scope here and should not block Option A.
- **Option A has a v0-visible effect**, not just a future one: because the
  role gate precedes the provenance gate, full-mix genre-contrast flips from
  `MAYBE` to `UNCERTAIN` even on today's stub inputs. That is the intended
  correction, but it is a behavior change and must land with an updated
  parametrization in `tests/test_move_abstention.py` (the `_ROLE_GATED` list
  is derived from `ROLE_DEPENDENT_MOVES`, so the existing role-gated test
  would automatically extend to cover it) and an update to the
  `genre_contrast_blend` row and gap note in
  `docs/fixture-planning-matrix.md`.
- **Neither gating choice improves aesthetic judgment.** Whatever is decided,
  genre_contrast stays capped at `MAYBE` until a contrast-quality model
  exists (and that may remain a human call). Role-gating only fixes the
  *premise* honesty, not the *contrast* honesty.
