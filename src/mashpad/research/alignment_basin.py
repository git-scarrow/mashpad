"""Alignment-basin analysis: can an offset-aware score distinguish the
intended landing of a construction from nearby corrupted offsets?

This is the research-layer counterpart to the executable negative result
in tests/test_construction_case.py (production `evaluate_move` is
structurally offset-blind: no input encodes *when* the guest enters). The
functions here consume only numeric event times and a beat period — never
track names, titles, or analyses — so nothing in a basin can be driven by
identity metadata.

The model: the host keeps its own timeline; the guest timeline is shifted
by a candidate `offset_sec` (already tempo-conformed — tempo treatment is
the construction's problem, not this module's). The basin score at an
offset is the weighted mean distance, in host beats, from each shifted
guest event to its nearest host event of a compatible kind. Two properties
this makes measurable:

- **Periodic ridge:** beat/downbeat events alone cannot single out the
  intended offset — every whole-beat (or whole-bar) shift scores the
  same. Beat-grid compatibility is necessary but cannot explain why
  "hard" must land on "fall".
- **Anchor tie-break:** one aperiodic lyric-anchor pair (the convergence)
  breaks that tie, making the intended offset a strict minimum. That is
  the smallest feature the production model is missing.

Kept deliberately tiny: point processes and nearest-neighbor distances,
no audio, no DSP.
"""

from __future__ import annotations

from dataclasses import dataclass

from mashpad.research.construction import EventKind

# Which host event kinds a guest event may be scored against. A guest
# lyric-stress onset landing on a host downbeat is fine rhythm but is not
# the convergence; anchors only match anchors of the paired kind.
_COMPATIBLE: dict[EventKind, frozenset[EventKind]] = {
    EventKind.DOWNBEAT: frozenset({EventKind.DOWNBEAT}),
    EventKind.PHRASE_ONSET: frozenset({EventKind.PHRASE_ONSET, EventKind.SECTION_BOUNDARY}),
    EventKind.SECTION_BOUNDARY: frozenset({EventKind.SECTION_BOUNDARY}),
    EventKind.LYRIC_STRESS_ONSET: frozenset({EventKind.LYRIC_STRESS_ONSET}),
}


@dataclass(frozen=True, slots=True)
class TimedEvent:
    """One annotated event time. `weight` lets a convergence anchor count
    more than a routine beat, mirroring that the landing is the point."""

    time_sec: float
    kind: EventKind
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class OffsetScore:
    offset_sec: float
    error_beats: float  # weighted mean nearest-neighbor distance; lower is better


def alignment_error(
    host_events: list[TimedEvent],
    guest_events: list[TimedEvent],
    offset_sec: float,
    beat_period_sec: float,
) -> float:
    """Weighted mean distance (in host beats) from each shifted guest event
    to the nearest compatible host event. Guest events with no compatible
    host event are skipped rather than scored against the wrong kind."""
    if beat_period_sec <= 0:
        raise ValueError("beat_period_sec must be positive")
    total = 0.0
    weight_sum = 0.0
    for g in guest_events:
        targets = [h for h in host_events if h.kind in _COMPATIBLE[g.kind]]
        if not targets:
            continue
        shifted = g.time_sec + offset_sec
        nearest = min(abs(shifted - h.time_sec) for h in targets)
        total += g.weight * (nearest / beat_period_sec)
        weight_sum += g.weight
    if weight_sum == 0.0:
        raise ValueError("no guest event has a compatible host event to score against")
    return total / weight_sum


def basin(
    host_events: list[TimedEvent],
    guest_events: list[TimedEvent],
    offsets_sec: list[float],
    beat_period_sec: float,
) -> tuple[OffsetScore, ...]:
    """Score every candidate offset. Order of the result follows the input
    offsets so callers can plot the basin shape directly."""
    return tuple(
        OffsetScore(o, alignment_error(host_events, guest_events, o, beat_period_sec))
        for o in offsets_sec
    )


def rank_offsets(scores: tuple[OffsetScore, ...]) -> tuple[OffsetScore, ...]:
    """Best-first ranking of an already-computed basin."""
    return tuple(sorted(scores, key=lambda s: s.error_beats))


def is_distinguished(
    scores: tuple[OffsetScore, ...],
    intended_offset_sec: float,
    margin_beats: float,
    tie_tolerance_sec: float = 1e-9,
) -> bool:
    """True iff the intended offset beats every *other* offset by at least
    `margin_beats`. This is the experiment's success predicate: a flat or
    ridged basin (ties at whole-beat shifts) returns False."""
    intended = [s for s in scores if abs(s.offset_sec - intended_offset_sec) <= tie_tolerance_sec]
    if not intended:
        raise ValueError("intended offset not present in the scored basin")
    rest = [s for s in scores if abs(s.offset_sec - intended_offset_sec) > tie_tolerance_sec]
    if not rest:
        return False  # nothing to be distinguished from
    best_intended = min(s.error_beats for s in intended)
    return all(s.error_beats - best_intended >= margin_beats for s in rest)
