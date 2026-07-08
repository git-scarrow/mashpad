import pytest

from mashpad.models import FitLevel
from mashpad.scoring.tempo_score import score_tempo_fit


def test_near_bpms_score_high():
    result = score_tempo_fit(122.4, 124.1)
    assert result.fit == FitLevel.STRONG
    assert result.score > 0.8


def test_half_time_bpm_scores_high():
    # 61.2 is exactly half of 122.4 -- a classic half-time mashup pairing.
    result = score_tempo_fit(122.4, 61.2)
    assert result.fit == FitLevel.STRONG
    assert result.multiplier == 2.0


def test_double_time_bpm_scores_high():
    # 244.8 is exactly double 122.4.
    result = score_tempo_fit(122.4, 244.8)
    assert result.fit == FitLevel.STRONG
    assert result.multiplier == 0.5


def test_distant_unrelated_bpms_score_low():
    # 140 isn't close to 90 at 1x, 0.5x, or 2x -- not even a half/double match.
    result = score_tempo_fit(90.0, 140.0)
    assert result.fit == FitLevel.WEAK
    assert result.score < 0.5


def test_stretch_adjustment_suggested_when_bpms_differ():
    result = score_tempo_fit(122.4, 124.1)
    descriptions = [a.description for a in result.adjustments]
    assert any("Stretch B to 122.4 BPM" == d for d in descriptions)


def test_no_stretch_adjustment_when_bpms_already_equal():
    result = score_tempo_fit(120.0, 120.0)
    assert result.adjustments == ()


def test_non_positive_bpm_rejected():
    with pytest.raises(ValueError):
        score_tempo_fit(0, 120.0)


def test_adjustable_label_names_the_correct_track():
    result = score_tempo_fit(122.4, 124.1, adjustable_label="A")
    descriptions = [a.description for a in result.adjustments]
    assert any("Stretch A to 122.4 BPM" == d for d in descriptions)
