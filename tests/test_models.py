from pathlib import Path

from mashpad.models import (
    EvaluationPair,
    MashupMoveType,
    Section,
    TempoCandidate,
    Track,
    TrackAnalysis,
    TrackRole,
    ValidationClass,
)


def test_track_analysis_round_trips_through_dict():
    analysis = TrackAnalysis(
        track=Track(path=Path("song.mp3"), title="Song"),
        bpm=120.0,
        key="C major",
        sections=(Section(label="verse", start_sec=0.0, end_sec=10.0, confidence=0.5),),
    )
    restored = TrackAnalysis.from_dict(analysis.to_dict())
    assert restored == analysis


def test_track_analysis_round_trips_tempo_candidates():
    analysis = TrackAnalysis(
        track=Track(path=Path("song.mp3")),
        bpm=120.0,
        key="C major",
        tempo_candidates=(
            TempoCandidate(bpm=120.0, confidence=0.6, multiplier_from_primary=1.0),
            TempoCandidate(bpm=60.0, confidence=0.25, multiplier_from_primary=0.5),
        ),
    )
    restored = TrackAnalysis.from_dict(analysis.to_dict())
    assert restored == analysis


def test_evaluation_pair_round_trips_through_dict():
    pair = EvaluationPair(
        pair_id="EX_Pair_01_Pos",
        validation_class=ValidationClass.POSITIVE_GROUND_TRUTH,
        move_type=MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY,
        track_a_role=TrackRole.VOCAL,
        track_b_role=TrackRole.INSTRUMENTAL,
        expected_score_min=0.85,
        expected_score_max=1.0,
        expected_features=("identical_bpm", "identical_key"),
        notes="same-track simulation",
    )
    restored = EvaluationPair.from_dict(pair.to_dict())
    assert restored == pair
