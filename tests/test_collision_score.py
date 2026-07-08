from mashpad.models import CollisionProfile
from mashpad.scoring.collision_score import score_collision_penalty


def test_unmeasured_profile_has_no_penalty():
    profile = CollisionProfile(vocal_overlap_ratio=0.9, bass_overlap_ratio=0.9, measured=False)
    assert score_collision_penalty(profile) == 0.0


def test_measured_overlap_penalizes_by_weight():
    profile = CollisionProfile(vocal_overlap_ratio=0.5, bass_overlap_ratio=0.5, measured=True)
    penalty = score_collision_penalty(profile, vocal_weight=0.4, bass_weight=0.3)
    assert penalty == 0.5 * 0.4 + 0.5 * 0.3


def test_no_overlap_has_no_penalty_even_when_measured():
    profile = CollisionProfile(vocal_overlap_ratio=0.0, bass_overlap_ratio=0.0, measured=True)
    assert score_collision_penalty(profile) == 0.0
