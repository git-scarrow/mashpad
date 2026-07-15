"""Pure-core tests for the blinded audition workflow: blinding conceals
offsets, unsealing round-trips, half-filled sessions cannot become
labels, and multiple viable clips are allowed. No audio, no librosa."""

import pytest

from mashpad.research.audition import (
    RESPONSE_DIMENSIONS,
    blind_assignment,
    response_template,
    unseal,
    validate_response,
)


def _filled(viable=True, confidence="high", **overrides):
    entry = {
        "viable": viable,
        **{dim: 3 for dim in RESPONSE_DIMENSIONS},
        "confidence": confidence,
        "notes": "",
    }
    entry.update(overrides)
    return entry


def test_blind_assignment_is_a_seeded_permutation_that_conceals_offsets():
    offsets = (-3, -2, -1, 0, 1, 2, 3)
    a = blind_assignment(offsets, seed=41)
    b = blind_assignment(offsets, seed=41)
    c = blind_assignment(offsets, seed=42)
    assert a == b  # reproducible from provenance
    assert sorted(off for _, off in a) == sorted(offsets)  # a permutation
    assert a != c  # seed actually randomizes
    for blind_id, offset in a:
        assert str(offset) not in blind_id  # the id encodes nothing
    # ids are positional, so directory order reveals nothing either
    assert [b for b, _ in a] == [f"clip_{chr(ord('a') + i)}" for i in range(len(offsets))]


def test_blind_assignment_rejects_duplicate_offsets():
    with pytest.raises(ValueError, match="duplicate"):
        blind_assignment((0, 1, 1), seed=1)


def test_response_template_contains_no_offsets():
    template = response_template(("clip_a", "clip_b"))
    assert "offset" not in str(template)
    for entry in template["responses"].values():
        assert entry["viable"] is None
        for dim in RESPONSE_DIMENSIONS:
            assert entry[dim] is None


def test_unseal_joins_key_and_responses_and_allows_multiple_viable():
    key = {
        "session_id": "s1",
        "assignment": {
            "clip_a": {"offset_bars": 2, "guest_silent_padding": False},
            "clip_b": {"offset_bars": 0, "guest_silent_padding": False},
            "clip_c": {"offset_bars": -1, "guest_silent_padding": True},
        },
    }
    responses = {
        "responses": {
            "clip_a": _filled(viable=True, notes="also works"),
            "clip_b": _filled(viable=True),
            "clip_c": _filled(viable="unsure", confidence="low"),
        }
    }
    records = unseal(key, responses)
    assert [r["offset_bars"] for r in records] == [-1, 0, 2]  # offset order
    viable = [r["offset_bars"] for r in records if r["viable"] is True]
    assert viable == [0, 2]  # more than one success is allowed
    unsure = next(r for r in records if r["offset_bars"] == -1)
    assert unsure["viable"] == "unsure"  # not coerced to a negative
    assert unsure["guest_silent_padding"] is True
    assert all(r["method"] == "blinded_audition:s1" for r in records)


def test_unseal_refuses_missing_or_invalid_responses():
    key = {"session_id": "s1", "assignment": {"clip_a": {"offset_bars": 0}}}
    with pytest.raises(ValueError, match="no response"):
        unseal(key, {"responses": {}})
    bad = {"responses": {"clip_a": _filled(viable="yes-ish")}}
    with pytest.raises(ValueError, match="viable"):
        unseal(key, bad)


def test_validate_response_checks_scale_and_confidence():
    assert validate_response(_filled()) == []
    assert validate_response(_filled(rhythmic_coherence=9))
    assert validate_response(_filled(confidence="certain"))
    # unrated dimensions are allowed (null), the viability is not
    assert validate_response(_filled(rhythmic_coherence=None)) == []
