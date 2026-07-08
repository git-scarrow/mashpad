import json
from pathlib import Path

import pytest

from mashpad.models import EvaluationPair, Section, Track, TrackAnalysis
from mashpad.scoring import evaluate_move

CORPUS_PATH = Path(__file__).parent / "fixtures" / "evaluation_corpus.example.json"


def _analysis(bpm: float, key: str, confidence: float, path: str) -> TrackAnalysis:
    sections = (Section(label="chorus", start_sec=0.0, end_sec=20.0, confidence=confidence),)
    return TrackAnalysis(track=Track(path=Path(path)), bpm=bpm, key=key, sections=sections)


# Structured (non-audio) fixtures for each corpus pair. EvaluationPair itself
# carries no bpm/key data -- see docs/eval-plan.md for why.
FIXTURE_ANALYSES = {
    "EX_Pair_01_Pos": (
        _analysis(120.0, "A minor", 0.9, "01a.mp3"),
        _analysis(120.0, "A minor", 0.9, "01b.mp3"),
    ),
    "EX_Pair_02_Pos": (
        _analysis(95.0, "F major", 0.9, "02a.mp3"),
        _analysis(95.0, "F major", 0.9, "02b.mp3"),
    ),
    "EX_Pair_03_Match": (
        _analysis(120.0, "C major", 0.55, "03a.mp3"),
        _analysis(122.0, "G major", 0.55, "03b.mp3"),
    ),
    "EX_Pair_04_Match": (
        _analysis(140.0, "A minor", 0.5, "04a.mp3"),
        _analysis(71.0, "C major", 0.5, "04b.mp3"),
    ),
    "EX_Pair_05_Neg": (
        _analysis(150.0, "C major", 0.5, "05a.mp3"),
        _analysis(90.0, "F# major", 0.5, "05b.mp3"),
    ),
    "EX_Pair_06_Neg": (
        _analysis(130.0, "C major", 0.5, "06a.mp3"),
        _analysis(85.0, "C# major", 0.5, "06b.mp3"),
    ),
}


def _load_corpus() -> list[EvaluationPair]:
    with open(CORPUS_PATH) as f:
        return [EvaluationPair.from_dict(row) for row in json.load(f)]


def test_corpus_has_all_three_validation_classes():
    classes = {pair.validation_class.value for pair in _load_corpus()}
    assert classes == {"positive_ground_truth", "known_compatible_match", "negative_ground_truth"}


@pytest.mark.parametrize("pair", _load_corpus(), ids=lambda p: p.pair_id)
def test_corpus_pair_scores_in_expected_range(pair):
    analysis_a, analysis_b = FIXTURE_ANALYSES[pair.pair_id]
    profile = evaluate_move(
        analysis_a,
        analysis_b,
        move_type=pair.move_type,
        track_a_role=pair.track_a_role,
        track_b_role=pair.track_b_role,
    )
    assert pair.expected_score_min <= profile.composite_score <= pair.expected_score_max
