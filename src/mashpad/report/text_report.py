"""Human-readable text report generation for `mashcheck`.

The report is deliberately split into two zones so the two are never
conflated:

- **Musical judgment** — the `CompatibilityVerdict` (compatible / maybe /
  unlikely / uncertain) and the evidence that produced it. This is the
  answer.
- **Analysis evidence (backend components)** — the raw tempo/harmonic/
  phrase fits and the composite component score. These are *inputs* to the
  judgment, shown for transparency, explicitly not the verdict.
"""

from __future__ import annotations

from mashpad.models import (
    AnalysisProvenance,
    CompatibilityProfile,
    CompatibilityVerdict,
    MashupCandidate,
    TrackAnalysis,
)


def _provenance_tag(analysis: TrackAnalysis) -> str:
    if analysis.provenance is AnalysisProvenance.MEASURED:
        return "[measured]"
    return "[stub estimate — seeded from file name, not audio]"


def render_track(label: str, analysis: TrackAnalysis) -> str:
    tag = _provenance_tag(analysis)
    lines = [
        f"{label}:",
        f"  BPM: {analysis.bpm:.1f}  {tag}",
        f"  Key: {analysis.key}  {tag}",
        f"  Sections: {', '.join(s.label for s in analysis.sections)}  {tag}",
    ]
    return "\n".join(lines)


def _render_verdict(verdict: CompatibilityVerdict) -> list[str]:
    lines = ["Musical judgment", f"  Verdict: {verdict.level.value.upper()} — {verdict.headline}"]

    supporting = verdict.supporting_evidence
    lines.append("  Evidence for this call:" if supporting else "  Evidence for this call: none")
    for item in supporting:
        lines.append(f"    - {item.dimension}: {item.detail}")

    caveats = verdict.caveats
    if caveats:
        lines.append("  Missing / ambiguous / conditional evidence:")
        for item in caveats:
            lines.append(f"    - {item.dimension}: {item.detail}")

    return lines


def render_report(
    analysis_a: TrackAnalysis,
    analysis_b: TrackAnalysis,
    profile: CompatibilityProfile,
    verdict: CompatibilityVerdict,
    candidates: list[MashupCandidate],
) -> str:
    lines = [render_track("Song A", analysis_a), render_track("Song B", analysis_b)]

    lines.append(
        f"Assumed move: {profile.move_type.value} "
        f"(Song A = {profile.track_a_role.value}, Song B = {profile.track_b_role.value}) "
        f"[{profile.support_status.value}]"
    )

    lines.append("")
    lines.extend(_render_verdict(verdict))

    lines.append("")
    lines.append("Analysis evidence (backend components — inputs to the judgment, not the verdict)")
    if profile.scores is None:
        lines.append(f"  Not scored: {profile.note}")
    else:
        scores = profile.scores
        lines.append(f"  Tempo fit: {scores.tempo_fit.value}")
        if profile.tempo_explanation:
            lines.append(f"  Tempo interpretation: {profile.tempo_explanation}")
        lines.append(f"  Harmonic fit: {scores.harmonic_fit.value}")
        lines.append(f"  Phrase fit: {scores.phrase_fit.value}")
        lines.append(
            f"  Composite component score: {profile.composite_score:.4f} "
            f"({profile.composite_fit.value})  [not the verdict]"
        )
        if profile.note:
            lines.append(f"  Note: {profile.note}")

    lines.append("Suggested adjustments:")
    if profile.adjustments:
        lines.extend(f"  {adj.description}" for adj in profile.adjustments)
    else:
        lines.append("  None")

    lines.append("Best candidates:")
    if candidates:
        for candidate in candidates:
            lines.append(f"  {candidate.rank}. {candidate.description}")
    else:
        lines.append("  None")

    return "\n".join(lines)
