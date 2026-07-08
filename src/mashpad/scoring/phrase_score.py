"""Phrase-fit scoring, based on section boundary detection confidence.

Real logic (not stubbed): averages the confidence of every detected
section boundary across both tracks. This is deliberately a proxy for
"how much do we trust the section layout enough to suggest a phrase-level
pairing" — not a judgment about the music itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.models import FitLevel, Section

STRONG_THRESHOLD = 0.75
MODERATE_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class PhraseScoreResult:
    score: float
    fit: FitLevel


def score_phrase_fit(sections_a: list[Section], sections_b: list[Section]) -> PhraseScoreResult:
    confidences = [s.confidence for s in (*sections_a, *sections_b)]
    if not confidences:
        return PhraseScoreResult(0.0, FitLevel.TENTATIVE)

    avg_confidence = sum(confidences) / len(confidences)

    if avg_confidence >= STRONG_THRESHOLD:
        fit = FitLevel.STRONG
    elif avg_confidence >= MODERATE_THRESHOLD:
        fit = FitLevel.MODERATE
    else:
        fit = FitLevel.TENTATIVE

    return PhraseScoreResult(round(avg_confidence, 4), fit)
