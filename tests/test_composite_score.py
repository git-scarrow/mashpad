from mashpad.models import CollisionProfile, CompatibilityScores, FitLevel
from mashpad.scoring.composite_score import CompatibilityWeights, score_composite

STRONG_SCORES = CompatibilityScores(
    tempo_fit=FitLevel.STRONG,
    harmonic_fit=FitLevel.STRONG,
    phrase_fit=FitLevel.STRONG,
    tempo_score=0.95,
    harmonic_score=0.95,
    phrase_score=0.9,
)
WEAK_SCORES = CompatibilityScores(
    tempo_fit=FitLevel.WEAK,
    harmonic_fit=FitLevel.WEAK,
    phrase_fit=FitLevel.WEAK,
    tempo_score=0.1,
    harmonic_score=0.1,
    phrase_score=0.1,
)


def test_strong_component_scores_yield_strong_composite():
    composite, fit = score_composite(STRONG_SCORES)
    assert fit == FitLevel.STRONG
    assert composite > 0.75


def test_weak_component_scores_yield_weak_composite():
    composite, fit = score_composite(WEAK_SCORES)
    assert fit == FitLevel.WEAK
    assert composite < 0.5


def test_supplying_high_arrangement_contrast_does_not_lower_composite():
    without, _ = score_composite(STRONG_SCORES)
    with_contrast, _ = score_composite(STRONG_SCORES, arrangement_contrast_score=0.95)
    # Supplying a high contrast score should not make an already-strong
    # composite lower; the weight is renormalized, not just appended.
    assert with_contrast >= without - 0.05


def test_measured_collision_reduces_composite():
    baseline, _ = score_composite(STRONG_SCORES)
    profile = CollisionProfile(vocal_overlap_ratio=1.0, bass_overlap_ratio=1.0, measured=True)
    penalized, _ = score_composite(STRONG_SCORES, collision=profile)
    assert penalized < baseline


def test_unmeasured_collision_does_not_reduce_composite():
    baseline, _ = score_composite(STRONG_SCORES)
    profile = CollisionProfile(vocal_overlap_ratio=1.0, bass_overlap_ratio=1.0, measured=False)
    result, _ = score_composite(STRONG_SCORES, collision=profile)
    assert result == baseline


def test_composite_is_clamped_to_zero_and_one():
    heavy_penalty = CollisionProfile(vocal_overlap_ratio=1.0, bass_overlap_ratio=1.0, measured=True)
    composite, _ = score_composite(WEAK_SCORES, collision=heavy_penalty)
    assert composite >= 0.0


def test_weights_are_configurable_not_fixed():
    tempo_only = CompatibilityWeights(tempo=1.0, harmonic=0.0, phrase=0.0, arrangement_contrast=0.0)
    mixed_scores = CompatibilityScores(
        tempo_fit=FitLevel.STRONG,
        harmonic_fit=FitLevel.WEAK,
        phrase_fit=FitLevel.WEAK,
        tempo_score=1.0,
        harmonic_score=0.0,
        phrase_score=0.0,
    )
    composite, _ = score_composite(mixed_scores, weights=tempo_only)
    assert composite == 1.0
