"""Tempo compatibility scoring, including half/double-time matching.

Real logic (not stubbed): checks the two BPMs at 1x, 0.5x, and 2x
multipliers and scores the best-fitting one, since half/double-time
tempo matches are common and legitimate in mashups.

`score_tempo_fit` compares two nominal BPM scalars. `score_tempo_candidates`
is the candidate-aware sibling: it searches every (candidate_a, candidate_b)
pair, so a track's half/double-time interpretation can win the match instead
of always deferring to its primary BPM. `mashpad.scoring.evaluate_move` uses
the candidate-aware path whenever both tracks have `tempo_candidates`, and
falls back to a synthesized single-candidate list (clearly labeled as a
fallback) when they don't.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.models import AdjustmentRecommendation, FitLevel, TempoCandidate

# Tolerance bands, expressed as a fraction of the target BPM.
STRONG_TOLERANCE = 0.03
MODERATE_TOLERANCE = 0.08

TEMPO_MULTIPLIERS = (1.0, 0.5, 2.0)


def _deviation_to_score_fit(deviation: float) -> tuple[float, FitLevel]:
    if deviation <= STRONG_TOLERANCE:
        fit = FitLevel.STRONG
        score = 1.0 - (deviation / STRONG_TOLERANCE) * 0.15
    elif deviation <= MODERATE_TOLERANCE:
        fit = FitLevel.MODERATE
        span = MODERATE_TOLERANCE - STRONG_TOLERANCE
        score = 0.85 - (deviation - STRONG_TOLERANCE) / span * 0.35
    else:
        fit = FitLevel.WEAK
        score = max(0.05, 0.5 - deviation)
    return score, fit


@dataclass(frozen=True, slots=True)
class TempoScoreResult:
    score: float
    fit: FitLevel
    multiplier: float  # which of TEMPO_MULTIPLIERS produced the best fit
    adjusted_bpm_b: float
    adjustments: tuple[AdjustmentRecommendation, ...] = ()


@dataclass(frozen=True, slots=True)
class TempoMatch:
    """Result of matching two tracks' *candidate sets* rather than one BPM each.

    `relation` names which side's candidate (if either) was a half/double-time
    interpretation relative to that track's own primary candidate
    (`TempoCandidate.multiplier_from_primary == 1.0`): `direct`,
    `a_half_time`, `a_double_time`, `b_half_time`, `b_double_time`, or
    `unresolved` when both selected candidates are non-primary. `"a"`/`"b"`
    refer to whichever candidate list was passed first/second — callers
    that anchor on a role (e.g. `evaluate_move`) pass the anchor track's
    candidates first, so `required_stretch_ratio` and the deviation score
    stay normalized against the anchor, consistent with `score_tempo_fit`.
    """

    score: float
    fit: FitLevel
    selected_bpm_a: float
    selected_bpm_b: float
    relation: str
    required_stretch_ratio: float
    explanation: str
    adjustments: tuple[AdjustmentRecommendation, ...] = ()


def _relation_label(candidate_a: TempoCandidate, candidate_b: TempoCandidate) -> str:
    a_is_primary = candidate_a.multiplier_from_primary == 1.0
    b_is_primary = candidate_b.multiplier_from_primary == 1.0

    if a_is_primary and b_is_primary:
        return "direct"
    if b_is_primary and not a_is_primary:
        return "a_double_time" if candidate_a.multiplier_from_primary > 1.0 else "a_half_time"
    if a_is_primary and not b_is_primary:
        return "b_double_time" if candidate_b.multiplier_from_primary > 1.0 else "b_half_time"
    return "unresolved"


def score_tempo_candidates(
    candidates_a: list[TempoCandidate],
    candidates_b: list[TempoCandidate],
    adjustable_label: str = "B",
) -> TempoMatch:
    """Find the best-fitting pair across two tracks' candidate tempo sets.

    Contract:

    - Evaluates every `(candidate_a, candidate_b)` combination — an
      exhaustive search, not a greedy or primary-only comparison.
    - Selects the pair with the lowest tempo deviation, which is
      equivalent to the highest-scoring pair: `_deviation_to_score_fit` is
      monotonically non-increasing in deviation, so minimizing deviation
      always maximizes (or ties) score. Ties are broken toward the pair
      with the higher combined candidate confidence.
    - Preserves the winning pair's BPMs verbatim as `selected_bpm_a` /
      `selected_bpm_b` (never averaged or re-derived).
    - Exposes `required_stretch_ratio` (`selected_bpm_a / selected_bpm_b`)
      as the residual stretch needed after picking that pair.
    - Does *not* itself know whether its inputs were real candidates or a
      synthesized fallback — that distinction belongs to the caller (see
      `mashpad.scoring.evaluate_move`, which prefixes
      `CompatibilityProfile.tempo_explanation` with `[fallback: ...]`
      when either side lacked real `tempo_candidates`).
    - A wide, unrelated tempo gap stays weak even with a full
      half/direct/double candidate set on both sides: the exhaustive
      search only rescues a match if some actual candidate pair is close,
      it doesn't relax tolerance just because candidates exist (see
      `test_no_valid_candidate_interpretation_stays_weak` and
      `test_evaluate_move_does_not_overfit_a_wide_tempo_gap`).

    Deviation is normalized against `candidate_a.bpm`, the same convention
    as `score_tempo_fit`'s `bpm_a` anchor, so a track's half/double-time
    interpretation can win the match without the caller having to
    pre-select a single BPM.
    """
    if not candidates_a or not candidates_b:
        raise ValueError("candidate lists must be non-empty")

    pairs = [(ca, cb) for ca in candidates_a for cb in candidates_b]
    candidate_a, candidate_b = min(
        pairs,
        key=lambda pair: (
            abs(pair[0].bpm - pair[1].bpm) / pair[0].bpm,
            -(pair[0].confidence + pair[1].confidence),
        ),
    )
    deviation = abs(candidate_a.bpm - candidate_b.bpm) / candidate_a.bpm
    score, fit = _deviation_to_score_fit(deviation)
    relation = _relation_label(candidate_a, candidate_b)
    stretch_ratio = candidate_a.bpm / candidate_b.bpm if candidate_b.bpm else float("inf")

    explanation = (
        f"Selected {candidate_a.bpm:.1f} BPM vs {candidate_b.bpm:.1f} BPM (relation={relation})"
    )

    adjustments = []
    if relation.startswith("a_"):
        adjustments.append(
            AdjustmentRecommendation(
                f"Treat Song A as half/double-time: "
                f"{candidate_a.multiplier_from_primary}x -> {candidate_a.bpm:.1f} BPM"
            )
        )
    elif relation.startswith("b_"):
        adjustments.append(
            AdjustmentRecommendation(
                f"Treat Song B as half/double-time: "
                f"{candidate_b.multiplier_from_primary}x -> {candidate_b.bpm:.1f} BPM"
            )
        )
    if abs(candidate_a.bpm - candidate_b.bpm) > 0.05:
        adjustments.append(
            AdjustmentRecommendation(f"Stretch {adjustable_label} to {candidate_a.bpm:.1f} BPM")
        )

    return TempoMatch(
        score=round(score, 4),
        fit=fit,
        selected_bpm_a=candidate_a.bpm,
        selected_bpm_b=candidate_b.bpm,
        relation=relation,
        required_stretch_ratio=round(stretch_ratio, 4),
        explanation=explanation,
        adjustments=tuple(adjustments),
    )


def score_tempo_fit(bpm_a: float, bpm_b: float, adjustable_label: str = "B") -> TempoScoreResult:
    """Score tempo fit, treating `bpm_a` as the anchor and `bpm_b` as adjustable.

    `adjustable_label` names whichever track is being stretched in the
    generated adjustment text (defaults to "B" for the historical
    A-anchors-B behavior). Callers that know track roles — e.g.
    `mashpad.scoring.evaluate_move`, which anchors on the `vocal`-role
    track since vocals tolerate far less stretch than instrumentals —
    pass `bpm_a` as the vocal-role BPM and label the instrumental-role
    track accordingly. This also makes the *deviation ratio* itself
    asymmetric (it's normalized by `bpm_a`), not just the wording.

    This is the single-BPM sibling of `score_tempo_candidates`; prefer that
    function when both tracks have `TrackAnalysis.tempo_candidates`.
    """
    if bpm_a <= 0 or bpm_b <= 0:
        raise ValueError("BPM values must be positive")

    candidates = []
    for multiplier in TEMPO_MULTIPLIERS:
        adjusted_b = bpm_b * multiplier
        deviation = abs(adjusted_b - bpm_a) / bpm_a
        candidates.append((deviation, multiplier, adjusted_b))
    deviation, multiplier, adjusted_b = min(candidates, key=lambda c: c[0])

    score, fit = _deviation_to_score_fit(deviation)

    adjustments = []
    if multiplier != 1.0:
        adjustments.append(
            AdjustmentRecommendation(
                f"Treat Song {adjustable_label} as half/double-time: "
                f"{multiplier}x -> {adjusted_b:.1f} BPM"
            )
        )
    if abs(bpm_a - adjusted_b) > 0.05:
        adjustments.append(
            AdjustmentRecommendation(f"Stretch {adjustable_label} to {bpm_a:.1f} BPM")
        )

    return TempoScoreResult(
        score=round(score, 4),
        fit=fit,
        multiplier=multiplier,
        adjusted_bpm_b=adjusted_b,
        adjustments=tuple(adjustments),
    )


# ---------------------------------------------------------------------------
# Candidate synthesis + interpretation analysis
#
# The fallback helpers below are the single source of truth for how a track
# with no real `tempo_candidates` is expanded into a candidate set. Both the
# scorer (`mashpad.scoring.evaluate_move`) and the evidence/verdict layer
# (`mashpad.scoring.verdict`) import them so the two never drift.
# ---------------------------------------------------------------------------


def anchor_candidates_or_fallback(
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


def adjustable_candidates_or_fallback(
    tempo_candidates: tuple[TempoCandidate, ...], nominal_bpm: float
) -> tuple[tuple[TempoCandidate, ...], bool]:
    """Return `(candidates, used_fallback)` for the adjustable track.

    Falls back to synthesized half/double/direct candidates at
    `TEMPO_MULTIPLIERS` of the nominal BPM when a track has no
    `tempo_candidates`, reproducing `score_tempo_fit`'s multiplier search
    exactly. Note the synthesized candidates all carry confidence 1.0: a
    fallback is a *structural* search space, not an ambiguity signal, so
    the verdict layer must never mine fallback candidates for ambiguity
    (it reads ambiguity from a track's real `tempo_candidates` only).
    """
    if tempo_candidates:
        return tempo_candidates, False
    fallback = tuple(
        TempoCandidate(bpm=round(nominal_bpm * m, 4), confidence=1.0, multiplier_from_primary=m)
        for m in TEMPO_MULTIPLIERS
    )
    return fallback, True


# --- Honesty gates for the verdict layer -----------------------------------
#
# These are NOT score weights and are not tuned to make pairings look
# better. They are thresholds for *withholding* confidence: when tempo
# evidence is too ambiguous, or leans on a reading the analyzer itself
# rates as unlikely, the verdict layer abstains rather than emit a number.
AMBIGUITY_CONFIDENCE_FLOOR = 0.2  # a candidate weaker than this can't create ambiguity
COMPARABLE_CONFIDENCE_RATIO = 0.6  # two candidates "compete" when min/max confidence >= this
OCTAVE_RATIO_TOLERANCE = 0.06  # a bpm ratio within this of 2.0 counts as an octave pair
VALUE_AMBIGUITY_MIN_RATIO = 1.02  # below this, two candidates are effectively the same BPM
OVERRIDE_CONFIDENCE_FLOOR = (
    0.3  # a *fitting* non-primary reading weaker than this needs an override
)


@dataclass(frozen=True, slots=True)
class TempoInterpretation:
    """One (candidate_a, candidate_b) alignment and whether it fits."""

    relation: str
    candidate_a: TempoCandidate
    candidate_b: TempoCandidate
    deviation: float
    fit: FitLevel
    within_tolerance: bool

    @property
    def combined_confidence(self) -> float:
        return self.candidate_a.confidence + self.candidate_b.confidence


def tempo_interpretations(
    candidates_a: list[TempoCandidate],
    candidates_b: list[TempoCandidate],
    tolerance: float = MODERATE_TOLERANCE,
) -> list[TempoInterpretation]:
    """Every candidate-pair alignment, each tagged with its relation and fit.

    Deviation is normalized against `candidate_a.bpm` (the anchor), the same
    convention as `score_tempo_candidates`. `within_tolerance` marks pairs
    close enough to count as a plausible alignment.
    """
    if not candidates_a or not candidates_b:
        raise ValueError("candidate lists must be non-empty")

    interpretations = []
    for ca in candidates_a:
        for cb in candidates_b:
            deviation = abs(ca.bpm - cb.bpm) / ca.bpm
            _, fit = _deviation_to_score_fit(deviation)
            interpretations.append(
                TempoInterpretation(
                    relation=_relation_label(ca, cb),
                    candidate_a=ca,
                    candidate_b=cb,
                    deviation=deviation,
                    fit=fit,
                    within_tolerance=deviation <= tolerance,
                )
            )
    return interpretations


def best_interpretation(interpretations: list[TempoInterpretation]) -> TempoInterpretation:
    """The lowest-deviation interpretation (ties toward higher combined confidence).

    Same selection contract as `score_tempo_candidates`.
    """
    return min(
        interpretations,
        key=lambda i: (i.deviation, -i.combined_confidence),
    )


@dataclass(frozen=True, slots=True)
class TrackTempoAmbiguity:
    """Whether a single track's own candidate set is internally ambiguous."""

    ambiguous: bool
    kind: str | None = None  # "octave" (multiple plausible ratios) | "value" (competing BPMs)
    detail: str = ""


def track_tempo_ambiguity(candidates: tuple[TempoCandidate, ...]) -> TrackTempoAmbiguity:
    """Detect when a track has two *competing* tempo readings of its own.

    Only real candidate sets should be passed here (never the synthesized
    fallback, whose confidences are all 1.0). Two candidates are competing
    when both clear `AMBIGUITY_CONFIDENCE_FLOOR` and neither dominates the
    other (`COMPARABLE_CONFIDENCE_RATIO`). Their BPM ratio then classifies
    the ambiguity:

    - ~2.0 -> "octave": e.g. 85 vs 170 both plausible primary readings, so
      the octave (and thus the mix ratio) is unresolved.
    - between "same BPM" and an octave -> "value": e.g. 128 vs 132, two
      genuinely different tempo estimates.

    A normal candidate set with one dominant primary (like the stub's
    0.6/0.25/0.15 split) is *not* flagged — the primary clearly wins.
    """
    strong = [c for c in candidates if c.confidence >= AMBIGUITY_CONFIDENCE_FLOOR]
    for i in range(len(strong)):
        for j in range(i + 1, len(strong)):
            c1, c2 = strong[i], strong[j]
            lo_conf, hi_conf = sorted((c1.confidence, c2.confidence))
            if hi_conf == 0 or lo_conf / hi_conf < COMPARABLE_CONFIDENCE_RATIO:
                continue  # one reading clearly dominates -> not ambiguous
            lo_bpm, hi_bpm = sorted((c1.bpm, c2.bpm))
            if lo_bpm <= 0:
                continue
            ratio = hi_bpm / lo_bpm
            if abs(ratio - 2.0) <= OCTAVE_RATIO_TOLERANCE:
                return TrackTempoAmbiguity(
                    True,
                    "octave",
                    f"{lo_bpm:.1f} and {hi_bpm:.1f} BPM are both plausible primary "
                    "readings (octave-ambiguous)",
                )
            if VALUE_AMBIGUITY_MIN_RATIO <= ratio < (2.0 - OCTAVE_RATIO_TOLERANCE):
                return TrackTempoAmbiguity(
                    True,
                    "value",
                    f"{lo_bpm:.1f} and {hi_bpm:.1f} BPM are competing tempo estimates",
                )
    return TrackTempoAmbiguity(False)
