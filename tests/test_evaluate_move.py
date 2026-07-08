from pathlib import Path

from mashpad.models import (
    FitLevel,
    MashupMoveType,
    MoveSupportStatus,
    Track,
    TrackAnalysis,
    TrackRole,
)
from mashpad.scoring import evaluate_move


def _analysis(bpm: float, key: str, path: str) -> TrackAnalysis:
    return TrackAnalysis(track=Track(path=Path(path)), bpm=bpm, key=key)


def test_tempo_score_is_asymmetric_under_role_swap():
    analysis_a = _analysis(bpm=100.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=108.0, key="C major", path="b.mp3")

    a_vocal = evaluate_move(
        analysis_a, analysis_b, track_a_role=TrackRole.VOCAL, track_b_role=TrackRole.INSTRUMENTAL
    )
    b_vocal = evaluate_move(
        analysis_a, analysis_b, track_a_role=TrackRole.INSTRUMENTAL, track_b_role=TrackRole.VOCAL
    )

    # Same two tracks, opposite role assignment -> different tempo deviation
    # (it's normalized by whichever BPM is the vocal-role anchor).
    assert a_vocal.scores.tempo_score != b_vocal.scores.tempo_score


def test_adjustment_targets_the_instrumental_role_track():
    analysis_a = _analysis(bpm=120.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=122.0, key="C major", path="b.mp3")

    a_vocal = evaluate_move(
        analysis_a, analysis_b, track_a_role=TrackRole.VOCAL, track_b_role=TrackRole.INSTRUMENTAL
    )
    b_vocal = evaluate_move(
        analysis_a, analysis_b, track_a_role=TrackRole.INSTRUMENTAL, track_b_role=TrackRole.VOCAL
    )

    a_vocal_text = [adj.description for adj in a_vocal.adjustments]
    b_vocal_text = [adj.description for adj in b_vocal.adjustments]
    assert any("Stretch B" in d for d in a_vocal_text)
    assert any("Stretch A" in d for d in b_vocal_text)


def test_half_time_pair_is_not_penalized_as_a_bad_stretch():
    analysis_a = _analysis(bpm=140.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=70.0, key="C major", path="b.mp3")

    profile = evaluate_move(analysis_a, analysis_b)

    assert profile.scores.tempo_fit == FitLevel.STRONG
    assert any("half/double-time" in adj.description for adj in profile.adjustments)


def test_distant_key_and_bad_stretch_scores_low():
    analysis_a = _analysis(bpm=150.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=90.0, key="F# major", path="b.mp3")  # tritone, no clean 0.5x/1x/2x

    profile = evaluate_move(analysis_a, analysis_b)

    assert profile.composite_fit == FitLevel.WEAK
    assert profile.composite_score < 0.3


def test_hook_collision_is_not_auto_failed_when_tracks_are_compatible():
    analysis_a = _analysis(bpm=120.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=121.0, key="C major", path="b.mp3")

    profile = evaluate_move(analysis_a, analysis_b, move_type=MashupMoveType.HOOK_COLLISION)

    assert profile.support_status == MoveSupportStatus.PARTIAL
    assert profile.scores is not None
    assert profile.composite_score is not None
    assert profile.composite_fit in (FitLevel.STRONG, FitLevel.MODERATE)


def test_out_of_scope_move_type_is_not_scored():
    analysis_a = _analysis(bpm=120.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=120.0, key="C major", path="b.mp3")

    profile = evaluate_move(analysis_a, analysis_b, move_type=MashupMoveType.SAMPLE_COLLAGE)

    assert profile.support_status == MoveSupportStatus.OUT_OF_SCOPE
    assert profile.scores is None
    assert profile.composite_score is None
    assert profile.composite_fit is None
    assert "out of scope" in profile.note
