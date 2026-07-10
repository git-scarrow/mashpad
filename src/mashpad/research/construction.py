"""Ground-truth mashup *construction* records.

A construction is more specific than an `EvaluationPair` (which says "this
pair should score in this band for this move"): it asserts a directed,
section-specific, phrase-level *arrangement* known to work artistically —
which track is the host foundation, where the guest enters, and which
events are intended to converge. It is the research-layer object that a
future alignment-aware scorer would be evaluated against.

Honesty rules, mirroring the production provenance contract without
touching it:

- Every empirical field is a `GroundTruthField` carrying an explicit
  `ResolutionState` — `MEASURED`, `ANNOTATED`, `HYPOTHESIS` (a bounded
  prior), or `UNRESOLVED`. Knowing that a construction works does *not*
  mean its parameters are known; most start as bounded hypotheses.
- `MEASURED` is refused unless the field names a real measurement method
  (`_LAUNDERING_METHODS` are rejected). Human annotation is `ANNOTATED`
  — the research twin of `ProvenanceTier.USER_ASSERTED` — and can never
  be promoted by renaming.
- A `HYPOTHESIS` must carry bounds or a stated candidate value; an
  unbounded, valueless guess is `UNRESOLVED`.
- Committed fixtures carry identity metadata and hypotheses only. Event
  *times* against the real recordings live in a local, uncommitted
  annotation file (same pattern as `fixtures/local/audio_index.json`)
  keyed by `event_id` — see `mashpad.research.alignment_basin`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from mashpad.models import MashupMoveType, TrackRole


class ResolutionState(StrEnum):
    """How much is actually known about one ground-truth field."""

    MEASURED = "measured"  # produced by a real measurement method on decoded audio
    ANNOTATED = "annotated"  # human annotation against the real recording
    HYPOTHESIS = "hypothesis"  # bounded prior — plausible range, not a trusted value
    UNRESOLVED = "unresolved"  # not yet known; to be annotated or measured


# Method names that can never justify MEASURED — the research-layer version
# of the anti-laundering guards in tests/test_provenance_contract.py.
_LAUNDERING_METHODS = frozenset({"", "stub", "manual_annotation", "manual_override", "prior"})


@dataclass(frozen=True, slots=True)
class GroundTruthField:
    """One empirical field of a construction, with explicit resolution.

    `value` is trusted only as far as `state` says; a HYPOTHESIS must
    carry `bounds` (lo, hi) or a stated candidate `value`. `unit` is free
    text ("bpm", "sec", "beats", "measures", "key", "index").
    """

    state: ResolutionState
    value: float | str | None = None
    bounds: tuple[float, float] | None = None
    unit: str = ""
    method: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.state is ResolutionState.MEASURED and self.method in _LAUNDERING_METHODS:
            raise ValueError(
                f"MEASURED requires a real measurement method, got {self.method!r} — "
                "annotation and priors stay ANNOTATED/HYPOTHESIS"
            )
        if self.state is ResolutionState.HYPOTHESIS and self.bounds is None and self.value is None:
            raise ValueError(
                "HYPOTHESIS must carry bounds or a stated candidate value; "
                "an unbounded, valueless guess is UNRESOLVED"
            )
        if self.bounds is not None and self.bounds[0] > self.bounds[1]:
            raise ValueError(f"bounds out of order: {self.bounds}")

    @property
    def resolved(self) -> bool:
        return self.state in (ResolutionState.MEASURED, ResolutionState.ANNOTATED)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "value": self.value,
            "bounds": list(self.bounds) if self.bounds is not None else None,
            "unit": self.unit,
            "method": self.method,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroundTruthField:
        raw_bounds = data.get("bounds")
        return cls(
            state=ResolutionState(data["state"]),
            value=data.get("value"),
            bounds=None if raw_bounds is None else (float(raw_bounds[0]), float(raw_bounds[1])),
            unit=data.get("unit", ""),
            method=data.get("method", ""),
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class RecordingRef:
    """Identity of one specific recording (not "the song" in the abstract —
    a different edit/version changes every time value in the construction)."""

    title: str
    artist: str
    version_note: str = ""
    duration_sec: GroundTruthField = field(
        default_factory=lambda: GroundTruthField(ResolutionState.UNRESOLVED, unit="sec")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "version_note": self.version_note,
            "duration_sec": self.duration_sec.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingRef:
        return cls(
            title=data["title"],
            artist=data["artist"],
            version_note=data.get("version_note", ""),
            duration_sec=GroundTruthField.from_dict(data["duration_sec"]),
        )


class EventKind(StrEnum):
    """What kind of musical event an anchor names."""

    LYRIC_STRESS_ONSET = "lyric_stress_onset"  # onset of a stressed sung syllable
    PHRASE_ONSET = "phrase_onset"  # start of a lyric/melodic phrase
    SECTION_BOUNDARY = "section_boundary"  # structural boundary (e.g. chorus start)
    DOWNBEAT = "downbeat"  # bar-level accent
    CADENCE = "cadence"  # harmonic arrival / cadential motion


class GuestAudibility(StrEnum):
    """Whether the guest is in the audible mix over an aligned span.

    Temporal alignment and audibility are different facts: a guest can be
    fully synchronized on the shared grid (aligned-but-MUTED) while its
    active harmonic/textural material is inadmissible for simultaneous
    playback. A valid construction grid is not a valid full-duration
    overlay."""

    MUTED = "muted"  # aligned on the grid but excluded from the audible mix
    ENTERING = "entering"  # being brought into the audible mix
    AUDIBLE = "audible"  # fully present in the audible mix


@dataclass(frozen=True, slots=True)
class AnchorEvent:
    """A named musical event on one side of the construction.

    `time_sec` in the committed fixture is typically UNRESOLVED — the
    committed record says *what* the event is and how to find it (token,
    lyric context, which occurrence); the local annotation file supplies
    when it happens in the actual recording.
    """

    event_id: str
    side: str  # "host" | "guest"
    kind: EventKind
    token: str = ""  # the emphasized word/syllable, if lyric-anchored
    lyric_context: str = ""  # surrounding lyric line, for locating it
    occurrence: str = ""  # which instance ("each chorus", "chorus 1", ...)
    time_sec: GroundTruthField = field(
        default_factory=lambda: GroundTruthField(ResolutionState.UNRESOLVED, unit="sec")
    )

    def __post_init__(self) -> None:
        if self.side not in ("host", "guest"):
            raise ValueError(f"side must be 'host' or 'guest', got {self.side!r}")
        # No forced-alignment or structural-segmentation measurement seam
        # exists anywhere in this repo yet, so an event time claiming
        # MEASURED could only be laundered annotation. Lift this when a
        # sanctioned seam (the tempo_measurement pattern) exists for it.
        if self.time_sec.state is ResolutionState.MEASURED:
            raise ValueError(
                "event times cannot be MEASURED yet: no sanctioned measurement seam "
                "exists for lyric/section event times — record them as ANNOTATED"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "side": self.side,
            "kind": self.kind.value,
            "token": self.token,
            "lyric_context": self.lyric_context,
            "occurrence": self.occurrence,
            "time_sec": self.time_sec.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnchorEvent:
        return cls(
            event_id=data["event_id"],
            side=data["side"],
            kind=EventKind(data["kind"]),
            token=data.get("token", ""),
            lyric_context=data.get("lyric_context", ""),
            occurrence=data.get("occurrence", ""),
            time_sec=GroundTruthField.from_dict(data["time_sec"]),
        )


@dataclass(frozen=True, slots=True)
class Convergence:
    """An intended coincidence between one guest event and one host event.

    `offset_beats` is the *signed landing offset* (guest event relative to
    host event, in host beats) — the central empirical unknown of a
    construction. It stays HYPOTHESIS/UNRESOLVED with bounds until the
    alignment experiment resolves it; `tolerance_beats` is how far off the
    landing can drift before the intended effect is judged (by ear) to
    degrade, which is also empirical.
    """

    convergence_id: str
    guest_event_id: str
    host_event_id: str
    offset_beats: GroundTruthField
    tolerance_beats: GroundTruthField
    character: tuple[str, ...] = ()  # e.g. ("accent_alignment", "semantic_collision")
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "convergence_id": self.convergence_id,
            "guest_event_id": self.guest_event_id,
            "host_event_id": self.host_event_id,
            "offset_beats": self.offset_beats.to_dict(),
            "tolerance_beats": self.tolerance_beats.to_dict(),
            "character": list(self.character),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Convergence:
        return cls(
            convergence_id=data["convergence_id"],
            guest_event_id=data["guest_event_id"],
            host_event_id=data["host_event_id"],
            offset_beats=GroundTruthField.from_dict(data["offset_beats"]),
            tolerance_beats=GroundTruthField.from_dict(data["tolerance_beats"]),
            character=tuple(data.get("character", [])),
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class AlignedWindow:
    """A contiguous span of the host timeline over which the aligned
    arrangement is judged (by ear) — including spans where the judgment is
    "keep the guest muted here."

    Bounds are in *host measures* on the corrected shared grid. `judgment`
    is a human listening judgment — ANNOTATED at best, never MEASURED
    (there is no instrument for "musically convincing").
    `guest_audibility` is the arrangement state over the span: a window can
    be structurally synchronized yet locally inadmissible for simultaneous
    playback (aligned-but-muted)."""

    window_id: str
    host_sections: tuple[str, ...]  # e.g. ("chorus 2", "bridge", "final chorus")
    start_host_measure: GroundTruthField
    end_host_measure: GroundTruthField
    judgment: GroundTruthField
    guest_audibility: GuestAudibility = GuestAudibility.AUDIBLE
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "window_id": self.window_id,
            "host_sections": list(self.host_sections),
            "start_host_measure": self.start_host_measure.to_dict(),
            "end_host_measure": self.end_host_measure.to_dict(),
            "judgment": self.judgment.to_dict(),
            "guest_audibility": self.guest_audibility.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlignedWindow:
        return cls(
            window_id=data["window_id"],
            host_sections=tuple(data.get("host_sections", [])),
            start_host_measure=GroundTruthField.from_dict(data["start_host_measure"]),
            end_host_measure=GroundTruthField.from_dict(data["end_host_measure"]),
            judgment=GroundTruthField.from_dict(data["judgment"]),
            guest_audibility=GuestAudibility(data.get("guest_audibility", "audible")),
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class GridAnchor:
    """The primary structural anchor: one host event and one guest event
    (typically each recording's *first metrically established downbeat*)
    placed at the same moment, establishing the continuous shared grid.

    Ground truth is source-audio timestamps plus musical function — the
    referenced `AnchorEvent`s. Application bar labels (djay etc.) are
    session-specific annotations recorded in `session_bar_labels`, never
    the anchor itself: an application may count an ambiguous opening
    gesture as a measure, treat it as pickup material, or omit it from
    the regular grid, renumbering every bar after it."""

    host_event_id: str
    guest_event_id: str
    alignment_offset_beats: GroundTruthField  # deviation from exact coincidence
    session_bar_labels: str = ""  # e.g. "djay: Skyfall bar 3 = In the End bar 1"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "host_event_id": self.host_event_id,
            "guest_event_id": self.guest_event_id,
            "alignment_offset_beats": self.alignment_offset_beats.to_dict(),
            "session_bar_labels": self.session_bar_labels,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GridAnchor:
        return cls(
            host_event_id=data["host_event_id"],
            guest_event_id=data["guest_event_id"],
            alignment_offset_beats=GroundTruthField.from_dict(data["alignment_offset_beats"]),
            session_bar_labels=data.get("session_bar_labels", ""),
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class GridAlignment:
    """Level-2 structural alignment: both tracks on one shared grid with a
    measure-index offset, `host_measure = guest_measure + measure_offset`.

    This sits between global conformance (tempo/pitch treatment — level 1)
    and local convergence events (level 3): it asserts *where* the guest
    timeline sits against the host timeline, and over which windows the
    resulting overlap works. `offset_constant_across_window` is its own
    empirical question — a drifting offset would mean the shared grid or
    one track's beat grid is wrong.

    The primary structural relation, when known, is `anchor`: a
    downbeat-to-downbeat coincidence establishing the continuous shared
    grid, with measure-offset bookkeeping (`measure_offset`,
    `example_correspondences`) secondary and *frame-dependent* — measure
    indices only mean anything relative to a stated numbering frame, and
    application bar labels are not source structure. **Structural
    synchronization is not admissibility**: sharing a usable grid says
    nothing about whether both tracks should be audible at a given moment
    (see `AlignedWindow.guest_audibility` — aligned-but-muted is a
    first-class state).

    Tempo compatibility here is a **bounded region, not a point**:
    `shared_grid_bpm` is the *witnessed working point* — the setting the
    construction was actually auditioned at — never the unique or optimal
    common tempo. `viable_grid_bpm_region` is the provisional
    human-auditioned interval over which the arrangement is hypothesized
    to remain viable. The constraint shaping that region is asymmetric by
    role: the host places the main bound (it must retain its intended
    pacing, weight, and dramatic character), while the conformed side may
    tolerate much larger transformation — so acceptability is *not* a
    matter of minimizing aggregate tempo change, and transformation cost
    cannot be judged by absolute percentage alone. Different grid settings
    within the region may need small alignment adjustments and yield
    distinct but valid versions of the overlay (a construction *family*)."""

    shared_grid_bpm: GroundTruthField
    measure_offset: GroundTruthField  # host measure minus guest measure
    offset_constant_across_window: GroundTruthField
    viable_grid_bpm_region: GroundTruthField | None = None
    anchor: GridAnchor | None = None
    example_correspondences: tuple[tuple[int, int], ...] = ()  # (host_measure, guest_measure)
    windows: tuple[AlignedWindow, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if self.measure_offset.value is not None:
            offset = float(self.measure_offset.value)
            for host_m, guest_m in self.example_correspondences:
                if float(host_m - guest_m) != offset:
                    raise ValueError(
                        f"example correspondence {host_m}<->{guest_m} contradicts "
                        f"measure_offset {offset}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "shared_grid_bpm": self.shared_grid_bpm.to_dict(),
            "measure_offset": self.measure_offset.to_dict(),
            "offset_constant_across_window": self.offset_constant_across_window.to_dict(),
            "viable_grid_bpm_region": (
                self.viable_grid_bpm_region.to_dict()
                if self.viable_grid_bpm_region is not None
                else None
            ),
            "anchor": self.anchor.to_dict() if self.anchor is not None else None,
            "example_correspondences": [list(pair) for pair in self.example_correspondences],
            "windows": [w.to_dict() for w in self.windows],
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GridAlignment:
        raw_region = data.get("viable_grid_bpm_region")
        return cls(
            shared_grid_bpm=GroundTruthField.from_dict(data["shared_grid_bpm"]),
            measure_offset=GroundTruthField.from_dict(data["measure_offset"]),
            offset_constant_across_window=GroundTruthField.from_dict(
                data["offset_constant_across_window"]
            ),
            viable_grid_bpm_region=(
                GroundTruthField.from_dict(raw_region) if raw_region is not None else None
            ),
            anchor=(
                GridAnchor.from_dict(data["anchor"]) if data.get("anchor") is not None else None
            ),
            example_correspondences=tuple(
                (int(pair[0]), int(pair[1])) for pair in data.get("example_correspondences", [])
            ),
            windows=tuple(AlignedWindow.from_dict(w) for w in data.get("windows", [])),
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class MashupConstruction:
    """A partially specified, directed, section-anchored mashup arrangement.

    Host/guest asymmetry is structural, not a role relabeling: the host
    *retains its foundation* (its own beat grid, key, and — in the
    Skyfall case — its own load-bearing vocal), while the guest *enters
    selectively* during a named host section and is the side conformed in
    tempo/pitch. This is deliberately richer than one `MashupMoveType`:
    `primary_move_type` records the closest taxonomy framing and
    `related_move_types` the aspects it borrows, so the record itself is
    evidence about whether the taxonomy has the right concepts.

    A resolved construction distinguishes three hypothesis levels:

    1. **Global conformance** — the tempo interpretation and tempo/pitch
       transformation that place both tracks on a shared grid
       (`host_bpm`/`guest_bpm`/`tempo_ratio`/`pitch_shift_semitones`,
       plus `grid.shared_grid_bpm`).
    2. **Structural alignment** — the measure-index offset and the
       windows over which the overlap works (`grid`).
    3. **Local convergence events** — particular landings such as "hard"
       on "fall" (`events`/`convergences`), which may help explain *why*
       the broader alignment feels effective but are not the whole claim.

    `claim_scope` is always `"witness"`: a construction asserts the
    *existence* of one working arrangement (an existence proof / positive
    example), never that it is the unique or best overlay of the two
    recordings. Success criteria built on a construction must therefore
    test "does the model score this arrangement as viable, and degraded
    neighbors as worse," not "does the model recover exactly this."
    """

    construction_id: str
    description: str
    primary_move_type: MashupMoveType
    related_move_types: tuple[MashupMoveType, ...]
    host: RecordingRef
    guest: RecordingRef
    host_role: TrackRole
    guest_role: TrackRole
    host_retains_own_vocal: bool
    host_anchor_section_label: str
    host_anchor_section_occurrence: GroundTruthField
    guest_entry_offset_beats: GroundTruthField  # guest entry relative to host section start
    conformed_side: str  # which side is stretched/shifted to the other's grid
    host_bpm: GroundTruthField
    guest_bpm: GroundTruthField
    # Guest stretch factor at the *witnessed* grid point. Grid-choice
    # dependent: it varies across grid.viable_grid_bpm_region and does not
    # define the construction.
    tempo_ratio: GroundTruthField
    host_key: GroundTruthField
    guest_key: GroundTruthField
    pitch_shift_semitones: GroundTruthField  # applied to the conformed side
    events: tuple[AnchorEvent, ...]
    convergences: tuple[Convergence, ...]
    taxonomy_gap_notes: str = ""
    grid: GridAlignment | None = None
    claim_scope: str = "witness"

    def __post_init__(self) -> None:
        if self.claim_scope != "witness":
            raise ValueError(
                "claim_scope must be 'witness': a construction is an existence proof of "
                "one working arrangement, never a uniqueness claim"
            )
        if self.conformed_side not in ("host", "guest"):
            raise ValueError(
                f"conformed_side must be 'host' or 'guest', got {self.conformed_side!r}"
            )
        ids = [e.event_id for e in self.events]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate event_id in events")
        known = set(ids)
        for c in self.convergences:
            missing = {c.guest_event_id, c.host_event_id} - known
            if missing:
                raise ValueError(
                    f"convergence {c.convergence_id} references unknown events {sorted(missing)}"
                )
        by_id = {e.event_id: e for e in self.events}
        for c in self.convergences:
            if by_id[c.guest_event_id].side != "guest" or by_id[c.host_event_id].side != "host":
                raise ValueError(
                    f"convergence {c.convergence_id} must pair a guest event with a host event"
                )
        if self.grid is not None and self.grid.anchor is not None:
            anchor = self.grid.anchor
            for event_id, side in (
                (anchor.host_event_id, "host"),
                (anchor.guest_event_id, "guest"),
            ):
                if event_id not in by_id:
                    raise ValueError(f"grid anchor references unknown event {event_id!r}")
                if by_id[event_id].side != side:
                    raise ValueError(
                        f"grid anchor {side} event {event_id!r} is on side {by_id[event_id].side!r}"
                    )

    def event(self, event_id: str) -> AnchorEvent:
        for e in self.events:
            if e.event_id == event_id:
                return e
        raise KeyError(event_id)

    def unresolved_fields(self) -> tuple[str, ...]:
        """Names of empirical fields not yet ANNOTATED/MEASURED — the
        construction's open work list."""
        named: list[tuple[str, GroundTruthField]] = [
            ("host.duration_sec", self.host.duration_sec),
            ("guest.duration_sec", self.guest.duration_sec),
            ("host_anchor_section_occurrence", self.host_anchor_section_occurrence),
            ("guest_entry_offset_beats", self.guest_entry_offset_beats),
            ("host_bpm", self.host_bpm),
            ("guest_bpm", self.guest_bpm),
            ("tempo_ratio", self.tempo_ratio),
            ("host_key", self.host_key),
            ("guest_key", self.guest_key),
            ("pitch_shift_semitones", self.pitch_shift_semitones),
        ]
        named.extend((f"event:{e.event_id}.time_sec", e.time_sec) for e in self.events)
        for c in self.convergences:
            named.append((f"convergence:{c.convergence_id}.offset_beats", c.offset_beats))
            named.append((f"convergence:{c.convergence_id}.tolerance_beats", c.tolerance_beats))
        if self.grid is not None:
            named.append(("grid.shared_grid_bpm", self.grid.shared_grid_bpm))
            named.append(("grid.measure_offset", self.grid.measure_offset))
            named.append(
                ("grid.offset_constant_across_window", self.grid.offset_constant_across_window)
            )
            if self.grid.viable_grid_bpm_region is not None:
                named.append(("grid.viable_grid_bpm_region", self.grid.viable_grid_bpm_region))
            if self.grid.anchor is not None:
                named.append(
                    ("grid.anchor.alignment_offset_beats", self.grid.anchor.alignment_offset_beats)
                )
            for w in self.grid.windows:
                named.append((f"window:{w.window_id}.start_host_measure", w.start_host_measure))
                named.append((f"window:{w.window_id}.end_host_measure", w.end_host_measure))
                named.append((f"window:{w.window_id}.judgment", w.judgment))
        return tuple(name for name, f in named if not f.resolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "construction_id": self.construction_id,
            "description": self.description,
            "primary_move_type": self.primary_move_type.value,
            "related_move_types": [m.value for m in self.related_move_types],
            "host": self.host.to_dict(),
            "guest": self.guest.to_dict(),
            "host_role": self.host_role.value,
            "guest_role": self.guest_role.value,
            "host_retains_own_vocal": self.host_retains_own_vocal,
            "host_anchor_section_label": self.host_anchor_section_label,
            "host_anchor_section_occurrence": self.host_anchor_section_occurrence.to_dict(),
            "guest_entry_offset_beats": self.guest_entry_offset_beats.to_dict(),
            "conformed_side": self.conformed_side,
            "host_bpm": self.host_bpm.to_dict(),
            "guest_bpm": self.guest_bpm.to_dict(),
            "tempo_ratio": self.tempo_ratio.to_dict(),
            "host_key": self.host_key.to_dict(),
            "guest_key": self.guest_key.to_dict(),
            "pitch_shift_semitones": self.pitch_shift_semitones.to_dict(),
            "events": [e.to_dict() for e in self.events],
            "convergences": [c.to_dict() for c in self.convergences],
            "taxonomy_gap_notes": self.taxonomy_gap_notes,
            "grid": self.grid.to_dict() if self.grid is not None else None,
            "claim_scope": self.claim_scope,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MashupConstruction:
        return cls(
            construction_id=data["construction_id"],
            description=data["description"],
            primary_move_type=MashupMoveType(data["primary_move_type"]),
            related_move_types=tuple(MashupMoveType(m) for m in data.get("related_move_types", [])),
            host=RecordingRef.from_dict(data["host"]),
            guest=RecordingRef.from_dict(data["guest"]),
            host_role=TrackRole(data["host_role"]),
            guest_role=TrackRole(data["guest_role"]),
            host_retains_own_vocal=bool(data["host_retains_own_vocal"]),
            host_anchor_section_label=data["host_anchor_section_label"],
            host_anchor_section_occurrence=GroundTruthField.from_dict(
                data["host_anchor_section_occurrence"]
            ),
            guest_entry_offset_beats=GroundTruthField.from_dict(data["guest_entry_offset_beats"]),
            conformed_side=data["conformed_side"],
            host_bpm=GroundTruthField.from_dict(data["host_bpm"]),
            guest_bpm=GroundTruthField.from_dict(data["guest_bpm"]),
            tempo_ratio=GroundTruthField.from_dict(data["tempo_ratio"]),
            host_key=GroundTruthField.from_dict(data["host_key"]),
            guest_key=GroundTruthField.from_dict(data["guest_key"]),
            pitch_shift_semitones=GroundTruthField.from_dict(data["pitch_shift_semitones"]),
            events=tuple(AnchorEvent.from_dict(e) for e in data.get("events", [])),
            convergences=tuple(Convergence.from_dict(c) for c in data.get("convergences", [])),
            taxonomy_gap_notes=data.get("taxonomy_gap_notes", ""),
            grid=(GridAlignment.from_dict(data["grid"]) if data.get("grid") is not None else None),
            claim_scope=data.get("claim_scope", "witness"),
        )


def load_construction(path: Path) -> MashupConstruction:
    with open(path, encoding="utf-8") as fh:
        return MashupConstruction.from_dict(json.load(fh))
