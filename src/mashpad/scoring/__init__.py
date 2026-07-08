"""Compatibility scoring orchestration.

`evaluate_move` is the top-level entry point: given two TrackAnalysis
objects, a move type, and a role assignment, it produces a
CompatibilityProfile. Compatibility is asymmetric by construction — the
`vocal`-role track is always treated as the tempo/key anchor (vocals
tolerate far less stretch/shift than instrumentals per the research
report), so swapping track_a_role/track_b_role for the same two analyses
is a genuinely different evaluation, not just relabeled output.

Out-of-scope move types (see MOVE_SUPPORT in mashpad.models) return a
CompatibilityProfile with no score at all, rather than a fabricated
number — see docs/mashup-move-taxonomy.md.
"""

from __future__ import annotations

from mashpad.models import (
    MOVE_SUPPORT,
    CollisionProfile,
    CompatibilityProfile,
    CompatibilityScores,
    MashupMoveType,
    MoveSupportStatus,
    TrackAnalysis,
    TrackRole,
)
from mashpad.scoring.composite_score import (
    DEFAULT_WEIGHTS,
    CompatibilityWeights,
    score_composite,
)
from mashpad.scoring.harmonic_score import score_harmonic_fit
from mashpad.scoring.phrase_score import score_phrase_fit
from mashpad.scoring.tempo_score import score_tempo_fit


def evaluate_move(
    analysis_a: TrackAnalysis,
    analysis_b: TrackAnalysis,
    *,
    move_type: MashupMoveType = MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY,
    track_a_role: TrackRole = TrackRole.VOCAL,
    track_b_role: TrackRole = TrackRole.INSTRUMENTAL,
    arrangement_contrast_score: float | None = None,
    collision: CollisionProfile | None = None,
    weights: CompatibilityWeights = DEFAULT_WEIGHTS,
) -> CompatibilityProfile:
    support_status = MOVE_SUPPORT[move_type]
    collision = collision or CollisionProfile()

    if support_status is MoveSupportStatus.OUT_OF_SCOPE:
        return CompatibilityProfile(
            move_type=move_type,
            track_a_role=track_a_role,
            track_b_role=track_b_role,
            support_status=support_status,
            scores=None,
            composite_score=None,
            composite_fit=None,
            collision=collision,
            note=f"{move_type.value} is out of scope for v0 — not scored.",
        )

    # The vocal-role track anchors tempo/key; the instrumental-role track
    # (higher stretch/shift tolerance, per the research report) is the one
    # adjustments target. If neither/both roles are `vocal` (e.g. two
    # FULL_MIX tracks), default to anchoring on A, matching the original
    # A-anchors-B behavior.
    if track_b_role is TrackRole.VOCAL and track_a_role is not TrackRole.VOCAL:
        anchor_bpm, adjustable_bpm, adjustable_label = analysis_b.bpm, analysis_a.bpm, "A"
        anchor_key, adjustable_key = analysis_b.key, analysis_a.key
    else:
        anchor_bpm, adjustable_bpm, adjustable_label = analysis_a.bpm, analysis_b.bpm, "B"
        anchor_key, adjustable_key = analysis_a.key, analysis_b.key

    tempo_result = score_tempo_fit(anchor_bpm, adjustable_bpm, adjustable_label)
    harmonic_result = score_harmonic_fit(anchor_key, adjustable_key, adjustable_label)
    phrase_result = score_phrase_fit(list(analysis_a.sections), list(analysis_b.sections))

    scores = CompatibilityScores(
        tempo_fit=tempo_result.fit,
        harmonic_fit=harmonic_result.fit,
        phrase_fit=phrase_result.fit,
        tempo_score=tempo_result.score,
        harmonic_score=harmonic_result.score,
        phrase_score=phrase_result.score,
    )
    adjustments = tuple(tempo_result.adjustments) + tuple(harmonic_result.adjustments)

    composite_score, composite_fit = score_composite(
        scores,
        arrangement_contrast_score=arrangement_contrast_score,
        collision=collision,
        weights=weights,
    )

    note = (
        ""
        if support_status is MoveSupportStatus.SUPPORTED
        else (
            f"{move_type.value} has partial v0 support: tempo/harmonic/phrase are real, "
            "move-specific criteria (see docs/mashup-move-taxonomy.md) are not modeled yet."
        )
    )

    return CompatibilityProfile(
        move_type=move_type,
        track_a_role=track_a_role,
        track_b_role=track_b_role,
        support_status=support_status,
        scores=scores,
        composite_score=composite_score,
        composite_fit=composite_fit,
        arrangement_contrast_score=arrangement_contrast_score,
        collision=collision,
        adjustments=adjustments,
        note=note,
    )
