"""Schema guards for the registration-evaluation corpus fixture.

The corpus is evaluation truth for the joint-feature program
(docs/experiment-joint-registration-features.md). These tests lock its
honesty properties: labels come only from human audition/attestation
(state machinery mirrors the research-layer resolution states), presumed
labels stay marked `hypothesis`, and nothing in the fixture can silently
become a discovery input.
"""

import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "registration_corpus_v1.json"

LABELS = {"success", "near_offset_negative", "hard_harmonic_negative", "random_negative"}
STATES = {"annotated", "hypothesis", "unresolved"}


def _corpus() -> dict:
    return json.loads(FIXTURE.read_text())


def test_corpus_schema_and_vocabulary():
    corpus = _corpus()
    assert corpus["schema"] == "mashpad.registration_corpus.v1"
    assert set(corpus["label_taxonomy"]) == LABELS
    assert set(corpus["label_states"]) == STATES
    for pair in corpus["pairs"]:
        assert pair["pair_id"]
        assert pair["technique_family"]
        for side in ("host", "guest"):
            assert pair[side]["local_path"].startswith("fixtures/local/")
        for reg in pair["registrations"]:
            assert isinstance(reg["offset_bars"], int)
            assert reg["label"] in LABELS
            assert reg["state"] in STATES


def test_annotated_labels_carry_a_method_and_hypotheses_do_not_claim_one():
    """An annotated label without a method would be laundering: the state
    says 'a human judged this' and the method says which human act."""
    for pair in _corpus()["pairs"]:
        for reg in pair["registrations"]:
            if reg["state"] == "annotated":
                assert reg["method"], f"annotated label without method: {reg}"


def test_each_pair_contrasts_success_with_near_negatives():
    """The experiment's unit of evidence is a within-pair contrast: every
    pair must carry at least one success and its loose-bar neighbors."""
    for pair in _corpus()["pairs"]:
        by_label: dict[str, list[int]] = {}
        for reg in pair["registrations"]:
            by_label.setdefault(reg["label"], []).append(reg["offset_bars"])
        assert by_label.get("success"), pair["pair_id"]
        near = set(by_label.get("near_offset_negative", []))
        successes = set(by_label["success"])
        assert any({s - 1, s - 2, s - 3} & near for s in successes), (
            f"{pair['pair_id']}: no -1/-2/-3 neighbors of any success"
        )


def test_single_pair_corpus_admits_no_generalization():
    """With n=1 pair the fixture must say so out loud — the honesty note is
    load-bearing until more pairs exist."""
    corpus = _corpus()
    if len(corpus["pairs"]) < 2:
        assert any("n=1" in note for note in corpus["honesty_notes"])
        assert corpus["wanted_pairs"]
