"""Anti-laundering guard tests for the field-level provenance substrate.

These are the eight guard tests specified in
`docs/design-memo-analyzer-provenance-contract.md` (Decision 4), realised
against the *substrate* — no real analyzer exists yet, so each constructs
provenance records directly (or drives `apply_override`) rather than
exercising a backend. Each one must fail if a future analyzer tries to
launder weak evidence (a high confidence, a stub fallback, a partial field,
a user override, a global tempo) into a confident verdict.

The single load-bearing invariant: a dimension is confident-worthy only when
its tier is MEASURED on both tracks; confidence numbers, human assertions,
and failures never substitute.
"""

from pathlib import Path

import pytest

from mashpad.analysis import analyze_track
from mashpad.models import (
    PROVENANCE_DIMENSIONS,
    AnalysisProvenance,
    CompatibilityVerdictLevel,
    EvidencePolarity,
    ManualOverride,
    MashupMoveType,
    OverrideTarget,
    ProvenanceRecord,
    ProvenanceTier,
    Section,
    Track,
    TrackAnalysis,
    TrackRole,
)
from mashpad.overrides import apply_override
from mashpad.scoring import evaluate_move
from mashpad.scoring.verdict import CONFIDENCE_DECIDING_DIMENSIONS, assess_compatibility

STUB = ProvenanceTier.STUB
MEASURED = ProvenanceTier.MEASURED
USER_ASSERTED = ProvenanceTier.USER_ASSERTED
UNAVAILABLE = ProvenanceTier.UNAVAILABLE

_LEVEL = CompatibilityVerdictLevel

# Confident sections so phrase-fit never muddies a case that is about provenance.
_CONFIDENT_SECTIONS = tuple(
    Section(label=label, start_sec=i * 10.0, end_sec=i * 10.0 + 10.0, confidence=0.85)
    for i, label in enumerate(("intro", "verse", "chorus"))
)


def _analysis(
    path: str,
    *,
    base: AnalysisProvenance = AnalysisProvenance.STUB,
    measured: tuple[str, ...] = (),
    user_asserted: tuple[str, ...] = (),
    unavailable: tuple[str, ...] = (),
    stub: tuple[str, ...] = (),
    bpm: float = 120.0,
    key: str = "C major",
) -> TrackAnalysis:
    """Build an analysis with an explicit per-dimension provenance mix.

    `base` is the whole-analysis fallback tier; the keyword tuples pin
    individual dimensions above/below it via `field_provenance`.
    """
    field_provenance: dict[str, ProvenanceRecord] = {}
    for dim in measured:
        field_provenance[dim] = ProvenanceRecord(MEASURED, method="fake_backend", confidence=0.8)
    for dim in user_asserted:
        field_provenance[dim] = ProvenanceRecord(USER_ASSERTED, method="manual_override")
    for dim in unavailable:
        field_provenance[dim] = ProvenanceRecord(UNAVAILABLE, method="fake_backend")
    for dim in stub:
        field_provenance[dim] = ProvenanceRecord(STUB, method="stub")
    return TrackAnalysis(
        track=Track(path=Path(path)),
        bpm=bpm,
        key=key,
        sections=_CONFIDENT_SECTIONS,
        provenance=base,
        field_provenance=field_provenance,
    )


def _fully_measured(path: str, *, bpm: float = 120.0, key: str = "C major") -> TrackAnalysis:
    return _analysis(path, base=AnalysisProvenance.MEASURED, bpm=bpm, key=key)


def _assess(a: TrackAnalysis, b: TrackAnalysis, **kwargs):
    return assess_compatibility(evaluate_move(a, b, **kwargs), a, b)


def _has(verdict, dimension, polarity):
    return any(e.dimension == dimension and e.polarity is polarity for e in verdict.evidence)


# --- Guard test 1: confidence is not provenance --------------------------------


def test_confidence_never_promotes_tier():
    # A stub-origin value with a 0.99 confidence stays STUB, and cannot make a
    # verdict confident. Confidence and tier are orthogonal axes.
    rec = ProvenanceRecord(tier=STUB, method="stub", confidence=0.99)
    assert rec.tier is STUB

    a = TrackAnalysis(
        track=Track(path=Path("a.mp3")),
        bpm=120.0,
        key="C major",
        sections=_CONFIDENT_SECTIONS,
        field_provenance={"tempo": rec},  # stub value carrying a 0.99 confidence
    )
    b = _fully_measured("b.mp3")

    verdict = _assess(a, b)
    assert not verdict.is_confident
    assert a.provenance_of("tempo").tier is STUB


# --- Guard test 2: no decoded audio -> no MEASURED (production reality) ---------


def test_production_analyze_track_emits_only_stub_provenance():
    analysis = analyze_track(Track(path=Path("some_song.mp3")))
    for dim in PROVENANCE_DIMENSIONS:
        assert analysis.provenance_of(dim).tier is STUB, dim
    assert analysis.derived_provenance() is AnalysisProvenance.STUB


def test_two_stub_production_tracks_cannot_be_compatible():
    a = analyze_track(Track(path=Path("x.mp3")))
    b = analyze_track(Track(path=Path("y.mp3")))
    verdict = _assess(a, b)
    assert verdict.level is not _LEVEL.COMPATIBLE
    assert not verdict.is_confident


# --- Guard test 3: failed measurement does not fall through --------------------


def test_unavailable_dimension_does_not_count_as_measured():
    # tempo measurement attempted and failed -> UNAVAILABLE, never a stub value
    # wearing a MEASURED tag; no confident verdict may rest on it.
    a = _analysis("a.mp3", base=AnalysisProvenance.MEASURED, unavailable=("tempo",))
    b = _fully_measured("b.mp3")

    assert a.provenance_of("tempo").tier is UNAVAILABLE
    verdict = _assess(a, b)
    assert not verdict.is_confident


@pytest.mark.parametrize(
    "tier,expect_confident",
    [
        (MEASURED, True),
        (STUB, False),
        (UNAVAILABLE, False),
        (USER_ASSERTED, False),
    ],
)
def test_only_measured_tier_passes_the_confidence_gate(tier, expect_confident):
    # Trust is decided by identity, not enum order. Swapping a single deciding
    # dimension's tier (all others MEASURED) flips confidence ONLY for
    # MEASURED; STUB, UNAVAILABLE, and USER_ASSERTED are equally insufficient
    # — none may outrank MEASURED or each other. A future ordering-based
    # refactor of the gate would break this.
    a = TrackAnalysis(
        track=Track(path=Path("a.mp3")),
        bpm=120.0,
        key="C major",
        sections=_CONFIDENT_SECTIONS,
        provenance=AnalysisProvenance.MEASURED,  # base: every other dimension measured
        field_provenance={"tempo": ProvenanceRecord(tier, method="probe")},
    )
    b = _fully_measured("b.mp3")

    verdict = _assess(a, b)
    assert verdict.is_confident is expect_confident


# --- Guard test 4: no partial-field promotion (the success criterion) ----------


def test_only_tempo_measured_does_not_launder_other_dimensions():
    # A fixture may mark ONLY tempo as MEASURED; key/sections/beatgrid/stems/role
    # stay STUB and the overlay (which decides on all of them) cannot be COMPATIBLE.
    a = _analysis("a.mp3", measured=("tempo",))
    b = _analysis("b.mp3", measured=("tempo",))

    assert a.provenance_of("tempo").tier is MEASURED
    for dim in ("key", "sections", "beatgrid", "stems", "role"):
        assert a.provenance_of(dim).tier is STUB, dim
    assert a.derived_provenance() is AnalysisProvenance.STUB  # not all measured

    verdict = _assess(a, b)
    assert verdict.level is not _LEVEL.COMPATIBLE
    assert not verdict.is_confident
    assert verdict.level is _LEVEL.MAYBE
    assert _has(verdict, "provenance", EvidencePolarity.MISSING)


# --- Guard test 5: overrides set USER_ASSERTED, never MEASURED -----------------


def test_override_sets_user_asserted_not_measured():
    base = _fully_measured("b.mp3")
    overridden = apply_override(
        base,
        ManualOverride(target=OverrideTarget.BPM, reason="user taps 120", bpm_multiplier=1.0),
    )
    # The overridden dimension drops to USER_ASSERTED; untouched dims stay MEASURED.
    assert overridden.provenance_of("tempo").tier is USER_ASSERTED
    assert overridden.provenance_of("key").tier is MEASURED
    # The whole-analysis enum is never touched by an override.
    assert overridden.provenance is AnalysisProvenance.MEASURED


def test_user_asserted_deciding_dimension_caps_at_maybe_with_attribution():
    a = _fully_measured("a.mp3")
    b = apply_override(
        _fully_measured("b.mp3"),
        ManualOverride(target=OverrideTarget.BPM, reason="user taps 120", bpm_multiplier=1.0),
    )

    verdict = _assess(a, b)
    assert verdict.level is _LEVEL.MAYBE
    assert not verdict.is_confident
    # The verdict attributes the user-asserted dimension rather than echoing it
    # back as the tool's own measurement.
    assert any(
        e.dimension == "provenance"
        and e.polarity is EvidencePolarity.CONDITIONAL
        and "override" in e.detail
        for e in verdict.evidence
    )


def test_key_override_alone_still_leaves_overlay_unconfident():
    # Overriding key (but not the still-STUB tempo/sections/...) cannot buy
    # confidence either.
    a = _analysis("a.mp3")
    b = apply_override(
        _analysis("b.mp3"),
        ManualOverride(target=OverrideTarget.KEY, reason="modal fix", key="C major"),
    )
    assert b.provenance_of("key").tier is USER_ASSERTED
    verdict = _assess(a, b)
    assert not verdict.is_confident


# --- Guard test 6: beatgrid is independent of tempo ----------------------------


def test_beatgrid_stub_blocks_overlay_confidence_even_with_tempo_measured():
    # tempo/key/sections/stems measured but beatgrid STUB -> the overlay's
    # phrase-lock premise is unestablished, so no COMPATIBLE.
    a = _analysis("a.mp3", base=AnalysisProvenance.MEASURED, stub=("beatgrid",))
    b = _analysis("b.mp3", base=AnalysisProvenance.MEASURED, stub=("beatgrid",))

    assert a.provenance_of("tempo").tier is MEASURED
    assert a.provenance_of("beatgrid").tier is STUB

    verdict = _assess(a, b)
    assert verdict.level is not _LEVEL.COMPATIBLE
    assert not verdict.is_confident


# --- Guard test 7: roles/collision are not measured without stems --------------


def test_stems_stub_blocks_overlay_confidence():
    # Absent a real separation, the vocal/bass masking failure mode is
    # unassessable, so overlay stays below a confident verdict.
    a = _analysis("a.mp3", base=AnalysisProvenance.MEASURED, stub=("stems",))
    b = _analysis("b.mp3", base=AnalysisProvenance.MEASURED, stub=("stems",))

    assert a.provenance_of("stems").tier is STUB
    verdict = _assess(a, b)
    assert verdict.level is not _LEVEL.COMPATIBLE
    assert not verdict.is_confident


# --- Guard test 8: stub-floor invariant (umbrella), per move -------------------

_CONFIDENT_MOVES = sorted(CONFIDENCE_DECIDING_DIMENSIONS, key=lambda m: m.value)


@pytest.mark.parametrize("move", _CONFIDENT_MOVES, ids=lambda m: m.value)
def test_each_deciding_dimension_is_load_bearing(move):
    # For every move that can be confident, downgrading ANY single deciding
    # dimension on either track to STUB must drop it below confidence.
    for dim in CONFIDENCE_DECIDING_DIMENSIONS[move]:
        a = _analysis("a.mp3", base=AnalysisProvenance.MEASURED, stub=(dim,))
        b = _fully_measured("b.mp3")
        verdict = _assess(a, b, move_type=move)
        assert not verdict.is_confident, f"{move.value} stayed confident with {dim} stubbed on A"

        a2 = _fully_measured("a.mp3")
        b2 = _analysis("b.mp3", base=AnalysisProvenance.MEASURED, stub=(dim,))
        verdict2 = _assess(a2, b2, move_type=move)
        assert not verdict2.is_confident, f"{move.value} stayed confident with {dim} stubbed on B"


@pytest.mark.parametrize("move", _CONFIDENT_MOVES, ids=lambda m: m.value)
def test_all_deciding_dimensions_measured_permits_confidence(move):
    # The positive control: with every deciding dimension MEASURED on both
    # tracks and clean tempo/key, the move IS allowed to be confident. Without
    # this, the load-bearing test above could pass vacuously.
    a = _fully_measured("a.mp3")
    b = _fully_measured("b.mp3")
    verdict = _assess(a, b, move_type=move)
    assert verdict.is_confident
    assert verdict.level is _LEVEL.COMPATIBLE


# --- Substrate integrity: serialization and validation -------------------------


def test_field_provenance_survives_serialization_round_trip():
    # A record must round-trip *whole* — every field, not just tier — or a
    # serialized analysis could silently drop the method/confidence/note that
    # justify (or qualify) its provenance.
    a = _analysis("a.mp3", measured=("tempo",), user_asserted=("key",))
    restored = TrackAnalysis.from_dict(a.to_dict())

    tempo = restored.provenance_of("tempo")
    assert tempo.tier is MEASURED
    assert tempo.method == "fake_backend"
    assert tempo.confidence == 0.8
    assert restored.provenance_of("key").tier is USER_ASSERTED
    assert restored.provenance_of("sections").tier is STUB  # fell back to base tier
    # The whole record, compared field-for-field, is identical after a round trip.
    assert restored.provenance_of("tempo") == a.provenance_of("tempo")

    # A note and a null confidence must also survive intact.
    rec = ProvenanceRecord(
        tier=UNAVAILABLE, method="fake_backend", confidence=None, note="no pulse"
    )
    with_note = TrackAnalysis(
        track=Track(path=Path("b.mp3")),
        bpm=120.0,
        key="C major",
        field_provenance={"tempo": rec},
    )
    restored_note = TrackAnalysis.from_dict(with_note.to_dict()).provenance_of("tempo")
    assert restored_note == rec
    assert restored_note.confidence is None
    assert restored_note.note == "no pulse"


def test_unknown_provenance_dimension_is_rejected():
    # A typo'd dimension key is a silent laundering hole (it gates nothing), so
    # it must be rejected at construction, not accepted and ignored.
    with pytest.raises(ValueError):
        TrackAnalysis(
            track=Track(path=Path("a.mp3")),
            bpm=120.0,
            key="C major",
            field_provenance={"tempoo": ProvenanceRecord(MEASURED)},
        )


def test_provenance_of_rejects_unknown_dimension():
    a = _analysis("a.mp3")
    with pytest.raises(KeyError):
        a.provenance_of("groove")


def test_derived_provenance_is_measured_only_when_all_dimensions_are():
    partial = _analysis("a.mp3", measured=("tempo", "key"))
    assert partial.derived_provenance() is AnalysisProvenance.STUB
    full = _fully_measured("b.mp3")
    assert full.derived_provenance() is AnalysisProvenance.MEASURED
    # A narrowed rollup over only-measured dimensions reads MEASURED.
    assert partial.derived_provenance(("tempo", "key")) is AnalysisProvenance.MEASURED


def test_partial_move_confidence_dimensions_are_empty():
    # hook_collision / rhythmic_graft / genre_contrast_blend have no confidence
    # row: provenance can never lift their PARTIAL cap. Guards the "empty set is
    # not vacuously confident" contract at the table level.
    for move in (
        MashupMoveType.HOOK_COLLISION,
        MashupMoveType.RHYTHMIC_GRAFT,
        MashupMoveType.GENRE_CONTRAST_BLEND,
    ):
        assert move not in CONFIDENCE_DECIDING_DIMENSIONS
        a = _fully_measured("a.mp3")
        b = _fully_measured("b.mp3")
        verdict = _assess(
            a,
            b,
            move_type=move,
            track_a_role=TrackRole.VOCAL,
            track_b_role=TrackRole.INSTRUMENTAL,
        )
        assert not verdict.is_confident
        assert verdict.level is _LEVEL.MAYBE
