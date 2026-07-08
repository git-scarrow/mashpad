import pytest

from mashpad.models import FitLevel
from mashpad.scoring.arrangement_contrast_score import score_arrangement_contrast


def test_balanced_contrast_scores_high():
    # Sparse vocal (0.1) over dense instrumental (0.9) -- the report's
    # recommended pairing.
    result = score_arrangement_contrast(0.1, 0.9)
    assert result.fit == FitLevel.STRONG
    assert result.score == pytest.approx(0.8)


def test_matched_density_scores_low():
    # Two dense (or two sparse) parts fighting for the same space.
    result = score_arrangement_contrast(0.8, 0.85)
    assert result.fit == FitLevel.WEAK


def test_out_of_range_complexity_rejected():
    with pytest.raises(ValueError):
        score_arrangement_contrast(1.5, 0.5)
