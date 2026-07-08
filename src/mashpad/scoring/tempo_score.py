"""Tempo compatibility scoring, including half/double-time matching.

Real logic (not stubbed): checks the two BPMs at 1x, 0.5x, and 2x
multipliers and scores the best-fitting one, since half/double-time
tempo matches are common and legitimate in mashups.

`score_tempo_fit` compares two nominal BPM scalars. `score_tempo_candidates`
is the candidate-aware sibling: it searches every (candidate_a, candidate_b)
pair, so a track's half/double-time interpretation can win the match instead
of always deferring to its primary BPM. `mashpad.scoring.evaluate_move` uses
the candidate-aware path whenever both tracks have `tempo_candidates`, and
falls back to a synthesized single-candidate list (clearly labeled as a
fallback) when they don't.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.models import AdjustmentRecommendation, FitLevel, TempoCandidate

# Tolerance bands, expressed as a fraction of the target BPM.
STRONG_TOLERANCE = 0.03
MODERATE_TOLERANCE = 0.08

TEMPO_MULTIPLIERS = (1.0, 0.5, 2.0)


def _deviation_to_score_fit(deviation: float) -> tuple[float, FitLevel]:
    if deviation <= STRONG_TOLERANCE:
        fit = FitLevel.STRONG
        score = 1.0 - (deviation / STRONG_TOLERANCE) * 0.15
    elif deviation <= MODERATE_TOLERANCE:
        fit = FitLevel.MODERATE
        span = MODERATE_TOLERANCE - STRONG_TOLERANCE
        score = 0.85 - (deviation - STRONG_TOLERANCE) / span * 0.35
    else:
        fit = FitLevel.WEAK
        score = max(0.05, 0.5 - deviation)
    return score, fit


@dataclass(frozen=True, slots=True)
class TempoScoreResult:
    score: float
    fit: FitLevel
    multiplier: float  # which of TEMPO_MULTIPLIERS produced the best fit
    adjusted_bpm_b: float
    adjustments: tuple[AdjustmentRecommendation, ...] = ()


@dataclass(frozen=True, slots=True)
class TempoMatch:
    """Result of matching two tracks' *candidate sets* rather than one BPM each.

    `relation` names which side's candidate (if either) was a half/double-time
    interpretation relative to that track's own primary candidate
    (`TempoCandidate.multiplier_from_primary == 1.0`): `direct`,
    `a_half_time`, `a_double_time`, `b_half_time`, `b_double_time`, or
    `unresolved` when both selected candidates are non-primary. `"a"`/`"b"`
    refer to whichever candidate list was passed first/second — callers
    that anchor on a role (e.g. `evaluate_move`) pass the anchor track's
    candidates first, so `required_stretch_ratio` and the deviation score
    stay normalized against the anchor, consistent with `score_tempo_fit`.
    """

    score: float
    fit: FitLevel
    selected_bpm_a: float
    selected_bpm_b: float
    relation: str
    required_stretch_ratio: float
    explanation: str
    adjustments: tuple[AdjustmentRecommendation, ...] = ()


def _relation_label(candidate_a: TempoCandidate, candidate_b: TempoCandidate) -> str:
    a_is_primary = candidate_a.multiplier_from_primary == 1.0
    b_is_primary = candidate_b.multiplier_from_primary == 1.0

    if a_is_primary and b_is_primary:
        return "direct"
    if b_is_primary and not a_is_primary:
        return "a_double_time" if candidate_a.multiplier_from_primary > 1.0 else "a_half_time"
    if a_is_primary and not b_is_primary:
        return "b_double_time" if candidate_b.multiplier_from_primary > 1.0 else "b_half_time"
    return "unresolved"


def score_tempo_candidates(
    candidates_a: list[TempoCandidate],
    candidates_b: list[TempoCandidate],
    adjustable_label: str = "B",
) -> TempoMatch:
    """Find the best-fitting pair across two tracks' candidate tempo sets.

    Contract:

    - Evaluates every `(candidate_a, candidate_b)` combination — an
      exhaustive search, not a greedy or primary-only comparison.
    - Selects the pair with the lowest tempo deviation, which is
      equivalent to the highest-scoring pair: `_deviation_to_score_fit` is
      monotonically non-increasing in deviation, so minimizing deviation
      always maximizes (or ties) score. Ties are broken toward the pair
      with the higher combined candidate confidence.
    - Preserves the winning pair's BPMs verbatim as `selected_bpm_a` /
      `selected_bpm_b` (never averaged or re-derived).
    - Exposes `required_stretch_ratio` (`selected_bpm_a / selected_bpm_b`)
      as the residual stretch needed after picking that pair.
    - Does *not* itself know whether its inputs were real candidates or a
      synthesized fallback — that distinction belongs to the caller (see
      `mashpad.scoring.evaluate_move`, which prefixes
      `CompatibilityProfile.tempo_explanation` with `[fallback: ...]`
      when either side lacked real `tempo_candidates`).
    - A wide, unrelated tempo gap stays weak even with a full
      half/direct/double candidate set on both sides: the exhaustive
      search only rescues a match if some actual candidate pair is close,
      it doesn't relax tolerance just because candidates exist (see
      `test_no_valid_candidate_interpretation_stays_weak` and
      `test_evaluate_move_does_not_overfit_a_wide_tempo_gap`).

    Deviation is normalized against `candidate_a.bpm`, the same convention
    as `score_tempo_fit`'s `bpm_a` anchor, so a track's half/double-time
    interpretation can win the match without the caller having to
    pre-select a single BPM.
    """
    if not candidates_a or not candidates_b:
        raise ValueError("candidate lists must be non-empty")

    pairs = [(ca, cb) for ca in candidates_a for cb in candidates_b]
    candidate_a, candidate_b = min(
        pairs,
        key=lambda pair: (
            abs(pair[0].bpm - pair[1].bpm) / pair[0].bpm,
            -(pair[0].confidence + pair[1].confidence),
        ),
    )
    deviation = abs(candidate_a.bpm - candidate_b.bpm) / candidate_a.bpm
    score, fit = _deviation_to_score_fit(deviation)
    relation = _relation_label(candidate_a, candidate_b)
    stretch_ratio = candidate_a.bpm / candidate_b.bpm if candidate_b.bpm else float("inf")

    explanation = (
        f"Selected {candidate_a.bpm:.1f} BPM vs {candidate_b.bpm:.1f} BPM (relation={relation})"
    )

    adjustments = []
    if relation.startswith("a_"):
        adjustments.append(
            AdjustmentRecommendation(
                f"Treat Song A as half/double-time: "
                f"{candidate_a.multiplier_from_primary}x -> {candidate_a.bpm:.1f} BPM"
            )
        )
    elif relation.startswith("b_"):
        adjustments.append(
            AdjustmentRecommendation(
                f"Treat Song B as half/double-time: "
                f"{candidate_b.multiplier_from_primary}x -> {candidate_b.bpm:.1f} BPM"
            )
        )
    if abs(candidate_a.bpm - candidate_b.bpm) > 0.05:
        adjustments.append(
            AdjustmentRecommendation(f"Stretch {adjustable_label} to {candidate_a.bpm:.1f} BPM")
        )

    return TempoMatch(
        score=round(score, 4),
        fit=fit,
        selected_bpm_a=candidate_a.bpm,
        selected_bpm_b=candidate_b.bpm,
        relation=relation,
        required_stretch_ratio=round(stretch_ratio, 4),
        explanation=explanation,
        adjustments=tuple(adjustments),
    )


def score_tempo_fit(bpm_a: float, bpm_b: float, adjustable_label: str = "B") -> TempoScoreResult:
    """Score tempo fit, treating `bpm_a` as the anchor and `bpm_b` as adjustable.

    `adjustable_label` names whichever track is being stretched in the
    generated adjustment text (defaults to "B" for the historical
    A-anchors-B behavior). Callers that know track roles — e.g.
    `mashpad.scoring.evaluate_move`, which anchors on the `vocal`-role
    track since vocals tolerate far less stretch than instrumentals —
    pass `bpm_a` as the vocal-role BPM and label the instrumental-role
    track accordingly. This also makes the *deviation ratio* itself
    asymmetric (it's normalized by `bpm_a`), not just the wording.

    This is the single-BPM sibling of `score_tempo_candidates`; prefer that
    function when both tracks have `TrackAnalysis.tempo_candidates`.
    """
    if bpm_a <= 0 or bpm_b <= 0:
        raise ValueError("BPM values must be positive")

    candidates = []
    for multiplier in TEMPO_MULTIPLIERS:
        adjusted_b = bpm_b * multiplier
        deviation = abs(adjusted_b - bpm_a) / bpm_a
        candidates.append((deviation, multiplier, adjusted_b))
    deviation, multiplier, adjusted_b = min(candidates, key=lambda c: c[0])

    score, fit = _deviation_to_score_fit(deviation)

    adjustments = []
    if multiplier != 1.0:
        adjustments.append(
            AdjustmentRecommendation(
                f"Treat Song {adjustable_label} as half/double-time: "
                f"{multiplier}x -> {adjusted_b:.1f} BPM"
            )
        )
    if abs(bpm_a - adjusted_b) > 0.05:
        adjustments.append(
            AdjustmentRecommendation(f"Stretch {adjustable_label} to {bpm_a:.1f} BPM")
        )

    return TempoScoreResult(
        score=round(score, 4),
        fit=fit,
        multiplier=multiplier,
        adjusted_bpm_b=adjusted_b,
        adjustments=tuple(adjustments),
    )
