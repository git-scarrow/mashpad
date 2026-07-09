"""Evidence-first verdict tests, focused on false-confidence cases.

Each of the five required scenarios is one where the raw composite score
would happily emit a flattering number, but the honest answer is to abstain
(UNCERTAIN) or withhold confidence (MAYBE). The positive cases prove the
harness is not merely always-uncertain: with MEASURED provenance and clean
evidence it will still say COMPATIBLE or UNLIKELY.
"""

from pathlib import Path

from mashpad.models import (
    AnalysisProvenance,
    CompatibilityVerdictLevel,
    EvidencePolarity,
    FitLevel,
    MashupMoveType,
    Section,
    TempoCandidate,
    Track,
    TrackAnalysis,
    TrackRole,
)
from mashpad.scoring import evaluate_move
from mashpad.scoring.verdict import assess_compatibility

MEASURED = AnalysisProvenance.MEASURED
STUB = AnalysisProvenance.STUB

# Confident sections so phrase-fit never muddies a case that is about tempo/role.
_CONFIDENT_SECTIONS = tuple(
    Section(label=label, start_sec=i * 10.0, end_sec=i * 10.0 + 10.0, confidence=0.85)
    for i, label in enumerate(("intro", "verse", "chorus"))
)


def _analysis(
    bpm: float,
    key: str,
    path: str,
    *,
    sections: tuple[Section, ...] = _CONFIDENT_SECTIONS,
    tempo_candidates: tuple[TempoCandidate, ...] = (),
    provenance: AnalysisProvenance = STUB,
) -> TrackAnalysis:
    return TrackAnalysis(
        track=Track(path=Path(path)),
        bpm=bpm,
        key=key,
        sections=sections,
        tempo_candidates=tempo_candidates,
        provenance=provenance,
    )


def _assess(analysis_a, analysis_b, **kwargs):
    profile = evaluate_move(analysis_a, analysis_b, **kwargs)
    return assess_compatibility(profile, analysis_a, analysis_b)


def _has(verdict, dimension, polarity):
    return any(e.dimension == dimension and e.polarity is polarity for e in verdict.evidence)


# --- The five false-confidence cases -------------------------------------------


def test_ambiguous_bpm_abstains():
    # Song B's analyzer is torn between two non-octave BPMs of equal weight.
    anchor = _analysis(
        120.0,
        "C major",
        "a.mp3",
        tempo_candidates=(TempoCandidate(120.0, 0.9),),
        provenance=MEASURED,
    )
    ambiguous = _analysis(
        128.0,
        "C major",
        "b.mp3",
        tempo_candidates=(
            TempoCandidate(128.0, 0.5, 1.0),
            TempoCandidate(133.0, 0.45, 1.04),
        ),
        provenance=MEASURED,
    )

    verdict = _assess(anchor, ambiguous)

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert verdict.abstained
    assert _has(verdict, "tempo", EvidencePolarity.AMBIGUOUS)
    # Even with MEASURED provenance, ambiguity forces abstention.
    assert verdict.caveats


def test_multiple_plausible_tempo_ratios_abstains():
    # Song B is octave-ambiguous (85 vs 170): direct or double-time both defensible.
    anchor = _analysis(
        170.0,
        "C major",
        "a.mp3",
        tempo_candidates=(TempoCandidate(170.0, 0.9),),
        provenance=MEASURED,
    )
    octave_ambiguous = _analysis(
        170.0,
        "C major",
        "b.mp3",
        tempo_candidates=(
            TempoCandidate(170.0, 0.5, 1.0),
            TempoCandidate(85.0, 0.5, 0.5),
        ),
        provenance=MEASURED,
    )

    verdict = _assess(anchor, octave_ambiguous)

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert _has(verdict, "tempo", EvidencePolarity.AMBIGUOUS)
    ambiguity = next(e for e in verdict.evidence if e.polarity is EvidencePolarity.AMBIGUOUS)
    assert "octave" in ambiguity.detail


def test_missing_role_assumption_abstains():
    # vocal_over_instrumental_overlay presupposes a vocal/instrumental split; two
    # full-mix tracks (no stem separation) leave that premise unverified.
    a = _analysis(120.0, "C major", "a.mp3", provenance=MEASURED)
    b = _analysis(120.0, "C major", "b.mp3", provenance=MEASURED)

    verdict = _assess(a, b, track_a_role=TrackRole.FULL_MIX, track_b_role=TrackRole.FULL_MIX)

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert _has(verdict, "role", EvidencePolarity.MISSING)


def test_unsupported_move_type_abstains():
    a = _analysis(120.0, "C major", "a.mp3", provenance=MEASURED)
    b = _analysis(120.0, "C major", "b.mp3", provenance=MEASURED)

    verdict = _assess(a, b, move_type=MashupMoveType.SAMPLE_COLLAGE)

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert _has(verdict, "move_support", EvidencePolarity.MISSING)
    assert "out of scope" in verdict.headline


def test_manual_override_required_abstains():
    # Song B's primary reading (61) does not fit; only its low-confidence
    # double-time reading (122) aligns with the anchor. That match hinges on a
    # manual tempo override the analyzer itself doubts -> abstain.
    anchor = _analysis(
        120.0,
        "C major",
        "a.mp3",
        tempo_candidates=(TempoCandidate(120.0, 0.9),),
        provenance=MEASURED,
    )
    override_needed = _analysis(
        61.0,
        "C major",
        "b.mp3",
        tempo_candidates=(
            TempoCandidate(61.0, 0.7, 1.0),
            TempoCandidate(122.0, 0.2, 2.0),
        ),
        provenance=MEASURED,
    )

    verdict = _assess(anchor, override_needed)

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert _has(verdict, "tempo", EvidencePolarity.CONDITIONAL)
    override = next(e for e in verdict.evidence if e.dimension == "tempo")
    assert "override" in override.detail


# --- The success condition, stated directly ------------------------------------


def test_stub_analysis_withholds_confidence_even_when_composite_is_strong():
    # The exact situation the old path mishandled: clean, agreeable stub inputs
    # that produce a high composite. The score is still STRONG, but the verdict
    # refuses to call it "compatible" because the inputs are placeholders.
    a = _analysis(120.0, "C major", "a.mp3")  # STUB provenance
    b = _analysis(120.0, "C major", "b.mp3")

    profile = evaluate_move(a, b)
    verdict = assess_compatibility(profile, a, b)

    assert profile.composite_fit is FitLevel.STRONG  # the flattering old signal is unchanged
    assert verdict.level is CompatibilityVerdictLevel.MAYBE  # ...but the judgment withholds it
    assert not verdict.is_confident
    assert _has(verdict, "provenance", EvidencePolarity.MISSING)


# --- Proof the harness is not merely always-uncertain --------------------------


def test_measured_clean_pair_is_confidently_compatible():
    a = _analysis(120.0, "C major", "a.mp3", provenance=MEASURED)
    b = _analysis(120.0, "C major", "b.mp3", provenance=MEASURED)

    verdict = _assess(a, b)

    assert verdict.level is CompatibilityVerdictLevel.COMPATIBLE
    assert verdict.is_confident
    assert verdict.supporting_evidence  # a confident call must cite what supports it


def test_measured_irreconcilable_pair_is_confidently_unlikely():
    # 150 vs 90: no 1:1/2:1/1:2 relation reconciles them -> a necessary condition
    # (beat-matchability) fails, which we can confidently reject on measured data.
    a = _analysis(150.0, "C major", "a.mp3", provenance=MEASURED)
    b = _analysis(90.0, "F# major", "b.mp3", provenance=MEASURED)

    verdict = _assess(a, b)

    assert verdict.level is CompatibilityVerdictLevel.UNLIKELY
    assert verdict.is_confident
    assert _has(verdict, "tempo", EvidencePolarity.OPPOSES)


def test_same_irreconcilable_pair_on_stub_data_cannot_confirm_rejection():
    # The identical tempo gap on STUB inputs is only leaning-no: we cannot even
    # confirm the incompatibility from placeholder numbers, so we abstain.
    a = _analysis(150.0, "C major", "a.mp3")
    b = _analysis(90.0, "F# major", "b.mp3")

    verdict = _assess(a, b)

    assert verdict.level is CompatibilityVerdictLevel.UNCERTAIN
    assert not verdict.is_confident


def test_partial_support_move_is_capped_below_compatible():
    a = _analysis(120.0, "C major", "a.mp3", provenance=MEASURED)
    b = _analysis(120.0, "C major", "b.mp3", provenance=MEASURED)

    verdict = _assess(a, b, move_type=MashupMoveType.HOOK_COLLISION)

    assert verdict.level is CompatibilityVerdictLevel.MAYBE
    assert _has(verdict, "move_support", EvidencePolarity.CONDITIONAL)


def test_manual_override_does_not_launder_stub_provenance_into_confidence():
    # A user override corrects a value but must not upgrade confidence: applying
    # the most flattering possible fix (snap B's tempo exactly onto A) to a STUB
    # analysis keeps STUB provenance, so the verdict stays MAYBE, never COMPATIBLE.
    from mashpad.models import ManualOverride, OverrideTarget
    from mashpad.overrides import apply_override

    a = _analysis(120.0, "C major", "a.mp3")  # STUB
    b = _analysis(90.0, "C major", "b.mp3")  # STUB, tempo far from A

    b_fixed = apply_override(
        b,
        ManualOverride(
            target=OverrideTarget.BPM, reason="user taps 120", bpm_multiplier=120.0 / 90.0
        ),
    )

    assert b_fixed.provenance is AnalysisProvenance.STUB  # provenance is not laundered
    verdict = _assess(a, b_fixed)
    assert verdict.level is CompatibilityVerdictLevel.MAYBE
    assert not verdict.is_confident
    assert _has(verdict, "provenance", EvidencePolarity.MISSING)
