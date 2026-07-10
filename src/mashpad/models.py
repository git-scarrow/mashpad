"""Core data model shared across analysis, scoring, and reporting.

Kept as plain dataclasses (no external schema library) so this module has
zero runtime dependencies. `to_dict`/`from_dict` on TrackAnalysis are the
seam that lets tests and future fixture-driven tooling build a full
analysis without touching the filesystem or the (currently stubbed)
analyzers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class FitLevel(StrEnum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    TENTATIVE = "tentative"


class MashupMoveType(StrEnum):
    """Structural mashup move types. See docs/mashup-move-taxonomy.md."""

    VOCAL_OVER_INSTRUMENTAL_OVERLAY = "vocal_over_instrumental_overlay"
    HOOK_COLLISION = "hook_collision"
    RHYTHMIC_GRAFT = "rhythmic_graft"
    GENRE_CONTRAST_BLEND = "genre_contrast_blend"
    TRANSITION_BLEND = "transition_blend"
    HARMONIC_REINTERPRETATION = "harmonic_reinterpretation"
    LYRICAL_CONCEPTUAL_JUXTAPOSITION = "lyrical_conceptual_juxtaposition"
    SAMPLE_COLLAGE = "sample_collage"


class MoveSupportStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    OUT_OF_SCOPE = "out_of_scope"


# Keep in sync with the status summary table in docs/mashup-move-taxonomy.md.
MOVE_SUPPORT: dict[MashupMoveType, MoveSupportStatus] = {
    MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY: MoveSupportStatus.SUPPORTED,
    MashupMoveType.TRANSITION_BLEND: MoveSupportStatus.SUPPORTED,
    MashupMoveType.HOOK_COLLISION: MoveSupportStatus.PARTIAL,
    MashupMoveType.RHYTHMIC_GRAFT: MoveSupportStatus.PARTIAL,
    MashupMoveType.GENRE_CONTRAST_BLEND: MoveSupportStatus.PARTIAL,
    MashupMoveType.HARMONIC_REINTERPRETATION: MoveSupportStatus.OUT_OF_SCOPE,
    MashupMoveType.LYRICAL_CONCEPTUAL_JUXTAPOSITION: MoveSupportStatus.OUT_OF_SCOPE,
    MashupMoveType.SAMPLE_COLLAGE: MoveSupportStatus.OUT_OF_SCOPE,
}


class TrackRole(StrEnum):
    """The role a track plays within a specific mashup move.

    Compatibility is asymmetric: Track A as `vocal` over Track B as
    `instrumental` is a different move than the roles reversed, and scores
    differently (see `mashpad.scoring.evaluate_move`). `FULL_MIX` is the
    honest v0 default when no stem separation has been performed, i.e.
    roles are an assumption, not a measurement.
    """

    VOCAL = "vocal"
    INSTRUMENTAL = "instrumental"
    FULL_MIX = "full_mix"


@dataclass(frozen=True, slots=True)
class Track:
    path: Path
    title: str | None = None

    @property
    def name(self) -> str:
        return self.title or self.path.stem


@dataclass(frozen=True, slots=True)
class Section:
    label: str
    start_sec: float
    end_sec: float
    confidence: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start_sec": self.start_sec,
            "end_sec": self.end_sec,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Section:
        return cls(
            label=data["label"],
            start_sec=float(data["start_sec"]),
            end_sec=float(data["end_sec"]),
            confidence=float(data["confidence"]),
        )


@dataclass(frozen=True, slots=True)
class TempoCandidate:
    """One plausible tempo interpretation for a track.

    A single BPM scalar hides octave ambiguity (the report's "octave
    error" failure mode: a beat tracker misreading half- or double-time).
    `TrackAnalysis.tempo_candidates` lets a track carry multiple ranked
    interpretations instead of asserting one number as ground truth.
    """

    bpm: float
    confidence: float
    multiplier_from_primary: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bpm": self.bpm,
            "confidence": self.confidence,
            "multiplier_from_primary": self.multiplier_from_primary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TempoCandidate:
        return cls(
            bpm=float(data["bpm"]),
            confidence=float(data["confidence"]),
            multiplier_from_primary=float(data.get("multiplier_from_primary", 1.0)),
        )


class AnalysisProvenance(StrEnum):
    """Where a `TrackAnalysis`'s values came from — the coarse whole-analysis view.

    v0 only produces `STUB` — deterministic placeholders seeded from the
    file *name*, not derived from audio content (see `mashpad.analysis`).
    A real analysis backend would set `MEASURED`. The compatibility verdict
    layer (`mashpad.scoring.verdict`) treats this as a first-class honesty
    signal: a *confident* verdict (COMPATIBLE / UNLIKELY) is withheld unless
    the deciding evidence is measured, because a judgment built on
    filename-seeded placeholders is not evidence about the actual audio.

    As of the provenance-contract substrate this is the **base tier**: it
    supplies the fallback for any dimension without an explicit
    `ProvenanceRecord` in `TrackAnalysis.field_provenance`, and
    `TrackAnalysis.derived_provenance()` recomputes it as a min-tier rollup.
    Field-level `ProvenanceTier` is the finer axis a real analyzer flips one
    dimension at a time; this enum stays for display and back-compat.
    """

    STUB = "stub"
    MEASURED = "measured"


class ProvenanceTier(StrEnum):
    """Per-dimension trust in how one analysis value was produced.

    Finer-grained than `AnalysisProvenance` (which stays a whole-analysis
    STUB/MEASURED rollup for display/back-compat). Only `MEASURED` — a real
    method run on decoded audio — qualifies a *deciding* dimension for a
    confident COMPATIBLE/UNLIKELY verdict; the other three tiers explicitly do
    not, no matter how high a `confidence` accompanies them. In particular
    `UNAVAILABLE` (a real method attempted and failed) and `USER_ASSERTED` (a
    human's claim) are *not* stronger evidence than `STUB` for confidence: all
    three fail the gate identically, and only `MEASURED` passes. See
    docs/design-memo-analyzer-provenance-contract.md.

    **Trust is not encoded by member order.** This is a `StrEnum`, so `<`/`>`
    fall back to *string* comparison ("stub" > "measured" alphabetically —
    the opposite of trust), which is meaningless here. Never rank tiers with
    comparisons; gate on identity/membership (`tier is MEASURED`,
    `MEASURED not in {...}`), as every caller in this codebase does.
    `derived_provenance` is conservative for exactly this reason: it uses
    `all(... is MEASURED)`, independent of any ordering.
    """

    STUB = "stub"  # filename-seeded placeholder; never touched the audio
    UNAVAILABLE = "unavailable"  # a real method was attempted and failed; no value trusted
    USER_ASSERTED = "user_asserted"  # human-supplied (manual override): a claim, not a measurement
    MEASURED = "measured"  # a real method decoded audio and produced it


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Provenance of a single analysis dimension.

    `tier` is the trust axis; `method` names the estimator/backend (or
    "stub"/"manual_override"). `confidence` is the method's own
    self-consistency, kept deliberately separate from `tier` — it is NOT a
    calibrated probability and NEVER promotes a tier (librosa reported 123 BPM
    at confidence 0.92 on pulseless pink noise). `note` is a short
    human-readable explanation.
    """

    tier: ProvenanceTier
    method: str = "stub"
    confidence: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "method": self.method,
            "confidence": self.confidence,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceRecord:
        raw_conf = data.get("confidence")
        return cls(
            tier=ProvenanceTier(data["tier"]),
            method=data.get("method", "stub"),
            confidence=None if raw_conf is None else float(raw_conf),
            note=data.get("note", ""),
        )


# Analysis dimensions that carry independent field-level provenance. `tempo`
# and `beatgrid` are deliberately separate: "how fast" does not imply "where
# the beats are" (see docs/design-memo-analyzer-provenance-contract.md).
PROVENANCE_DIMENSIONS: tuple[str, ...] = (
    "tempo",
    "beatgrid",
    "key",
    "sections",
    "stems",
    "role",
)


@dataclass(frozen=True, slots=True)
class TrackAnalysis:
    track: Track
    bpm: float
    key: str
    sections: tuple[Section, ...] = field(default_factory=tuple)
    tempo_candidates: tuple[TempoCandidate, ...] = field(default_factory=tuple)
    provenance: AnalysisProvenance = AnalysisProvenance.STUB
    # Per-dimension provenance. Any dimension without an explicit record falls
    # back to the whole-analysis `provenance` above (the base tier), so this
    # can stay empty for stub/legacy analyses while a real analyzer flips one
    # dimension at a time. Keys must be in PROVENANCE_DIMENSIONS.
    field_provenance: dict[str, ProvenanceRecord] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.field_provenance) - set(PROVENANCE_DIMENSIONS)
        if unknown:
            raise ValueError(
                f"unknown provenance dimension(s): {sorted(unknown)}; "
                f"valid dimensions are {PROVENANCE_DIMENSIONS}"
            )

    def provenance_of(self, dimension: str) -> ProvenanceRecord:
        """Provenance of one dimension: an explicit field-level record if set,
        else the whole-analysis base tier (`provenance`) as a fallback.

        This is the single seam the verdict layer reads — never the coarse
        `provenance` enum directly — so a real analyzer can flip one dimension
        to MEASURED without laundering the others.
        """
        if dimension not in PROVENANCE_DIMENSIONS:
            raise KeyError(f"unknown provenance dimension: {dimension!r}")
        record = self.field_provenance.get(dimension)
        if record is not None:
            return record
        if self.provenance is AnalysisProvenance.MEASURED:
            return ProvenanceRecord(tier=ProvenanceTier.MEASURED, method="legacy")
        return ProvenanceRecord(tier=ProvenanceTier.STUB, method="stub")

    def derived_provenance(
        self, dimensions: tuple[str, ...] = PROVENANCE_DIMENSIONS
    ) -> AnalysisProvenance:
        """Min-tier rollup of `dimensions` into the coarse display enum:
        MEASURED only if every named dimension is MEASURED, else STUB.

        This is a legacy/display compatibility view of the old whole-analysis
        enum — a derived signal, never a stored source of truth, and **not**
        consulted by the verdict's confidence gate. `assess_compatibility`
        keys COMPATIBLE/UNLIKELY off field-level `provenance_of(dim).tier`
        directly (per-move deciding dimensions), never this rollup, so the
        gate cannot be widened or narrowed by which dimensions a caller rolls
        up here.
        """
        all_measured = all(
            self.provenance_of(d).tier is ProvenanceTier.MEASURED for d in dimensions
        )
        return AnalysisProvenance.MEASURED if all_measured else AnalysisProvenance.STUB

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": {"path": str(self.track.path), "title": self.track.title},
            "bpm": self.bpm,
            "key": self.key,
            "sections": [s.to_dict() for s in self.sections],
            "tempo_candidates": [t.to_dict() for t in self.tempo_candidates],
            "provenance": self.provenance.value,
            "field_provenance": {dim: rec.to_dict() for dim, rec in self.field_provenance.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrackAnalysis:
        track_data = data["track"]
        track = Track(path=Path(track_data["path"]), title=track_data.get("title"))
        sections = tuple(Section.from_dict(s) for s in data.get("sections", []))
        tempo_candidates = tuple(
            TempoCandidate.from_dict(t) for t in data.get("tempo_candidates", [])
        )
        field_provenance = {
            dim: ProvenanceRecord.from_dict(rec)
            for dim, rec in data.get("field_provenance", {}).items()
        }
        return cls(
            track=track,
            bpm=float(data["bpm"]),
            key=data["key"],
            sections=sections,
            tempo_candidates=tempo_candidates,
            provenance=AnalysisProvenance(data.get("provenance", AnalysisProvenance.STUB.value)),
            field_provenance=field_provenance,
        )


class OverrideTarget(StrEnum):
    BPM = "bpm"
    KEY = "key"
    DOWNBEAT = "downbeat"
    PHRASE_BOUNDARY = "phrase_boundary"
    STEM_GAIN = "stem_gain"


@dataclass(frozen=True, slots=True)
class ManualOverride:
    """A user correction to a stubbed/estimated analysis value.

    First-class because every automated estimate here (and every real
    MIR estimate later) is expected to be wrong sometimes: octave errors
    on tempo, modal ambiguity on key, phase-shifted downbeats, drifted
    phrase boundaries, and — once stems exist — bleed that needs a gain
    trim. Only the fields relevant to `target` are expected to be set;
    the rest stay at their default (None).
    """

    target: OverrideTarget
    reason: str
    bpm_multiplier: float | None = None
    key: str | None = None
    downbeat_shift_beats: float | None = None
    phrase_boundary_shift_sec: float | None = None
    stem: str | None = None
    gain_db: float | None = None


@dataclass(frozen=True, slots=True)
class CollisionProfile:
    """Vocal/bass overlap between two tracks over a candidate alignment.

    v0 has no stem separation (`mashpad.analysis.stems` is an explicit
    NotImplementedError seam), so there is no signal to measure overlap
    from yet. The default (`measured=False`, both ratios 0.0) means "not
    measured," not "no collision" — `mashpad.scoring.collision_score`
    treats an unmeasured profile as contributing no penalty rather than
    silently asserting a clean mix.
    """

    vocal_overlap_ratio: float = 0.0
    bass_overlap_ratio: float = 0.0
    measured: bool = False


@dataclass(frozen=True, slots=True)
class CompatibilityScores:
    tempo_fit: FitLevel
    harmonic_fit: FitLevel
    phrase_fit: FitLevel
    tempo_score: float
    harmonic_score: float
    phrase_score: float


@dataclass(frozen=True, slots=True)
class AdjustmentRecommendation:
    description: str


@dataclass(frozen=True, slots=True)
class CompatibilityProfile:
    """The result of evaluating one specific mashup move + role assignment.

    This is deliberately not symmetric in Track A / Track B: swapping
    `track_a_role` and `track_b_role` for the same pair of analyses is a
    different move and can produce a different `scores`/`composite_score`
    (see `mashpad.scoring.evaluate_move`), because the model preserves the
    higher-tolerance track (instrumental) rather than the vocal when a
    stretch/shift is required.

    `scores` is `None` exactly when `support_status` is `OUT_OF_SCOPE` —
    out-of-scope move types are represented honestly as "not scored,"
    never as a fabricated low (or high) number.
    """

    move_type: MashupMoveType
    track_a_role: TrackRole
    track_b_role: TrackRole
    support_status: MoveSupportStatus
    scores: CompatibilityScores | None
    composite_score: float | None
    composite_fit: FitLevel | None
    arrangement_contrast_score: float | None = None
    collision: CollisionProfile = field(default_factory=CollisionProfile)
    adjustments: tuple[AdjustmentRecommendation, ...] = ()
    note: str = ""
    tempo_relation: str | None = None
    tempo_explanation: str | None = None


class CompatibilityVerdictLevel(StrEnum):
    """Evidence-first outcome of assessing one move + role assignment.

    Deliberately asymmetric in how hard each is to earn — see
    `mashpad.scoring.verdict` and docs/compatibility-verdict.md:

    - `COMPATIBLE` / `UNLIKELY` are *confident* verdicts. They require
      MEASURED analysis provenance and unambiguous evidence; v0's stubs
      cannot reach them.
    - `MAYBE` is a real leaning-yes that is nonetheless conditional (stub
      data, a partial-support move, a fixable key clash, or a required
      octave reinterpretation).
    - `UNCERTAIN` is an explicit abstention: the harness declines to judge
      because evidence is missing, ambiguous, or the move's premise is
      unverified. Abstaining is the correct answer far more often than a
      flattering composite score implies.
    """

    COMPATIBLE = "compatible"
    MAYBE = "maybe"
    UNLIKELY = "unlikely"
    UNCERTAIN = "uncertain"


class EvidencePolarity(StrEnum):
    """How one piece of evidence bears on a compatibility verdict."""

    SUPPORTS = "supports"  # points toward compatibility
    OPPOSES = "opposes"  # points against compatibility
    AMBIGUOUS = "ambiguous"  # points more than one way at once
    MISSING = "missing"  # could not be evaluated (no data, or low-trust stub data)
    CONDITIONAL = "conditional"  # holds only under an assumption or manual override


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One piece of evidence behind a compatibility verdict.

    `dimension` names what was examined ("tempo", "harmonic", "phrase",
    "role", "move_support", "provenance"); `polarity` is how it bears on
    the verdict; `detail` explains it in one human-readable line. A
    confident verdict cites its SUPPORTS/OPPOSES items ("what supports
    confidence"); an UNCERTAIN verdict cites its AMBIGUOUS/MISSING/
    CONDITIONAL items ("what is missing or ambiguous"). That citation
    contract is the point of the model.
    """

    dimension: str
    polarity: EvidencePolarity
    detail: str


@dataclass(frozen=True, slots=True)
class CompatibilityVerdict:
    """The evidence-first result of `mashpad.scoring.verdict.assess_compatibility`.

    This is a musical *judgment* layered over `CompatibilityProfile`'s raw
    component scores — it never recomputes or re-weights them. It is the
    object the CLI presents as the answer, with the profile's numbers shown
    subordinate to it as backend evidence.
    """

    level: CompatibilityVerdictLevel
    headline: str
    evidence: tuple[EvidenceItem, ...]
    move_type: MashupMoveType
    track_a_role: TrackRole
    track_b_role: TrackRole

    @property
    def is_confident(self) -> bool:
        return self.level in (
            CompatibilityVerdictLevel.COMPATIBLE,
            CompatibilityVerdictLevel.UNLIKELY,
        )

    @property
    def abstained(self) -> bool:
        return self.level is CompatibilityVerdictLevel.UNCERTAIN

    @property
    def supporting_evidence(self) -> tuple[EvidenceItem, ...]:
        """Evidence that pushed the verdict one way (SUPPORTS/OPPOSES)."""
        return tuple(
            e
            for e in self.evidence
            if e.polarity in (EvidencePolarity.SUPPORTS, EvidencePolarity.OPPOSES)
        )

    @property
    def caveats(self) -> tuple[EvidenceItem, ...]:
        """Evidence that is missing, ambiguous, or conditional."""
        return tuple(
            e
            for e in self.evidence
            if e.polarity
            in (
                EvidencePolarity.AMBIGUOUS,
                EvidencePolarity.MISSING,
                EvidencePolarity.CONDITIONAL,
            )
        )


@dataclass(frozen=True, slots=True)
class MashupCandidate:
    rank: int
    section_a: Section
    section_b: Section
    score: float
    description: str


class ValidationClass(StrEnum):
    """The three evaluation-corpus buckets. See docs/eval-plan.md."""

    POSITIVE_GROUND_TRUTH = "positive_ground_truth"
    KNOWN_COMPATIBLE_MATCH = "known_compatible_match"
    NEGATIVE_GROUND_TRUTH = "negative_ground_truth"


@dataclass(frozen=True, slots=True)
class EvaluationPair:
    """One row of the evaluation corpus schema (docs/eval-plan.md).

    This is metadata about what a pair *should* score, not the analysis
    data itself — `track_a_path`/`track_b_path` are optional local-only
    placeholders (never resolved or committed; see fixtures/README.md).
    Tests that actually run the scoring pipeline against a corpus pair
    still need real `TrackAnalysis` fixtures (bpm/key/sections); this
    type only carries the pair's identity and expectations.
    """

    pair_id: str
    validation_class: ValidationClass
    move_type: MashupMoveType
    track_a_role: TrackRole
    track_b_role: TrackRole
    expected_score_min: float
    expected_score_max: float
    expected_features: tuple[str, ...] = ()
    notes: str = ""
    track_a_path: str | None = None
    track_b_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pair_id": self.pair_id,
            "validation_class": self.validation_class.value,
            "move_type": self.move_type.value,
            "track_a_role": self.track_a_role.value,
            "track_b_role": self.track_b_role.value,
            "expected_score_min": self.expected_score_min,
            "expected_score_max": self.expected_score_max,
            "expected_features": list(self.expected_features),
            "notes": self.notes,
            "track_a_path": self.track_a_path,
            "track_b_path": self.track_b_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationPair:
        return cls(
            pair_id=data["pair_id"],
            validation_class=ValidationClass(data["validation_class"]),
            move_type=MashupMoveType(data["move_type"]),
            track_a_role=TrackRole(data["track_a_role"]),
            track_b_role=TrackRole(data["track_b_role"]),
            expected_score_min=float(data["expected_score_min"]),
            expected_score_max=float(data["expected_score_max"]),
            expected_features=tuple(data.get("expected_features", [])),
            notes=data.get("notes", ""),
            track_a_path=data.get("track_a_path"),
            track_b_path=data.get("track_b_path"),
        )
