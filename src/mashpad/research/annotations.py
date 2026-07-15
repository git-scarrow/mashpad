"""Label-import seam: the executable path from real audio to the research
structures.

There is deliberately no annotation application, playback engine, or UI in
this repo. Aligned audition happens in external tools (djay); entering
timestamps against one recording happens in any label editor (e.g. an
Audacity label track, exported as plain tab-separated ``start  end  label``
text). This module is only the missing importer:

1. `parse_label_file` reads one exported label file (stdlib text parsing,
   no new dependencies);
2. `import_labels` matches label text against one side of a
   `MashupConstruction` — a label naming an `event_id` annotates that
   event; a label naming an `EventKind` value ("downbeat", "cadence", ...)
   appends to that side's grid-event list; anything else is reported
   unmatched, never silently dropped;
3. the result is merged into a **local, uncommitted** annotations JSON
   (`AnnotationSet` — the file the construction schema already
   anticipates; it contains real timestamps of commercial recordings, so
   it lives under `fixtures/local/`, gitignored, like `audio_index.json`);
4. `apply_annotations` flips matched construction event times to
   `ANNOTATED` — never `MEASURED` (the `AnchorEvent` guard enforces this
   independently) — and `basin_events` emits `TimedEvent`s so
   `mashpad.research.alignment_basin` can run against the annotations.

A label file annotates exactly ONE recording's timeline, so every import
names a side ("host"/"guest"); a label matching an event on the *other*
side is a loud error, not a skip — silence there would mislead. Region
labels use their start time as the event onset.

CLI (thin shim: ``scripts/import_labels.py``)::

    uv run scripts/import_labels.py \
        --construction tests/fixtures/construction_skyfall_in_the_end.json \
        --side host --labels fixtures/local/skyfall_labels.txt \
        --annotations fixtures/local/skyfall_in_the_end.annotations.json
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from mashpad.research.alignment_basin import TimedEvent
from mashpad.research.construction import (
    AnchorEvent,
    EventKind,
    GroundTruthField,
    MashupConstruction,
    ResolutionState,
    load_construction,
)

_EVENT_KIND_VALUES = {kind.value for kind in EventKind}
_SIDES = ("host", "guest")


@dataclass(frozen=True, slots=True)
class LabelRow:
    """One row of an exported label file. Point labels have start == end."""

    start_sec: float
    end_sec: float
    text: str


def parse_label_file(path: Path) -> tuple[LabelRow, ...]:
    """Parse an Audacity-style label export: one ``start<TAB>end<TAB>label``
    row per line. Blank lines are skipped; so are Audacity's extended
    frequency-range lines (which begin with a backslash). Malformed rows
    fail loudly with their line number — a mangled export should never be
    half-imported."""
    rows: list[LabelRow] = []
    with open(path, encoding="utf-8") as fh:
        for line_number, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if line.lstrip().startswith("\\"):
                continue  # Audacity extended-format frequency line
            parts = line.split("\t")
            if len(parts) < 2:
                raise ValueError(
                    f"{path}:{line_number}: expected 'start<TAB>end<TAB>label', got {line!r}"
                )
            try:
                start = float(parts[0])
                end = float(parts[1])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: non-numeric time in {line!r}") from exc
            text = parts[2].strip() if len(parts) > 2 else ""
            rows.append(LabelRow(start_sec=start, end_sec=end, text=text))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class EventAnnotation:
    """An annotated time for one named construction event."""

    time_sec: float
    method: str = "label_import"
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"time_sec": self.time_sec, "method": self.method, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventAnnotation:
        return cls(
            time_sec=float(data["time_sec"]),
            method=data.get("method", "label_import"),
            note=data.get("note", ""),
        )


@dataclass(frozen=True, slots=True)
class AnnotationSet:
    """The local, uncommitted annotation store for one construction.

    `events` holds times for named `AnchorEvent`s (keyed by event_id).
    `grid` holds anonymous repeated events per side and kind (e.g. every
    annotated downbeat) — the material the alignment basin needs beyond
    the handful of named anchors. Times are source-relative seconds."""

    construction_id: str
    events: dict[str, EventAnnotation] = field(default_factory=dict)
    grid: dict[str, dict[str, tuple[float, ...]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown_sides = set(self.grid) - set(_SIDES)
        if unknown_sides:
            raise ValueError(f"unknown grid side(s): {sorted(unknown_sides)}")
        for side, kinds in self.grid.items():
            unknown_kinds = set(kinds) - _EVENT_KIND_VALUES
            if unknown_kinds:
                raise ValueError(f"unknown grid event kind(s) for {side}: {sorted(unknown_kinds)}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "construction_id": self.construction_id,
            "events": {eid: ann.to_dict() for eid, ann in sorted(self.events.items())},
            "grid": {
                side: {kind: sorted(times) for kind, times in sorted(kinds.items())}
                for side, kinds in sorted(self.grid.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotationSet:
        return cls(
            construction_id=data["construction_id"],
            events={
                eid: EventAnnotation.from_dict(ann) for eid, ann in data.get("events", {}).items()
            },
            grid={
                side: {kind: tuple(float(t) for t in times) for kind, times in kinds.items()}
                for side, kinds in data.get("grid", {}).items()
            },
        )


def load_annotations(path: Path) -> AnnotationSet:
    with open(path, encoding="utf-8") as fh:
        return AnnotationSet.from_dict(json.load(fh))


def save_annotations(annotations: AnnotationSet, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(annotations.to_dict(), fh, indent=2, sort_keys=True)
        fh.write("\n")


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What one label import matched — surfaced so nothing is silently
    dropped: unmatched labels are the user's signal that a label was
    misspelled or not yet modeled as an event."""

    matched_event_ids: tuple[str, ...]
    grid_counts: dict[str, int]  # kind value -> rows added
    unmatched_labels: tuple[str, ...]

    @property
    def matched_anything(self) -> bool:
        return bool(self.matched_event_ids) or any(self.grid_counts.values())


def import_labels(
    annotations: AnnotationSet,
    construction: MashupConstruction,
    side: str,
    rows: tuple[LabelRow, ...],
    *,
    method: str = "label_import",
) -> tuple[AnnotationSet, ImportResult]:
    """Merge one side's label rows into the annotation set (pure — returns
    a new set). Matching rules per row, on the stripped label text:

    - equals an `event_id` on this side  -> event annotation (start time);
      re-import overwrites, duplicate within one file is an error;
    - equals an `event_id` on the OTHER side -> loud error (a label file
      annotates one recording; a cross-side match means the wrong file or
      the wrong --side);
    - equals an `EventKind` value ("downbeat", "cadence", ...) -> appended
      to this side's grid events of that kind;
    - anything else (including empty) -> reported unmatched.
    """
    if side not in _SIDES:
        raise ValueError(f"side must be one of {_SIDES}, got {side!r}")
    if annotations.construction_id != construction.construction_id:
        raise ValueError(
            f"annotation set is for {annotations.construction_id!r}, "
            f"not {construction.construction_id!r}"
        )
    events_by_id = {e.event_id: e for e in construction.events}

    new_events = dict(annotations.events)
    new_grid = {
        s: {k: list(times) for k, times in kinds.items()} for s, kinds in annotations.grid.items()
    }
    matched: list[str] = []
    grid_counts: dict[str, int] = {}
    unmatched: list[str] = []
    seen_this_import: set[str] = set()

    for row in rows:
        text = row.text.strip()
        if text in events_by_id:
            event = events_by_id[text]
            if event.side != side:
                raise ValueError(
                    f"label {text!r} names a {event.side} event, but this import annotates "
                    f"the {side} recording — wrong label file or wrong --side"
                )
            if text in seen_this_import:
                raise ValueError(
                    f"label {text!r} appears more than once in this file; a named event has "
                    "one time — use grid-kind labels (e.g. 'downbeat') for repeated events"
                )
            seen_this_import.add(text)
            note = "" if row.start_sec == row.end_sec else f"region label; end={row.end_sec}"
            new_events[text] = EventAnnotation(time_sec=row.start_sec, method=method, note=note)
            matched.append(text)
        elif text in _EVENT_KIND_VALUES:
            new_grid.setdefault(side, {}).setdefault(text, []).append(row.start_sec)
            grid_counts[text] = grid_counts.get(text, 0) + 1
        else:
            unmatched.append(text or f"<empty label at {row.start_sec}s>")

    merged = AnnotationSet(
        construction_id=annotations.construction_id,
        events=new_events,
        grid={
            s: {k: tuple(sorted(times)) for k, times in kinds.items()}
            for s, kinds in new_grid.items()
        },
    )
    return merged, ImportResult(
        matched_event_ids=tuple(matched),
        grid_counts=grid_counts,
        unmatched_labels=tuple(unmatched),
    )


def apply_annotations(
    construction: MashupConstruction, annotations: AnnotationSet
) -> MashupConstruction:
    """Return a new construction whose annotated events carry their imported
    times at `ANNOTATED` — never `MEASURED` (human/label-editor timestamps
    are annotation; the `AnchorEvent` guard independently rejects MEASURED
    event times). Unknown event ids fail loudly."""
    if annotations.construction_id != construction.construction_id:
        raise ValueError(
            f"annotation set is for {annotations.construction_id!r}, "
            f"not {construction.construction_id!r}"
        )
    known = {e.event_id for e in construction.events}
    unknown = set(annotations.events) - known
    if unknown:
        raise ValueError(f"annotation set names unknown event(s): {sorted(unknown)}")

    def annotate(event: AnchorEvent) -> AnchorEvent:
        ann = annotations.events.get(event.event_id)
        if ann is None:
            return event
        return replace(
            event,
            time_sec=GroundTruthField(
                state=ResolutionState.ANNOTATED,
                value=ann.time_sec,
                unit="sec",
                method=ann.method,
                note=ann.note,
            ),
        )

    return replace(construction, events=tuple(annotate(e) for e in construction.events))


def basin_events(
    construction: MashupConstruction,
    annotations: AnnotationSet,
    side: str,
    weight_by_kind: dict[EventKind, float] | None = None,
) -> list[TimedEvent]:
    """One side's `TimedEvent`s for the alignment basin: this side's grid
    events plus its annotated named events, sorted by time. Weights come
    from `weight_by_kind` (default 1.0) — how much a convergence anchor
    outweighs a routine downbeat is an experimental knob, not a truth."""
    if side not in _SIDES:
        raise ValueError(f"side must be one of {_SIDES}, got {side!r}")
    weights = weight_by_kind or {}
    events: list[TimedEvent] = []
    for kind_value, times in annotations.grid.get(side, {}).items():
        kind = EventKind(kind_value)
        for t in times:
            events.append(TimedEvent(time_sec=t, kind=kind, weight=weights.get(kind, 1.0)))
    events_by_id = {e.event_id: e for e in construction.events}
    for event_id, ann in annotations.events.items():
        event = events_by_id[event_id]
        if event.side != side:
            continue
        events.append(
            TimedEvent(
                time_sec=ann.time_sec,
                kind=event.kind,
                weight=weights.get(event.kind, 1.0),
            )
        )
    return sorted(events, key=lambda e: e.time_sec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import an exported label file (e.g. an Audacity label track) into a local "
            "construction annotation set. Labels naming an event_id annotate that event; "
            "labels naming an event kind (downbeat, cadence, ...) become grid events; "
            "everything else is reported unmatched."
        )
    )
    parser.add_argument(
        "--construction", required=True, type=Path, help="construction fixture JSON"
    )
    parser.add_argument("--labels", required=True, type=Path, help="exported label file")
    parser.add_argument(
        "--side", required=True, choices=_SIDES, help="which recording the label file annotates"
    )
    parser.add_argument(
        "--annotations",
        required=True,
        type=Path,
        help="local annotation JSON to merge into (created if missing; keep it under "
        "fixtures/local/ — it contains real timestamps and must never be committed)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be imported without writing"
    )
    args = parser.parse_args(argv)

    construction = load_construction(args.construction)
    if args.annotations.exists():
        annotations = load_annotations(args.annotations)
    else:
        annotations = AnnotationSet(construction_id=construction.construction_id)

    rows = parse_label_file(args.labels)
    merged, result = import_labels(annotations, construction, args.side, rows)

    print(f"labels read: {len(rows)}")
    print(f"event annotations ({len(result.matched_event_ids)}): ", end="")
    print(", ".join(result.matched_event_ids) or "-")
    for kind, count in sorted(result.grid_counts.items()):
        print(f"grid[{args.side}][{kind}]: +{count}")
    if result.unmatched_labels:
        print(f"unmatched labels ({len(result.unmatched_labels)}):")
        for label in result.unmatched_labels:
            print(f"  {label}")

    annotated = apply_annotations(construction, merged)
    still_open = [
        name
        for name in annotated.unresolved_fields()
        if name.startswith("event:")
        and annotated.event(name[len("event:") : -len(".time_sec")]).side == args.side
    ]
    print(f"{args.side} event times still unresolved ({len(still_open)}):")
    for name in still_open:
        print(f"  {name}")

    if not result.matched_anything:
        print("nothing matched — nothing written")
        return 1
    if args.dry_run:
        print("dry run — nothing written")
        return 0
    save_annotations(merged, args.annotations)
    print(f"wrote {args.annotations}")
    return 0
