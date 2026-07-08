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

Tempo is scored candidate-set-aware via `score_tempo_candidates`, never a
single BPM comparison. Fallback candidates (when a track has no real
`tempo_candidates`) are generated asymmetrically, not identically for both
tracks: the anchor gets exactly one candidate at its nominal BPM (it was
never multiplier-searched even before candidates existed); the adjustable
side gets three, at half/direct/double its nominal BPM, reproducing the
pre-candidate `score_tempo_fit` search space. `CompatibilityProfile`
separates two related-but-distinct tempo facts: `tempo_relation` /
`tempo_explanation` describe the *best pulse relation* found (which
candidate pair matched, e.g. "b_double_time" — a description of what was
selected), while `adjustments` carries the *recommended stretch target*
(e.g. "Stretch B to 140.0 BPM" — an instruction for what to do about it).
"""

from __future__ import annotations

from mashpad.models import (
    MOVE_SUPPORT,
    CollisionProfile,
    CompatibilityProfile,
    CompatibilityScores,
    MashupMoveType,
    MoveSupportStatus,
    TempoCandidate,
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
from mashpad.scoring.tempo_score import TEMPO_MULTIPLIERS, score_tempo_candidates


def _anchor_candidates_or_fallback(
    tempo_candidates: tuple[TempoCandidate, ...], nominal_bpm: float
) -> tuple[tuple[TempoCandidate, ...], bool]:
    """Return `(candidates, used_fallback)` for the anchor track.

    The anchor is never multiplier-expanded (real or fallback) — it's the
    fixed reference the adjustable track's tempo is measured against,
    matching `score_tempo_fit`'s `bpm_a`-is-fixed convention.
    """
    if tempo_candidates:
        return tempo_candidates, False
    return (TempoCandidate(bpm=nominal_bpm, confidence=1.0, multiplier_from_primary=1.0),), True


def _adjustable_candidates_or_fallback(
    tempo_candidates: tuple[TempoCandidate, ...], nominal_bpm: float
) -> tuple[tuple[TempoCandidate, ...], bool]:
    """Return `(candidates, used_fallback)` for the adjustable track.

    Falls back to synthesized half/double/direct candidates at
    `TEMPO_MULTIPLIERS` of the nominal BPM when a track has no
    `tempo_candidates` — this reproduces `score_tempo_fit`'s multiplier
    search exactly when candidate data isn't available, so tracks without
    real octave-ambiguity data don't lose half/double-time matching.
    """
    if tempo_candidates:
        return tempo_candidates, False
    fallback = tuple(
        TempoCandidate(bpm=round(nominal_bpm * m, 4), confidence=1.0, multiplier_from_primary=m)
        for m in TEMPO_MULTIPLIERS
    )
    return fallback, True


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
        anchor_analysis, adjustable_analysis, adjustable_label = analysis_b, analysis_a, "A"
        anchor_key, adjustable_key = analysis_b.key, analysis_a.key
    else:
        anchor_analysis, adjustable_analysis, adjustable_label = analysis_a, analysis_b, "B"
        anchor_key, adjustable_key = analysis_a.key, analysis_b.key

    anchor_candidates, anchor_fallback = _anchor_candidates_or_fallback(
        anchor_analysis.tempo_candidates, anchor_analysis.bpm
    )
    adjustable_candidates, adjustable_fallback = _adjustable_candidates_or_fallback(
        adjustable_analysis.tempo_candidates, adjustable_analysis.bpm
    )
    used_fallback = anchor_fallback or adjustable_fallback

    tempo_result = score_tempo_candidates(
        list(anchor_candidates), list(adjustable_candidates), adjustable_label
    )
    tempo_explanation = tempo_result.explanation
    if used_fallback:
        tempo_explanation = (
            "[fallback: no tempo_candidates on one or both tracks, using nominal BPM only] "
            + tempo_explanation
        )

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
        tempo_relation=tempo_result.relation,
        tempo_explanation=tempo_explanation,
    )
