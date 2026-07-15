"""Tests for the within-pair ranking evaluation: metric correctness,
abstention accounting, and the label discipline (hypothesis labels only
ever produce provisional reports; too few labels produce an abstention
report, not fabricated metrics)."""

import pytest

from mashpad.research.evaluation import LabeledCandidate, evaluate_feature, within_pair_report


def _cand(offset: int, label: str, value: float | None, state: str = "annotated"):
    return LabeledCandidate(offset_bars=offset, label=label, state=state, features={"f": value})


def test_pairwise_accuracy_rank_and_topk():
    candidates = (
        _cand(0, "success", 0.9),
        _cand(-1, "near_offset_negative", 0.5),
        _cand(1, "near_offset_negative", 0.7),
        _cand(2, "near_offset_negative", 0.95),  # a negative the feature prefers
    )
    higher = evaluate_feature(candidates, "f", "higher")
    assert higher.pairwise_accuracy == pytest.approx(2 / 3)
    assert higher.success_ranks == (2,)
    assert higher.top_k_recall == 1.0
    assert higher.abstentions == 0
    lower = evaluate_feature(candidates, "f", "lower")
    assert lower.pairwise_accuracy == pytest.approx(1 / 3)
    assert lower.success_ranks == (3,)


def test_ties_count_half_and_abstentions_are_reported():
    candidates = (
        _cand(0, "success", 0.5),
        _cand(1, "near_offset_negative", 0.5),
        _cand(2, "near_offset_negative", None),
    )
    report = evaluate_feature(candidates, "f", "higher")
    assert report.pairwise_accuracy == 0.5  # the tie discriminates nothing
    assert report.n_pairs_compared == 1  # the None candidate never compared
    assert report.abstentions == 1


def test_hypothesis_labels_are_excluded_unless_allowed_and_then_flagged():
    candidates = (
        _cand(0, "success", 0.9),
        _cand(1, "near_offset_negative", 0.5, state="hypothesis"),
    )
    strict = within_pair_report(candidates)
    assert strict["n_usable"] == 1
    assert strict["abstention_report"] is not None  # no negatives -> no metrics
    assert strict["features"] == []
    provisional = within_pair_report(candidates, allow_hypothesis_labels=True)
    assert provisional["provisional"] is True
    assert provisional["features"]  # metrics exist but are marked planning-only
    assert "single-pair" in provisional["single_pair_warning"]


def test_both_directions_always_reported():
    candidates = (
        _cand(0, "success", 0.9),
        _cand(1, "near_offset_negative", 0.5),
    )
    report = within_pair_report(candidates)
    directions = {(f["feature"], f["direction"]) for f in report["features"]}
    assert ("f", "higher") in directions
    assert ("f", "lower") in directions  # choosing one would be in-sample fitting


def test_multiple_successes_all_ranked():
    candidates = (
        _cand(0, "success", 0.9),
        _cand(20, "success", 0.8),
        _cand(1, "near_offset_negative", 0.5),
        _cand(19, "near_offset_negative", 0.85),
    )
    report = evaluate_feature(candidates, "f", "higher")
    assert report.success_ranks == (1, 3)
    assert report.pairwise_accuracy == pytest.approx(3 / 4)


def test_candidates_from_session_labels_maps_viability_and_excludes_unsure():
    """viable True -> success, False -> near_offset_negative (annotated
    via the blinded session), 'unsure' -> excluded entirely; records
    whose offset has no features are dropped for the caller to report."""
    from mashpad.research.evaluation import candidates_from_session_labels

    records = [
        {"offset_bars": 18, "viable": True},
        {"offset_bars": 19, "viable": False},
        {"offset_bars": 17, "viable": "unsure"},
        {"offset_bars": 23, "viable": False},  # no features extracted
    ]
    features = {18: {"f": 1.0}, 19: {"f": 0.5}, 17: {"f": 0.9}}
    candidates = candidates_from_session_labels(records, features)
    assert [(c.offset_bars, c.label) for c in candidates] == [
        (18, "success"),
        (19, "near_offset_negative"),
    ]
    assert all(c.state == "annotated" for c in candidates)
