from pathlib import Path

import pytest

from mashpad.models import FitLevel, TempoCandidate, Track, TrackAnalysis, TrackRole
from mashpad.scoring import evaluate_move
from mashpad.scoring.tempo_score import MODERATE_TOLERANCE, score_tempo_candidates


def test_double_time_candidate_beats_nominal_bpm_match():
    # 87 BPM was misread; 174 (its double-time candidate) is the real match for 172.
    candidates_a = [
        TempoCandidate(bpm=87.0, confidence=0.6, multiplier_from_primary=1.0),
        TempoCandidate(bpm=174.0, confidence=0.15, multiplier_from_primary=2.0),
    ]
    candidates_b = [TempoCandidate(bpm=172.0, confidence=0.6, multiplier_from_primary=1.0)]

    candidate_aware = score_tempo_candidates(candidates_a, candidates_b)
    naive_nominal_deviation = abs(87.0 - 172.0) / 87.0

    assert candidate_aware.fit == FitLevel.STRONG
    assert candidate_aware.relation == "a_double_time"
    assert candidate_aware.selected_bpm_a == 174.0
    # The nominal (primary-only) BPM pairing would have been far outside even
    # the moderate tolerance band -- the candidate match rescues it.
    assert naive_nominal_deviation > MODERATE_TOLERANCE


def test_half_time_candidate_matches_double_tempo_track():
    candidates_a = [
        TempoCandidate(bpm=70.0, confidence=0.6, multiplier_from_primary=1.0),
        TempoCandidate(bpm=140.0, confidence=0.15, multiplier_from_primary=2.0),
    ]
    candidates_b = [TempoCandidate(bpm=140.0, confidence=0.6, multiplier_from_primary=1.0)]

    result = score_tempo_candidates(candidates_a, candidates_b)

    assert result.fit == FitLevel.STRONG
    assert result.selected_bpm_a == 140.0
    assert result.selected_bpm_b == 140.0
    assert result.relation == "a_double_time"


def test_close_primary_candidates_match_directly():
    candidates_a = [TempoCandidate(bpm=120.0, confidence=0.6, multiplier_from_primary=1.0)]
    candidates_b = [TempoCandidate(bpm=123.0, confidence=0.6, multiplier_from_primary=1.0)]

    result = score_tempo_candidates(candidates_a, candidates_b)

    assert result.relation == "direct"
    assert result.fit == FitLevel.STRONG


def test_no_valid_candidate_interpretation_stays_weak():
    candidates_a = [
        TempoCandidate(bpm=95.0, confidence=0.6, multiplier_from_primary=1.0),
        TempoCandidate(bpm=47.5, confidence=0.25, multiplier_from_primary=0.5),
        TempoCandidate(bpm=190.0, confidence=0.15, multiplier_from_primary=2.0),
    ]
    candidates_b = [
        TempoCandidate(bpm=128.0, confidence=0.6, multiplier_from_primary=1.0),
        TempoCandidate(bpm=64.0, confidence=0.25, multiplier_from_primary=0.5),
        TempoCandidate(bpm=256.0, confidence=0.15, multiplier_from_primary=2.0),
    ]

    result = score_tempo_candidates(candidates_a, candidates_b)

    assert result.fit == FitLevel.WEAK


def test_empty_candidate_lists_rejected():
    with pytest.raises(ValueError):
        score_tempo_candidates([], [TempoCandidate(bpm=120.0, confidence=1.0)])


def _analysis(bpm, key, path, tempo_candidates=()):
    return TrackAnalysis(
        track=Track(path=Path(path)), bpm=bpm, key=key, tempo_candidates=tuple(tempo_candidates)
    )


def test_asymmetric_role_scoring_still_works_with_tempo_candidates():
    analysis_a = _analysis(
        bpm=87.0,
        key="C major",
        path="a.mp3",
        tempo_candidates=[
            TempoCandidate(bpm=87.0, confidence=0.6, multiplier_from_primary=1.0),
            TempoCandidate(bpm=174.0, confidence=0.15, multiplier_from_primary=2.0),
        ],
    )
    analysis_b = _analysis(
        bpm=172.0,
        key="C major",
        path="b.mp3",
        tempo_candidates=[TempoCandidate(bpm=172.0, confidence=0.6, multiplier_from_primary=1.0)],
    )

    a_vocal = evaluate_move(
        analysis_a, analysis_b, track_a_role=TrackRole.VOCAL, track_b_role=TrackRole.INSTRUMENTAL
    )
    b_vocal = evaluate_move(
        analysis_a, analysis_b, track_a_role=TrackRole.INSTRUMENTAL, track_b_role=TrackRole.VOCAL
    )

    # Both pick A's double-time (174 BPM) candidate as the best match against B's
    # 172 BPM, but the deviation is normalized against whichever track anchors the
    # role assignment, so the resulting scores differ even though both are strong.
    assert a_vocal.scores.tempo_score != b_vocal.scores.tempo_score
    assert a_vocal.scores.tempo_fit == FitLevel.STRONG
    assert b_vocal.scores.tempo_fit == FitLevel.STRONG


def test_evaluate_move_still_resolves_half_double_time_without_candidates():
    analysis_a = _analysis(bpm=140.0, key="C major", path="a.mp3")
    analysis_b = _analysis(bpm=70.0, key="C major", path="b.mp3")

    profile = evaluate_move(analysis_a, analysis_b)

    assert profile.scores.tempo_fit == FitLevel.STRONG
    assert profile.tempo_explanation is not None
    assert "fallback" in profile.tempo_explanation


def test_evaluate_move_does_not_overfit_a_wide_tempo_gap():
    # Both tracks carry a full primary/half/double candidate set, but no
    # combination is actually close -- the exhaustive search must not
    # manufacture a strong match just because candidates exist.
    def _triplet(primary_bpm):
        return [
            TempoCandidate(bpm=primary_bpm * 0.5, confidence=0.25, multiplier_from_primary=0.5),
            TempoCandidate(bpm=primary_bpm, confidence=0.6, multiplier_from_primary=1.0),
            TempoCandidate(bpm=primary_bpm * 2.0, confidence=0.15, multiplier_from_primary=2.0),
        ]

    analysis_a = _analysis(bpm=90.0, key="C major", path="a.mp3", tempo_candidates=_triplet(90.0))
    analysis_b = _analysis(bpm=133.0, key="C major", path="b.mp3", tempo_candidates=_triplet(133.0))

    profile = evaluate_move(analysis_a, analysis_b)

    assert profile.scores.tempo_fit == FitLevel.WEAK
    assert profile.scores.tempo_score < 0.5
    assert profile.tempo_explanation is not None
    assert "fallback" not in profile.tempo_explanation


def test_report_explains_selected_tempo_interpretation():
    from mashpad.cli import build_report

    analysis_a = _analysis(
        bpm=87.0,
        key="C major",
        path="a.mp3",
        tempo_candidates=[
            TempoCandidate(bpm=87.0, confidence=0.6, multiplier_from_primary=1.0),
            TempoCandidate(bpm=174.0, confidence=0.15, multiplier_from_primary=2.0),
        ],
    )
    analysis_b = _analysis(
        bpm=172.0,
        key="C major",
        path="b.mp3",
        tempo_candidates=[TempoCandidate(bpm=172.0, confidence=0.6, multiplier_from_primary=1.0)],
    )

    report = build_report(analysis_a, analysis_b)

    assert "Tempo interpretation:" in report
    assert "relation=" in report
