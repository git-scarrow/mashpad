"""Tempo compatibility scoring, including half/double-time matching.

Real logic (not stubbed): checks the two BPMs at 1x, 0.5x, and 2x
multipliers and scores the best-fitting one, since half/double-time
tempo matches are common and legitimate in mashups.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.models import AdjustmentRecommendation, FitLevel

# Tolerance bands, expressed as a fraction of the target BPM.
STRONG_TOLERANCE = 0.03
MODERATE_TOLERANCE = 0.08

TEMPO_MULTIPLIERS = (1.0, 0.5, 2.0)


@dataclass(frozen=True, slots=True)
class TempoScoreResult:
    score: float
    fit: FitLevel
    multiplier: float  # which of TEMPO_MULTIPLIERS produced the best fit
    adjusted_bpm_b: float
    adjustments: tuple[AdjustmentRecommendation, ...] = ()


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
    """
    if bpm_a <= 0 or bpm_b <= 0:
        raise ValueError("BPM values must be positive")

    candidates = []
    for multiplier in TEMPO_MULTIPLIERS:
        adjusted_b = bpm_b * multiplier
        deviation = abs(adjusted_b - bpm_a) / bpm_a
        candidates.append((deviation, multiplier, adjusted_b))
    deviation, multiplier, adjusted_b = min(candidates, key=lambda c: c[0])

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
