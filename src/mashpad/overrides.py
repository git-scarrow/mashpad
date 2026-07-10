"""Applying manual overrides to a TrackAnalysis.

Real, tested logic for the override kinds that are pure data transforms
on already-estimated values (BPM, key, phrase boundaries). DOWNBEAT and
STEM_GAIN overrides are modeled in `ManualOverride` but have nothing to
apply to yet — there's no beat-grid representation and no stem data
(`mashpad.analysis.stems.separate_stems` is unimplemented) — so applying
them raises NotImplementedError rather than silently doing nothing.
"""

from __future__ import annotations

from dataclasses import replace

from mashpad.models import (
    ManualOverride,
    OverrideTarget,
    ProvenanceRecord,
    ProvenanceTier,
    Section,
    TrackAnalysis,
)


def _mark_user_asserted(
    analysis: TrackAnalysis, dimension: str, reason: str
) -> dict[str, ProvenanceRecord]:
    """Field-provenance mapping with `dimension` set to USER_ASSERTED, every
    other dimension's record preserved.

    A user correcting a value is a human *assertion* — trusted as the value,
    never promoted to MEASURED. It lifts the dimension out of STUB (an override
    can resolve an ambiguity or supply a missing value) but cannot, by itself,
    earn a confident verdict; the verdict layer attributes it. See
    docs/design-memo-analyzer-provenance-contract.md (Decision 2).
    """
    updated = dict(analysis.field_provenance)
    updated[dimension] = ProvenanceRecord(
        tier=ProvenanceTier.USER_ASSERTED, method="manual_override", note=reason
    )
    return updated


def apply_override(analysis: TrackAnalysis, override: ManualOverride) -> TrackAnalysis:
    if override.target is OverrideTarget.BPM:
        if override.bpm_multiplier is None:
            raise ValueError("BPM override requires bpm_multiplier")
        return replace(
            analysis,
            bpm=round(analysis.bpm * override.bpm_multiplier, 4),
            field_provenance=_mark_user_asserted(analysis, "tempo", override.reason),
        )

    if override.target is OverrideTarget.KEY:
        if override.key is None:
            raise ValueError("KEY override requires key")
        return replace(
            analysis,
            key=override.key,
            field_provenance=_mark_user_asserted(analysis, "key", override.reason),
        )

    if override.target is OverrideTarget.PHRASE_BOUNDARY:
        if override.phrase_boundary_shift_sec is None:
            raise ValueError("PHRASE_BOUNDARY override requires phrase_boundary_shift_sec")
        shift = override.phrase_boundary_shift_sec
        shifted = tuple(
            Section(
                label=s.label,
                start_sec=max(0.0, s.start_sec + shift),
                end_sec=max(0.0, s.end_sec + shift),
                confidence=s.confidence,
            )
            for s in analysis.sections
        )
        return replace(
            analysis,
            sections=shifted,
            field_provenance=_mark_user_asserted(analysis, "sections", override.reason),
        )

    raise NotImplementedError(
        f"{override.target.value} override is modeled but not yet applied "
        "(no beat-grid/stem representation exists to apply it to)"
    )
