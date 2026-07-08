"""Arrangement/harmonic contrast scoring.

Design input: docs/Mashup Compatibility Tool Taxonomy.md's "Harmonic
Contrast Score" section, following Chuan-Lung Lee's finding that a mashup
overlay works best when the vocal and backing arrangement have
*contrasting* harmonic/rhythmic density (a sparse vocal over a dense
backing, or vice versa) rather than two dense or two sparse parts
fighting for the same space.

This is a hypothesis over structured inputs, not a validated judgment:
nothing in this codebase estimates harmonic density from real audio yet
(that would need beat-synchronous chromagram analysis). Callers must
supply `complexity_vocal`/`complexity_instrumental` explicitly — there is
no stub estimator here, unlike tempo/key/sections, because inventing a
plausible-looking density number would be worse than admitting we don't
have one yet. `mashpad.scoring.evaluate_move` only uses this dimension
when a caller opts in by supplying both values.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.models import FitLevel

# Contrast bands, expressed as absolute difference between two densities
# normalized to [0.0, 1.0]. v0-usable defaults, not tuned against real data.
STRONG_THRESHOLD = 0.4
MODERATE_THRESHOLD = 0.2


@dataclass(frozen=True, slots=True)
class ArrangementContrastResult:
    score: float
    fit: FitLevel


def score_arrangement_contrast(
    complexity_vocal: float, complexity_instrumental: float
) -> ArrangementContrastResult:
    if not (0.0 <= complexity_vocal <= 1.0) or not (0.0 <= complexity_instrumental <= 1.0):
        raise ValueError("complexity values must be within [0.0, 1.0]")

    contrast = abs(complexity_vocal - complexity_instrumental)

    if contrast >= STRONG_THRESHOLD:
        fit = FitLevel.STRONG
    elif contrast >= MODERATE_THRESHOLD:
        fit = FitLevel.MODERATE
    else:
        fit = FitLevel.WEAK

    return ArrangementContrastResult(round(contrast, 4), fit)
