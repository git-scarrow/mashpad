from mashpad.models import FitLevel, Section
from mashpad.scoring.phrase_score import score_phrase_fit


def _section(label: str, confidence: float) -> Section:
    return Section(label=label, start_sec=0.0, end_sec=10.0, confidence=confidence)


def test_high_confidence_sections_score_strong():
    sections_a = [_section("verse", 0.9), _section("chorus", 0.85)]
    sections_b = [_section("verse", 0.8), _section("chorus", 0.9)]
    result = score_phrase_fit(sections_a, sections_b)
    assert result.fit == FitLevel.STRONG


def test_low_confidence_sections_score_tentative():
    sections_a = [_section("verse", 0.3), _section("chorus", 0.35)]
    sections_b = [_section("verse", 0.4), _section("chorus", 0.3)]
    result = score_phrase_fit(sections_a, sections_b)
    assert result.fit == FitLevel.TENTATIVE


def test_no_sections_is_tentative_not_an_error():
    result = score_phrase_fit([], [])
    assert result.fit == FitLevel.TENTATIVE
    assert result.score == 0.0
