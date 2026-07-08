from mashpad.models import FitLevel
from mashpad.scoring.harmonic_score import score_harmonic_fit


def test_identical_key_scores_high():
    result = score_harmonic_fit("C major", "C major")
    assert result.fit == FitLevel.STRONG
    assert result.score == 1.0


def test_relative_major_minor_scores_high():
    # A minor is the relative minor of C major (same key signature).
    result = score_harmonic_fit("A minor", "C major")
    assert result.fit == FitLevel.STRONG
    assert result.relation == "relative major/minor"


def test_perfect_fifth_neighbor_scores_high():
    result = score_harmonic_fit("C major", "G major")
    assert result.fit == FitLevel.STRONG
    assert result.relation == "perfect fifth neighbor"


def test_semitone_clash_scores_low():
    result = score_harmonic_fit("C major", "C# major")
    assert result.fit == FitLevel.WEAK
    assert result.score < 0.5


def test_semitone_clash_suggests_pitch_adjustment():
    result = score_harmonic_fit("C major", "C# major")
    descriptions = [a.description for a in result.adjustments]
    assert any("Pitch shift" in d for d in descriptions)
    # The clash itself still scores low -- the suggestion makes it fixable,
    # it doesn't retroactively make the raw pairing "strong".
    assert result.fit == FitLevel.WEAK


def test_non_clash_relations_do_not_suggest_pitch_shift():
    result = score_harmonic_fit("A minor", "C major")
    descriptions = [a.description for a in result.adjustments]
    assert descriptions == ["No pitch shift required"]


def test_distant_unrelated_keys_score_lower_than_related():
    related = score_harmonic_fit("A minor", "C major")
    distant = score_harmonic_fit("C major", "F# major")  # tritone apart
    assert distant.score < related.score


def test_adjustable_label_names_the_correct_track():
    result = score_harmonic_fit("C major", "C# major", adjustable_label="A")
    descriptions = [a.description for a in result.adjustments]
    assert any("Pitch shift Song A" in d for d in descriptions)
