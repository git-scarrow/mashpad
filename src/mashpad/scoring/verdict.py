"""Evidence-first compatibility verdict — a calibration layer, not a scorer.

`assess_compatibility` turns a `CompatibilityProfile` (plus the two
`TrackAnalysis` inputs) into a `CompatibilityVerdict`: one of COMPATIBLE,
MAYBE, UNLIKELY, or UNCERTAIN, each carrying the evidence that produced it.
It **never** recomputes or re-weights the profile's component scores — it
reinterprets them through an honesty lens and adds the abstention gates the
raw scorer lacks. See docs/compatibility-verdict.md.

The guiding asymmetry: it is easier to *rule out* a mashup (a necessary
condition, like beat-matchability, fails) than to *rule one in* (which needs
sufficient conditions we cannot verify from stubbed analysis). So:

- COMPATIBLE and UNLIKELY are *confident* verdicts. They require MEASURED
  analysis provenance and unambiguous evidence. v0's filename-seeded stubs
  never reach them — a judgment built on placeholder numbers is not evidence
  about the audio.
- MAYBE is a real leaning-yes that is conditional (stub data, a
  partial-support move, a fixable key clash, or a required octave reading).
- UNCERTAIN is an explicit abstention: out-of-scope move, unverified role
  premise, ambiguous tempo, or a compatibility that hinges on a tempo
  override the analyzer itself rates as unlikely.

This makes the system *more* willing to say "uncertain" exactly where the
old path emitted a flattering-but-unsupported composite score.
"""

from __future__ import annotations

from mashpad.models import (
    AnalysisProvenance,
    CompatibilityProfile,
    CompatibilityVerdict,
    CompatibilityVerdictLevel,
    EvidenceItem,
    EvidencePolarity,
    FitLevel,
    MashupMoveType,
    MoveSupportStatus,
    TrackAnalysis,
    TrackRole,
)
from mashpad.scoring.harmonic_score import score_harmonic_fit
from mashpad.scoring.tempo_score import (
    OVERRIDE_CONFIDENCE_FLOOR,
    adjustable_candidates_or_fallback,
    anchor_candidates_or_fallback,
    best_interpretation,
    tempo_interpretations,
    track_tempo_ambiguity,
)

# Moves whose very premise is a vocal/instrumental split. For these, roles
# that don't supply exactly one vocal + one instrumental leave the move
# unverifiable in v0 (no stem separation exists to establish the split).
ROLE_DEPENDENT_MOVES = frozenset(
    {
        MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY,
        MashupMoveType.HOOK_COLLISION,
        MashupMoveType.RHYTHMIC_GRAFT,
    }
)

_LEVEL = CompatibilityVerdictLevel
_POL = EvidencePolarity


def _verdict(
    level: CompatibilityVerdictLevel,
    headline: str,
    evidence: list[EvidenceItem],
    profile: CompatibilityProfile,
) -> CompatibilityVerdict:
    return CompatibilityVerdict(
        level=level,
        headline=headline,
        evidence=tuple(evidence),
        move_type=profile.move_type,
        track_a_role=profile.track_a_role,
        track_b_role=profile.track_b_role,
    )


def _anchor_and_adjustable(
    profile: CompatibilityProfile, analysis_a: TrackAnalysis, analysis_b: TrackAnalysis
) -> tuple[TrackAnalysis, TrackAnalysis, str]:
    """Which analysis anchors tempo — mirrors `evaluate_move`'s rule exactly."""
    if profile.track_b_role is TrackRole.VOCAL and profile.track_a_role is not TrackRole.VOCAL:
        return analysis_b, analysis_a, "A"
    return analysis_a, analysis_b, "B"


def assess_compatibility(
    profile: CompatibilityProfile,
    analysis_a: TrackAnalysis,
    analysis_b: TrackAnalysis,
) -> CompatibilityVerdict:
    """Derive an evidence-first verdict from an already-computed profile."""
    move = profile.move_type
    evidence: list[EvidenceItem] = []

    # --- Gate 1: move support -------------------------------------------------
    if profile.support_status is MoveSupportStatus.OUT_OF_SCOPE:
        evidence.append(
            EvidenceItem(
                "move_support",
                _POL.MISSING,
                f"{move.value} is out of scope for v0 — no compatibility evidence is "
                "computed for it, so there is nothing to judge.",
            )
        )
        return _verdict(
            _LEVEL.UNCERTAIN,
            f"{move.value} is not evaluated in v0 (out of scope).",
            evidence,
            profile,
        )

    partial_move = profile.support_status is MoveSupportStatus.PARTIAL
    if partial_move:
        evidence.append(
            EvidenceItem(
                "move_support",
                _POL.CONDITIONAL,
                f"{move.value} has only partial v0 support: generic tempo/harmonic/phrase "
                "are scored, but this move's own criteria are not modeled, so 'compatible' "
                "cannot be confirmed.",
            )
        )
    else:
        evidence.append(
            EvidenceItem("move_support", _POL.SUPPORTS, f"{move.value} is a v0-supported move.")
        )

    # --- Gate 2: role premise -------------------------------------------------
    roles = (profile.track_a_role, profile.track_b_role)
    if move in ROLE_DEPENDENT_MOVES:
        has_split = TrackRole.VOCAL in roles and TrackRole.INSTRUMENTAL in roles
        if not has_split:
            evidence.append(
                EvidenceItem(
                    "role",
                    _POL.MISSING,
                    f"{move.value} presupposes one vocal and one instrumental track, but the "
                    f"roles given are ({roles[0].value}, {roles[1].value}). With no stem "
                    "separation in v0 the vocal/instrumental split is unverified, so the "
                    "move's premise is not established.",
                )
            )
            return _verdict(
                _LEVEL.UNCERTAIN,
                "The move's role premise is missing or unverified.",
                evidence,
                profile,
            )
        evidence.append(
            EvidenceItem(
                "role",
                _POL.CONDITIONAL,
                "Vocal/instrumental roles are caller-asserted, not verified "
                "(no stem separation in v0).",
            )
        )

    # --- Provenance: is any deciding evidence real? --------------------------
    measured = (
        analysis_a.provenance is AnalysisProvenance.MEASURED
        and analysis_b.provenance is AnalysisProvenance.MEASURED
    )
    if not measured:
        evidence.append(
            EvidenceItem(
                "provenance",
                _POL.MISSING,
                "BPM/key/section values are deterministic stubs (seeded from the file name), "
                "not real-audio measurements — enough to sketch a hypothesis, not to confirm "
                "or rule out compatibility.",
            )
        )

    anchor, adjustable, adj_label = _anchor_and_adjustable(profile, analysis_a, analysis_b)

    # --- Gate 3: a track's own tempo is ambiguous ----------------------------
    # A single track carrying two *competing* readings covers both required
    # false-confidence cases: "value" kind = an ambiguous BPM (e.g. 128 vs
    # 132), "octave" kind = multiple plausible tempo ratios (e.g. 85 vs 170,
    # where the mix could be direct or double-time). Either way the alignment
    # relation is not determined, so we abstain rather than pick one silently.
    for track, label in ((anchor, "anchor"), (adjustable, adj_label)):
        amb = track_tempo_ambiguity(track.tempo_candidates)
        if amb.ambiguous:
            evidence.append(
                EvidenceItem(
                    "tempo",
                    _POL.AMBIGUOUS,
                    f"Song {label}'s tempo is ambiguous: {amb.detail}. The alignment relation "
                    "depends on which reading is correct.",
                )
            )
            return _verdict(
                _LEVEL.UNCERTAIN,
                "Tempo interpretation is ambiguous.",
                evidence,
                profile,
            )

    anchor_candidates, _ = anchor_candidates_or_fallback(anchor.tempo_candidates, anchor.bpm)
    adjustable_candidates, _ = adjustable_candidates_or_fallback(
        adjustable.tempo_candidates, adjustable.bpm
    )
    interpretations = tempo_interpretations(list(anchor_candidates), list(adjustable_candidates))
    within = [i for i in interpretations if i.within_tolerance]
    best = best_interpretation(interpretations)

    # --- Gate 4 + tempo evidence (supports / opposes / conditional / override)
    tempo_opposes = False
    tempo_conditional = False
    if not best.within_tolerance:
        tempo_opposes = True
        evidence.append(
            EvidenceItem(
                "tempo",
                _POL.OPPOSES,
                f"Best tempo alignment is {best.candidate_a.bpm:.1f} vs "
                f"{best.candidate_b.bpm:.1f} BPM ({best.deviation * 100:.1f}% off) — no "
                "1:1, 2:1, or 1:2 relation reconciles them.",
            )
        )
    elif best.relation == "direct":
        evidence.append(
            EvidenceItem(
                "tempo",
                _POL.SUPPORTS,
                f"Tempo aligns directly at ~{best.candidate_a.bpm:.1f} BPM "
                f"({best.deviation * 100:.1f}% deviation).",
            )
        )
    else:
        # A non-direct (half/double-time) alignment. If it leans on a reading the
        # analyzer itself rates as unlikely AND the primary reading does not fit,
        # compatibility hinges on a manual tempo override -> abstain.
        non_primary = (
            best.candidate_b
            if best.candidate_b.multiplier_from_primary != 1.0
            else best.candidate_a
        )
        has_direct_fit = any(i.relation == "direct" for i in within)
        override_required = (
            non_primary.confidence < OVERRIDE_CONFIDENCE_FLOOR and not has_direct_fit
        )
        if override_required:
            evidence.append(
                EvidenceItem(
                    "tempo",
                    _POL.CONDITIONAL,
                    f"Tempo only aligns if a track is treated as "
                    f"{best.relation.replace('_', ' ')} ({non_primary.bpm:.1f} BPM), but the "
                    f"analyzer rates that reading low (confidence {non_primary.confidence:.2f}) "
                    "and the primary reading does not fit — this needs a manual tempo override "
                    "to trust.",
                )
            )
            return _verdict(
                _LEVEL.UNCERTAIN,
                "Compatibility depends on a low-confidence tempo override.",
                evidence,
                profile,
            )
        tempo_conditional = True
        evidence.append(
            EvidenceItem(
                "tempo",
                _POL.CONDITIONAL,
                f"Tempo aligns only via a {best.relation.replace('_', ' ')} reading "
                f"(~{best.candidate_a.bpm:.1f} vs {best.candidate_b.bpm:.1f} BPM) — compatible "
                "if you commit to mixing at that octave.",
            )
        )

    # --- Harmonic + phrase evidence (read from the profile, not recomputed) --
    harmonic_opposes = False
    harmonic = score_harmonic_fit(anchor.key, adjustable.key, adj_label)
    if profile.scores is not None and profile.scores.harmonic_fit in (
        FitLevel.STRONG,
        FitLevel.MODERATE,
    ):
        evidence.append(
            EvidenceItem(
                "harmonic",
                _POL.SUPPORTS,
                f"Keys relate as {harmonic.relation} (harmonically workable).",
            )
        )
    else:
        harmonic_opposes = True
        evidence.append(
            EvidenceItem(
                "harmonic",
                _POL.OPPOSES,
                f"Keys relate as {harmonic.relation} — a clash that needs a pitch shift "
                "to resolve.",
            )
        )

    if profile.scores is not None and profile.scores.phrase_fit is FitLevel.TENTATIVE:
        evidence.append(
            EvidenceItem(
                "phrase",
                _POL.MISSING,
                "Section-boundary confidence is too low (tentative) to support a phrase-level "
                "pairing suggestion.",
            )
        )
    elif profile.scores is not None and profile.scores.phrase_fit is FitLevel.STRONG:
        evidence.append(
            EvidenceItem(
                "phrase", _POL.SUPPORTS, "Section layout is confident enough to align phrases."
            )
        )

    # --- Combine into a verdict ----------------------------------------------
    if tempo_opposes:
        # A necessary condition (beat-matchability) fails. Confident only when
        # the deciding tempo evidence is real; otherwise we cannot even confirm
        # the incompatibility.
        if measured:
            return _verdict(
                _LEVEL.UNLIKELY,
                "Tempos cannot be beat-matched at any octave — unlikely.",
                evidence,
                profile,
            )
        return _verdict(
            _LEVEL.UNCERTAIN,
            "Leaning incompatible, but the tempo evidence is stubbed — cannot confirm.",
            evidence,
            profile,
        )

    conditional = partial_move or tempo_conditional or harmonic_opposes
    if measured and not conditional:
        return _verdict(
            _LEVEL.COMPATIBLE,
            "Tempo and key evidence line up — compatible.",
            evidence,
            profile,
        )
    if measured and conditional:
        return _verdict(
            _LEVEL.MAYBE,
            "Workable, but only under a condition (see conditional evidence).",
            evidence,
            profile,
        )
    return _verdict(
        _LEVEL.MAYBE,
        "Plausible, but not confirmed — analysis is stubbed, not measured.",
        evidence,
        profile,
    )
