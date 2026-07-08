"""Vocal/bass collision penalty scoring.

Design input: docs/Mashup Compatibility Tool Taxonomy.md's "Overlap and
Collision Penalty" section. Pure math over a CollisionProfile — this does
not attempt to detect overlap itself (that needs stem separation, which
doesn't exist yet; see `mashpad.models.CollisionProfile`).

Penalty coefficients (0.4 for vocal overlap, 0.3 for bass overlap) are the
report's example values, kept here as configurable defaults, not
validated constants. Treat them as a starting hypothesis.
"""

from __future__ import annotations

from mashpad.models import CollisionProfile

DEFAULT_VOCAL_COLLISION_WEIGHT = 0.4
DEFAULT_BASS_COLLISION_WEIGHT = 0.3


def score_collision_penalty(
    profile: CollisionProfile,
    vocal_weight: float = DEFAULT_VOCAL_COLLISION_WEIGHT,
    bass_weight: float = DEFAULT_BASS_COLLISION_WEIGHT,
) -> float:
    """Return a penalty in [0, vocal_weight + bass_weight].

    An unmeasured profile (`measured=False`, the v0 default) always scores
    a 0 penalty — "we didn't check" isn't the same as "it's clean," but a
    v0 harness with no stem data has no basis to penalize a pairing for a
    collision it has no way to detect.
    """
    if not profile.measured:
        return 0.0
    return vocal_weight * profile.vocal_overlap_ratio + bass_weight * profile.bass_overlap_ratio
