"""Construction timeline: the arrangement laid out by corrected measure
number on the shared grid.

This is the working artifact of the alignment-validation protocol: one
row per annotated host measure, carrying both tracks' section labels,
the derived guest measure index (`host - measure_offset`), notable vocal
or musical events, and the human judgment for that span. A separate
`OffsetAudition` list records listening judgments for the witness offset
and its neighbors, so "nearby offsets degrade the whole passage" is a
recorded observation, not an assumption.

Like everything in `mashpad.research`, this is parallel to production:
timelines are annotation artifacts about one construction, they carry
`GroundTruthField` resolution states, and human judgments stay ANNOTATED
at best. Entries are expected to be sparse and to grow as annotation
proceeds — a missing measure means "not yet annotated," never "nothing
happens there."
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mashpad.research.construction import GroundTruthField, GuestAudibility

# The judgment dimensions of the tempo-sweep protocol. Each auditioned grid
# tempo gets an overall judgment plus (optionally) per-aspect judgments, so
# the sweep estimates a viability curve/interval rather than fitting to one
# chosen BPM.
TEMPO_SWEEP_ASPECTS: tuple[str, ...] = (
    "host_naturalness",
    "guest_intelligibility",
    "groove",
    "dramatic_weight",
    "overall_effectiveness",
)


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """What happens at (or starting at) one host measure on the shared grid.

    `host_measure` is the timeline's working index (its numbering frame is
    stated in `ConstructionTimeline.transformation_note`). Source-audio
    downbeat timestamps (`host_downbeat_sec`/`guest_downbeat_sec`) are the
    ground-truth representation of the grid; `host_app_bar`/`guest_app_bar`
    keep application (e.g. djay) bar labels *separately*, because an app may
    count an ambiguous opening as a measure, pickup, or nothing —
    application numbering is never source structure. `guest_audibility` is
    the arrangement state (aligned-but-muted is first-class);
    `harmonic_judgment`, `texture_conflict`, and `cadential_events` carry
    the local-admissibility evidence for the span."""

    host_measure: int
    host_section: str = ""
    guest_section: str = ""
    events: tuple[str, ...] = ()
    judgment: str = ""  # human note for this span; "" = not yet auditioned/annotated
    host_downbeat_sec: GroundTruthField | None = None  # source-relative timestamp
    guest_downbeat_sec: GroundTruthField | None = None  # source-relative timestamp
    host_app_bar: int | None = None  # application (session) bar label, if any
    guest_app_bar: int | None = None
    guest_audibility: GuestAudibility | None = None  # None = not yet decided/recorded
    harmonic_judgment: str = ""
    texture_conflict: str = ""
    cadential_events: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "host_measure": self.host_measure,
            "host_section": self.host_section,
            "guest_section": self.guest_section,
            "events": list(self.events),
            "judgment": self.judgment,
            "host_downbeat_sec": (
                self.host_downbeat_sec.to_dict() if self.host_downbeat_sec is not None else None
            ),
            "guest_downbeat_sec": (
                self.guest_downbeat_sec.to_dict() if self.guest_downbeat_sec is not None else None
            ),
            "host_app_bar": self.host_app_bar,
            "guest_app_bar": self.guest_app_bar,
            "guest_audibility": (
                self.guest_audibility.value if self.guest_audibility is not None else None
            ),
            "harmonic_judgment": self.harmonic_judgment,
            "texture_conflict": self.texture_conflict,
            "cadential_events": list(self.cadential_events),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimelineEntry:
        raw_host_db = data.get("host_downbeat_sec")
        raw_guest_db = data.get("guest_downbeat_sec")
        raw_audibility = data.get("guest_audibility")
        return cls(
            host_measure=int(data["host_measure"]),
            host_section=data.get("host_section", ""),
            guest_section=data.get("guest_section", ""),
            events=tuple(data.get("events", [])),
            judgment=data.get("judgment", ""),
            host_downbeat_sec=(
                GroundTruthField.from_dict(raw_host_db) if raw_host_db is not None else None
            ),
            guest_downbeat_sec=(
                GroundTruthField.from_dict(raw_guest_db) if raw_guest_db is not None else None
            ),
            host_app_bar=(None if data.get("host_app_bar") is None else int(data["host_app_bar"])),
            guest_app_bar=(
                None if data.get("guest_app_bar") is None else int(data["guest_app_bar"])
            ),
            guest_audibility=(
                GuestAudibility(raw_audibility) if raw_audibility is not None else None
            ),
            harmonic_judgment=data.get("harmonic_judgment", ""),
            texture_conflict=data.get("texture_conflict", ""),
            cadential_events=tuple(data.get("cadential_events", [])),
        )


@dataclass(frozen=True, slots=True)
class OffsetAudition:
    """A listening judgment for one candidate measure offset (the witness
    offset or a corrupted neighbor). `judgment.state` is ANNOTATED once a
    human has actually auditioned it, UNRESOLVED until then."""

    measure_offset: int
    judgment: GroundTruthField

    def to_dict(self) -> dict[str, Any]:
        return {"measure_offset": self.measure_offset, "judgment": self.judgment.to_dict()}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OffsetAudition:
        return cls(
            measure_offset=int(data["measure_offset"]),
            judgment=GroundTruthField.from_dict(data["judgment"]),
        )


@dataclass(frozen=True, slots=True)
class TempoAudition:
    """A listening judgment for one candidate shared-grid tempo, holding the
    structural offset as close to constant as possible.

    `judgment` is the overall call for this grid setting; `aspects` may add
    per-dimension judgments keyed by `TEMPO_SWEEP_ASPECTS`. UNRESOLVED until
    a human has actually auditioned it — planned sweep points are recorded
    unresolved so the sweep's coverage is visible before it runs."""

    grid_bpm: float
    judgment: GroundTruthField
    aspects: dict[str, GroundTruthField] = field(default_factory=dict)
    note: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.aspects) - set(TEMPO_SWEEP_ASPECTS)
        if unknown:
            raise ValueError(
                f"unknown tempo-sweep aspect(s): {sorted(unknown)}; "
                f"valid aspects are {TEMPO_SWEEP_ASPECTS}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "grid_bpm": self.grid_bpm,
            "judgment": self.judgment.to_dict(),
            "aspects": {name: f.to_dict() for name, f in self.aspects.items()},
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TempoAudition:
        return cls(
            grid_bpm=float(data["grid_bpm"]),
            judgment=GroundTruthField.from_dict(data["judgment"]),
            aspects={
                name: GroundTruthField.from_dict(f) for name, f in data.get("aspects", {}).items()
            },
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class ConstructionTimeline:
    """The measure-keyed view of one construction at one measure offset."""

    construction_id: str
    measure_offset: int  # host_measure = guest_measure + measure_offset
    transformation_note: str  # tempo/pitch settings this timeline was auditioned under
    entries: tuple[TimelineEntry, ...]
    offset_auditions: tuple[OffsetAudition, ...] = ()
    tempo_auditions: tuple[TempoAudition, ...] = ()

    def __post_init__(self) -> None:
        measures = [e.host_measure for e in self.entries]
        if len(measures) != len(set(measures)):
            raise ValueError("duplicate host_measure in timeline entries")
        if sorted(measures) != measures:
            raise ValueError("timeline entries must be in ascending host_measure order")
        offsets = [a.measure_offset for a in self.offset_auditions]
        if len(offsets) != len(set(offsets)):
            raise ValueError("duplicate measure_offset in offset_auditions")
        bpms = [t.grid_bpm for t in self.tempo_auditions]
        if len(bpms) != len(set(bpms)):
            raise ValueError("duplicate grid_bpm in tempo_auditions")

    def guest_measure(self, host_measure: int) -> int:
        return host_measure - self.measure_offset

    def to_dict(self) -> dict[str, Any]:
        return {
            "construction_id": self.construction_id,
            "measure_offset": self.measure_offset,
            "transformation_note": self.transformation_note,
            "entries": [e.to_dict() for e in self.entries],
            "offset_auditions": [a.to_dict() for a in self.offset_auditions],
            "tempo_auditions": [t.to_dict() for t in self.tempo_auditions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstructionTimeline:
        return cls(
            construction_id=data["construction_id"],
            measure_offset=int(data["measure_offset"]),
            transformation_note=data.get("transformation_note", ""),
            entries=tuple(TimelineEntry.from_dict(e) for e in data.get("entries", [])),
            offset_auditions=tuple(
                OffsetAudition.from_dict(a) for a in data.get("offset_auditions", [])
            ),
            tempo_auditions=tuple(
                TempoAudition.from_dict(t) for t in data.get("tempo_auditions", [])
            ),
        )


def load_timeline(path: Path) -> ConstructionTimeline:
    with open(path, encoding="utf-8") as fh:
        return ConstructionTimeline.from_dict(json.load(fh))


def render_markdown(timeline: ConstructionTimeline) -> str:
    """Human-readable table of the timeline plus the offset-audition ledger."""
    lines = [
        f"# Construction timeline: {timeline.construction_id}",
        "",
        f"Measure offset: host = guest + {timeline.measure_offset}",
        f"Transformation: {timeline.transformation_note}",
        "",
        "| host m. | guest m. | host section | guest section | guest | events | judgment |",
        "| --: | --: | :-- | :-- | :-- | :-- | :-- |",
    ]
    for e in timeline.entries:
        audibility = "" if e.guest_audibility is None else e.guest_audibility.value
        detail = list(e.events)
        if e.harmonic_judgment:
            detail.append(f"harmonic: {e.harmonic_judgment}")
        if e.texture_conflict:
            detail.append(f"texture: {e.texture_conflict}")
        detail.extend(f"cadence: {c}" for c in e.cadential_events)
        lines.append(
            f"| {e.host_measure} | {timeline.guest_measure(e.host_measure)} "
            f"| {e.host_section} | {e.guest_section} | {audibility} "
            f"| {'; '.join(detail)} | {e.judgment} |"
        )
    if timeline.offset_auditions:
        lines += [
            "",
            "## Offset auditions",
            "",
            "| offset (measures) | state | judgment |",
            "| --: | :-- | :-- |",
        ]
        for a in timeline.offset_auditions:
            value = "" if a.judgment.value is None else str(a.judgment.value)
            lines.append(f"| {a.measure_offset} | {a.judgment.state.value} | {value} |")
    if timeline.tempo_auditions:
        lines += [
            "",
            "## Tempo auditions (shared-grid sweep)",
            "",
            "| grid BPM | state | judgment |",
            "| --: | :-- | :-- |",
        ]
        for t in timeline.tempo_auditions:
            value = "" if t.judgment.value is None else str(t.judgment.value)
            lines.append(f"| {t.grid_bpm:g} | {t.judgment.state.value} | {value} |")
    return "\n".join(lines) + "\n"
