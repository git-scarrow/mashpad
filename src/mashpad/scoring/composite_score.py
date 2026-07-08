"""Composite compatibility scoring: combine component scores into one number.

Design input: docs/Mashup Compatibility Tool Taxonomy.md's proposed v0
scoring model (S_comp = w_t*S_tempo + w_h*S_harmonic + w_c*S_contrast -
penalty). The report's example weights (0.30/0.50/0.20 tempo/harmonic/
contrast) are a starting hypothesis, not validated truth — this module
treats every weight as a configurable default via `CompatibilityWeights`,
and callers are expected to override them once real analysis data (or a
listening test) exists to tune against.

This is a hypothesis over structured analysis inputs, not a validated
judgment about real audio: v0-usable with confidence scores and manual
override, not "reliable" or "high precision."
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.models import CollisionProfile, CompatibilityScores, FitLevel
from mashpad.scoring.collision_score import (
    DEFAULT_BASS_COLLISION_WEIGHT,
    DEFAULT_VOCAL_COLLISION_WEIGHT,
    score_collision_penalty,
)

STRONG_THRESHOLD = 0.75
MODERATE_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class CompatibilityWeights:
    tempo: float = 0.30
    harmonic: float = 0.30
    phrase: float = 0.20
    arrangement_contrast: float = 0.20
    vocal_collision: float = DEFAULT_VOCAL_COLLISION_WEIGHT
    bass_collision: float = DEFAULT_BASS_COLLISION_WEIGHT


DEFAULT_WEIGHTS = CompatibilityWeights()


def score_composite(
    scores: CompatibilityScores,
    *,
    arrangement_contrast_score: float | None = None,
    collision: CollisionProfile | None = None,
    weights: CompatibilityWeights = DEFAULT_WEIGHTS,
) -> tuple[float, FitLevel]:
    """Combine component scores into one composite score + fit.

    `arrangement_contrast_score` is only folded in when supplied — v0 has
    no analyzer that produces it, so omitting it (the common case) simply
    renormalizes the remaining weights rather than treating a missing
    dimension as a zero.
    """
    components = [
        (weights.tempo, scores.tempo_score),
        (weights.harmonic, scores.harmonic_score),
        (weights.phrase, scores.phrase_score),
    ]
    if arrangement_contrast_score is not None:
        components.append((weights.arrangement_contrast, arrangement_contrast_score))

    weight_sum = sum(w for w, _ in components)
    base = sum(w * s for w, s in components) / weight_sum if weight_sum else 0.0

    penalty = (
        score_collision_penalty(collision, weights.vocal_collision, weights.bass_collision)
        if collision is not None
        else 0.0
    )

    composite = max(0.0, min(1.0, base - penalty))

    if composite >= STRONG_THRESHOLD:
        fit = FitLevel.STRONG
    elif composite >= MODERATE_THRESHOLD:
        fit = FitLevel.MODERATE
    else:
        fit = FitLevel.WEAK

    return round(composite, 4), fit
