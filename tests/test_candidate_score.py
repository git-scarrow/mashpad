from mashpad.models import CompatibilityScores, FitLevel, Section
from mashpad.scoring.candidate_score import rank_candidates

SECTIONS_A = [
    Section(label="intro", start_sec=0.0, end_sec=10.0, confidence=0.5),
    Section(label="chorus", start_sec=10.0, end_sec=30.0, confidence=0.5),
]
SECTIONS_B = [
    Section(label="verse", start_sec=0.0, end_sec=20.0, confidence=0.5),
    Section(label="outro", start_sec=20.0, end_sec=30.0, confidence=0.5),
]

STRONG_SCORES = CompatibilityScores(
    tempo_fit=FitLevel.STRONG,
    harmonic_fit=FitLevel.STRONG,
    phrase_fit=FitLevel.STRONG,
    tempo_score=0.95,
    harmonic_score=0.95,
    phrase_score=0.9,
)
WEAK_SCORES = CompatibilityScores(
    tempo_fit=FitLevel.WEAK,
    harmonic_fit=FitLevel.WEAK,
    phrase_fit=FitLevel.WEAK,
    tempo_score=0.1,
    harmonic_score=0.15,
    phrase_score=0.2,
)


def test_returns_top_n_candidates_ranked_by_score():
    candidates = rank_candidates(SECTIONS_A, SECTIONS_B, STRONG_SCORES, top_n=3)
    assert len(candidates) == 3
    assert [c.rank for c in candidates] == [1, 2, 3]
    scores = [c.score for c in candidates]
    assert scores == sorted(scores, reverse=True)


def test_strong_compatibility_outranks_weak_compatibility():
    strong = rank_candidates(SECTIONS_A, SECTIONS_B, STRONG_SCORES, top_n=1)[0]
    weak = rank_candidates(SECTIONS_A, SECTIONS_B, WEAK_SCORES, top_n=1)[0]
    assert strong.score > weak.score


def test_candidate_description_names_both_sections():
    candidates = rank_candidates(SECTIONS_A, SECTIONS_B, STRONG_SCORES, top_n=1)
    description = candidates[0].description
    assert description.startswith("A ")
    assert " over B " in description
