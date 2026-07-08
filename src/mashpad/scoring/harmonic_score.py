"""Harmonic compatibility scoring using a small known-key relation table.

Real logic (not stubbed): same key, relative major/minor, perfect-fifth
neighbors, parallel major/minor, and semitone-clash are all classic
harmonic-mixing relations (the same ones behind tools like the Camelot
wheel) — this reimplements them directly from circle-of-fifths distance
rather than depending on an external numbering scheme.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.analysis.harmony import fifths_distance, parse_key, semitone_distance, semitone_shift
from mashpad.models import AdjustmentRecommendation, FitLevel

NO_SHIFT = AdjustmentRecommendation("No pitch shift required")


@dataclass(frozen=True, slots=True)
class HarmonicScoreResult:
    score: float
    fit: FitLevel
    relation: str
    adjustments: tuple[AdjustmentRecommendation, ...] = (NO_SHIFT,)


def score_harmonic_fit(key_a: str, key_b: str, adjustable_label: str = "B") -> HarmonicScoreResult:
    """Score harmonic fit, treating `key_a` as the anchor and `key_b` as adjustable.

    `adjustable_label` names whichever track a pitch-shift recommendation
    applies to (defaults to "B"). The numeric score/relation are symmetric
    in key distance, but which physical track gets shifted — and the sign
    of the shift — depends on which track is treated as anchor, so callers
    that know track roles (e.g. `mashpad.scoring.evaluate_move`, which
    anchors on the `vocal`-role track) should pass keys and label
    accordingly.
    """
    tonic_a, mode_a = parse_key(key_a)
    tonic_b, mode_b = parse_key(key_b)

    if tonic_a == tonic_b and mode_a == mode_b:
        return HarmonicScoreResult(1.0, FitLevel.STRONG, "identical key")

    fifths = fifths_distance(tonic_a, tonic_b)
    semis = semitone_distance(tonic_a, tonic_b)

    if mode_a != mode_b and semis == 3:
        return HarmonicScoreResult(0.95, FitLevel.STRONG, "relative major/minor")

    if mode_a == mode_b and fifths == 1:
        return HarmonicScoreResult(0.85, FitLevel.STRONG, "perfect fifth neighbor")

    if tonic_a == tonic_b and mode_a != mode_b:
        return HarmonicScoreResult(0.6, FitLevel.MODERATE, "parallel major/minor")

    if semis == 1:
        shift = semitone_shift(tonic_a, tonic_b)
        message = f"Pitch shift Song {adjustable_label} by {shift:+d} semitone(s) to resolve clash"
        return HarmonicScoreResult(
            0.2,
            FitLevel.WEAK,
            "semitone clash",
            (AdjustmentRecommendation(message),),
        )

    score = max(0.15, 0.6 - 0.08 * fifths)
    fit = FitLevel.MODERATE if fifths <= 3 else FitLevel.WEAK
    return HarmonicScoreResult(round(score, 4), fit, f"{fifths} steps apart on circle of fifths")
