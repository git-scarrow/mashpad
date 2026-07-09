"""Locks the *current* v0 abstention behavior per move type.

This is the executable half of `docs/fixture-planning-matrix.md`. It asserts
only abstention / confidence-withholding — never a composite score band — so
it cannot drift into tuning the scoring model. The parametrization is derived
from `MOVE_SUPPORT` and `verdict.ROLE_DEPENDENT_MOVES`, so these guarantees
stay attached to whatever those tables say, not a hand-copied list.
"""

from pathlib import Path

import pytest

from mashpad.models import (
    MOVE_SUPPORT,
    AnalysisProvenance,
    CompatibilityVerdictLevel,
    EvidencePolarity,
    MashupMoveType,
    MoveSupportStatus,
    Section,
    Track,
    TrackAnalysis,
    TrackRole,
)
from mashpad.scoring import evaluate_move
from mashpad.scoring.verdict import ROLE_DEPENDENT_MOVES, assess_compatibility

_CONFIDENT_SECTIONS = tuple(
    Section(label=label, start_sec=i * 10.0, end_sec=i * 10.0 + 10.0, confidence=0.85)
    for i, label in enumerate(("intro", "verse", "chorus"))
)

_OUT_OF_SCOPE = [m for m, s in MOVE_SUPPORT.items() if s is MoveSupportStatus.OUT_OF_SCOPE]
_PARTIAL = [m for m, s in MOVE_SUPPORT.items() if s is MoveSupportStatus.PARTIAL]
_ROLE_GATED = sorted(ROLE_DEPENDENT_MOVES, key=lambda m: m.value)


def _clean_pair(provenance: AnalysisProvenance):
    a = TrackAnalysis(
        track=Track(path=Path("a.mp3")),
        bpm=120.0,
        key="C major",
        sections=_CONFIDENT_SECTIONS,
        provenance=provenance,
    )
    b = TrackAnalysis(
        track=Track(path=Path("b.mp3")),
        bpm=120.0,
        key="C major",
        sections=_CONFIDENT_SECTIONS,
        provenance=provenance,
    )
    return a, b


def _assess(a, b, **kwargs):
    return assess_compatibility(evaluate_move(a, b, **kwargs), a, b)


def _has(verdict, dimension, polarity):
    return any(e.dimension == dimension and e.polarity is polarity for e in verdict.evidence)


@pytest.mark.parametrize("move", _OUT_OF_SCOPE, ids=lambda m: m.value)
def test_out_of_scope_move_abstains_with_no_score(move):
    a, b = _clean_pair(AnalysisProvenance.MEASURED)  # even best-case inputs are not scored
    profile = evaluate_move(a, b, move_type=move)
    verdict = assess_compatibility(profile, a, b)

    assert profile.scores is None
    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert _has(verdict, "move_support", EvidencePolarity.MISSING)


@pytest.mark.parametrize("move", _ROLE_GATED, ids=lambda m: m.value)
def test_role_gated_move_abstains_without_role_split(move):
    # MEASURED provenance isolates the cause: it is the missing role premise,
    # not stub data, that forces the abstention.
    a, b = _clean_pair(AnalysisProvenance.MEASURED)
    verdict = _assess(
        a, b, move_type=move, track_a_role=TrackRole.FULL_MIX, track_b_role=TrackRole.FULL_MIX
    )

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert _has(verdict, "role", EvidencePolarity.MISSING)


@pytest.mark.parametrize("move", _PARTIAL, ids=lambda m: m.value)
def test_partial_move_is_capped_below_compatible_even_when_measured(move):
    a, b = _clean_pair(AnalysisProvenance.MEASURED)
    verdict = _assess(a, b, move_type=move)

    assert verdict.level is CompatibilityVerdictLevel.MAYBE
    assert not verdict.is_confident
    assert _has(verdict, "move_support", EvidencePolarity.CONDITIONAL)


@pytest.mark.parametrize("move", list(MashupMoveType), ids=lambda m: m.value)
def test_stub_provenance_is_never_confident_for_any_move(move):
    # The v0 production reality: analyze_track only ever emits STUB provenance,
    # so no move type may present a confident (COMPATIBLE/UNLIKELY) verdict.
    a, b = _clean_pair(AnalysisProvenance.STUB)
    verdict = _assess(a, b, move_type=move)

    assert not verdict.is_confident
    assert verdict.level in (
        CompatibilityVerdictLevel.MAYBE,
        CompatibilityVerdictLevel.UNCERTAIN,
    )
