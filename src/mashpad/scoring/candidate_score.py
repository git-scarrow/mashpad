"""Candidate mashup pairing and ranking from weighted component scores.

Real logic (not stubbed): every section-pair between the two tracks gets
a score from the overall compatibility components, with a small bonus for
pairing sections that are natural mashup anchors (chorus/verse/bridge) and
a small penalty for pairing two sections of the same type (which tend to
compete for the same energy/role rather than complement each other).
"""

from __future__ import annotations

from mashpad.models import CompatibilityScores, MashupCandidate, Section

TEMPO_WEIGHT = 0.35
HARMONIC_WEIGHT = 0.35
PHRASE_WEIGHT = 0.30

PREFERRED_LABELS = {"chorus", "verse", "bridge", "instrumental"}
SAME_LABEL_PENALTY = 0.05
PREFERRED_LABEL_BONUS = 0.1


def rank_candidates(
    sections_a: list[Section],
    sections_b: list[Section],
    scores: CompatibilityScores,
    top_n: int = 3,
) -> list[MashupCandidate]:
    base = (
        TEMPO_WEIGHT * scores.tempo_score
        + HARMONIC_WEIGHT * scores.harmonic_score
        + PHRASE_WEIGHT * scores.phrase_score
    )

    scored_pairs = []
    for sec_a in sections_a:
        for sec_b in sections_b:
            pair_score = base * _pair_bonus(sec_a, sec_b)
            description = f"A {sec_a.label} over B {sec_b.label}"
            scored_pairs.append((pair_score, sec_a, sec_b, description))

    scored_pairs.sort(key=lambda item: item[0], reverse=True)

    return [
        MashupCandidate(
            rank=i + 1, section_a=a, section_b=b, score=round(score, 4), description=desc
        )
        for i, (score, a, b, desc) in enumerate(scored_pairs[:top_n])
    ]


def _pair_bonus(sec_a: Section, sec_b: Section) -> float:
    bonus = 1.0
    if sec_a.label in PREFERRED_LABELS:
        bonus += PREFERRED_LABEL_BONUS
    if sec_b.label in PREFERRED_LABELS:
        bonus += PREFERRED_LABEL_BONUS
    if sec_a.label == sec_b.label:
        bonus -= SAME_LABEL_PENALTY
    return bonus
