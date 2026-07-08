"""Human-readable text report generation for `mashcheck`."""

from __future__ import annotations

from mashpad.models import CompatibilityProfile, MashupCandidate, TrackAnalysis


def render_track(label: str, analysis: TrackAnalysis) -> str:
    lines = [
        f"{label}:",
        f"  BPM: {analysis.bpm:.1f}",
        f"  Key: {analysis.key}",
        f"  Sections: {', '.join(s.label for s in analysis.sections)}",
    ]
    return "\n".join(lines)


def render_report(
    analysis_a: TrackAnalysis,
    analysis_b: TrackAnalysis,
    profile: CompatibilityProfile,
    candidates: list[MashupCandidate],
) -> str:
    lines = [render_track("Song A", analysis_a), render_track("Song B", analysis_b)]

    lines.append(
        f"Assumed move: {profile.move_type.value} "
        f"(Song A = {profile.track_a_role.value}, Song B = {profile.track_b_role.value}) "
        f"[{profile.support_status.value}]"
    )

    lines.append("Compatibility:")
    if profile.scores is None:
        lines.append(f"  Not scored: {profile.note}")
        return "\n".join(lines)

    scores = profile.scores
    lines.append(f"  Tempo fit: {scores.tempo_fit.value}")
    if profile.tempo_explanation:
        lines.append(f"  Tempo interpretation: {profile.tempo_explanation}")
    lines.append(f"  Harmonic fit: {scores.harmonic_fit.value}")
    lines.append(f"  Phrase fit: {scores.phrase_fit.value}")
    lines.append(f"  Composite: {profile.composite_score:.4f} ({profile.composite_fit.value})")
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
