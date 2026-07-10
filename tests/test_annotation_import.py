"""Tests for the label-import seam (`mashpad.research.annotations`).

This is the executable path from real audio to the research structures:
external label-editor export -> local annotation JSON -> construction
event times flipped to ANNOTATED -> TimedEvents for the alignment basin.
Everything here runs on synthetic label text written inside the tests —
no audio, no real timestamps committed."""

from pathlib import Path

import pytest

from mashpad.research.alignment_basin import basin, is_distinguished
from mashpad.research.annotations import (
    AnnotationSet,
    EventAnnotation,
    apply_annotations,
    basin_events,
    import_labels,
    load_annotations,
    main,
    parse_label_file,
    save_annotations,
)
from mashpad.research.construction import (
    EventKind,
    ResolutionState,
    load_construction,
)

FIXTURE = Path(__file__).parent / "fixtures" / "construction_skyfall_in_the_end.json"


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- parsing ----------------------------------------------------------------


def test_parse_label_file_handles_points_regions_blanks_and_frequency_lines(tmp_path):
    labels = _write(
        tmp_path / "labels.txt",
        "1.50\t1.50\thost.fall\n"
        "\n"
        "2.25\t4.00\tchorus region\n"
        "\\\t440.0\t880.0\n"  # Audacity extended-format frequency line
        "5.00\t5.00\tdownbeat\n",
    )
    rows = parse_label_file(labels)
    assert [(r.start_sec, r.end_sec, r.text) for r in rows] == [
        (1.5, 1.5, "host.fall"),
        (2.25, 4.0, "chorus region"),
        (5.0, 5.0, "downbeat"),
    ]


def test_parse_label_file_fails_loudly_on_malformed_rows(tmp_path):
    with pytest.raises(ValueError, match="labels.txt:1"):
        parse_label_file(_write(tmp_path / "labels.txt", "no tabs here\n"))
    with pytest.raises(ValueError, match="non-numeric"):
        parse_label_file(_write(tmp_path / "bad.txt", "abc\t1.0\tx\n"))


# --- import matching --------------------------------------------------------


def _fresh_set():
    construction = load_construction(FIXTURE)
    return construction, AnnotationSet(construction_id=construction.construction_id)


def test_import_matches_event_ids_and_grid_kinds_and_reports_the_rest(tmp_path):
    construction, annotations = _fresh_set()
    rows = parse_label_file(
        _write(
            tmp_path / "host.txt",
            "10.00\t10.00\thost.fall\n"
            "1.00\t1.00\tdownbeat\n"
            "3.00\t3.00\tdownbeat\n"
            "7.77\t7.77\tsomething else\n",
        )
    )
    merged, result = import_labels(annotations, construction, "host", rows)
    assert result.matched_event_ids == ("host.fall",)
    assert result.grid_counts == {"downbeat": 2}
    assert result.unmatched_labels == ("something else",)
    assert result.matched_anything
    assert merged.events["host.fall"].time_sec == 10.0
    assert merged.grid["host"]["downbeat"] == (1.0, 3.0)
    # Pure merge: the input set is untouched.
    assert not annotations.events and not annotations.grid


def test_import_rejects_cross_side_and_duplicate_event_labels(tmp_path):
    construction, annotations = _fresh_set()
    guest_label_in_host_file = parse_label_file(
        _write(tmp_path / "wrong.txt", "1.0\t1.0\tguest.hard\n")
    )
    with pytest.raises(ValueError, match="wrong label file or wrong --side"):
        import_labels(annotations, construction, "host", guest_label_in_host_file)
    duplicated = parse_label_file(
        _write(tmp_path / "dup.txt", "1.0\t1.0\thost.fall\n2.0\t2.0\thost.fall\n")
    )
    with pytest.raises(ValueError, match="appears more than once"):
        import_labels(annotations, construction, "host", duplicated)


def test_import_rejects_mismatched_construction_id(tmp_path):
    construction, _ = _fresh_set()
    other = AnnotationSet(construction_id="CONSTR_other")
    rows = parse_label_file(_write(tmp_path / "l.txt", "1.0\t1.0\tdownbeat\n"))
    with pytest.raises(ValueError, match="annotation set is for"):
        import_labels(other, construction, "host", rows)


def test_reimport_overwrites_event_time_and_round_trips(tmp_path):
    construction, annotations = _fresh_set()
    first = parse_label_file(_write(tmp_path / "a.txt", "10.0\t10.0\thost.fall\n"))
    merged, _ = import_labels(annotations, construction, "host", first)
    second = parse_label_file(_write(tmp_path / "b.txt", "11.5\t11.5\thost.fall\n"))
    merged, _ = import_labels(merged, construction, "host", second)
    assert merged.events["host.fall"].time_sec == 11.5

    store = tmp_path / "local" / "annotations.json"
    save_annotations(merged, store)
    assert load_annotations(store) == merged


# --- applying to the construction -------------------------------------------


def test_apply_flips_event_times_to_annotated_never_measured():
    construction, _ = _fresh_set()
    annotations = AnnotationSet(
        construction_id=construction.construction_id,
        events={"host.fall": EventAnnotation(time_sec=123.4)},
    )
    annotated = apply_annotations(construction, annotations)
    fall = annotated.event("host.fall")
    assert fall.time_sec.state is ResolutionState.ANNOTATED
    assert fall.time_sec.state is not ResolutionState.MEASURED
    assert fall.time_sec.value == 123.4
    assert fall.time_sec.unit == "sec"
    # Untouched events keep their unresolved state; the original is unchanged.
    assert annotated.event("guest.hard").time_sec.state is ResolutionState.UNRESOLVED
    assert construction.event("host.fall").time_sec.state is ResolutionState.UNRESOLVED
    assert "event:host.fall.time_sec" not in annotated.unresolved_fields()


def test_apply_rejects_unknown_events_and_wrong_construction():
    construction, _ = _fresh_set()
    with pytest.raises(ValueError, match="unknown event"):
        apply_annotations(
            construction,
            AnnotationSet(
                construction_id=construction.construction_id,
                events={"host.nonexistent": EventAnnotation(time_sec=1.0)},
            ),
        )
    with pytest.raises(ValueError, match="annotation set is for"):
        apply_annotations(construction, AnnotationSet(construction_id="CONSTR_other"))


# --- basin events -----------------------------------------------------------


def test_basin_events_combines_grid_and_named_events_per_side():
    construction, _ = _fresh_set()
    annotations = AnnotationSet(
        construction_id=construction.construction_id,
        events={
            "host.fall": EventAnnotation(time_sec=6.3),
            "guest.hard": EventAnnotation(time_sec=6.3),
        },
        grid={"host": {"downbeat": (0.0, 2.0, 4.0)}},
    )
    host = basin_events(
        construction, annotations, "host", weight_by_kind={EventKind.LYRIC_STRESS_ONSET: 4.0}
    )
    assert [(e.time_sec, e.kind) for e in host] == [
        (0.0, EventKind.DOWNBEAT),
        (2.0, EventKind.DOWNBEAT),
        (4.0, EventKind.DOWNBEAT),
        (6.3, EventKind.LYRIC_STRESS_ONSET),
    ]
    assert host[-1].weight == 4.0
    guest = basin_events(construction, annotations, "guest")
    assert [(e.time_sec, e.kind) for e in guest] == [(6.3, EventKind.LYRIC_STRESS_ONSET)]


# --- end to end: label files -> CLI -> annotations -> basin ------------------


def test_full_path_from_label_files_to_a_distinguishable_basin(tmp_path):
    """The whole seam in one pass, against the real committed construction
    fixture and synthetic label text: two label files (one per side) are
    imported via the CLI, merged into one local annotation JSON, applied
    to the construction, converted to TimedEvents, and the basin then
    distinguishes the intended offset from whole-bar corruptions — the
    experiment the seam exists to make executable."""
    bar = 2.0
    host_lines = [f"{i * bar:.2f}\t{i * bar:.2f}\tdownbeat" for i in range(16)]
    host_lines.append("6.30\t6.30\thost.fall")
    guest_lines = [f"{8.0 + i * bar:.2f}\t{8.0 + i * bar:.2f}\tdownbeat" for i in range(8)]
    guest_lines.append("6.30\t6.30\tguest.hard")
    host_labels = _write(tmp_path / "host_labels.txt", "\n".join(host_lines) + "\n")
    guest_labels = _write(tmp_path / "guest_labels.txt", "\n".join(guest_lines) + "\n")
    store = tmp_path / "annotations.json"

    for side, labels in (("host", host_labels), ("guest", guest_labels)):
        exit_code = main(
            [
                "--construction",
                str(FIXTURE),
                "--side",
                side,
                "--labels",
                str(labels),
                "--annotations",
                str(store),
            ]
        )
        assert exit_code == 0
    assert store.exists()

    construction = load_construction(FIXTURE)
    annotations = load_annotations(store)
    annotated = apply_annotations(construction, annotations)
    assert annotated.event("host.fall").time_sec.state is ResolutionState.ANNOTATED
    assert annotated.event("guest.hard").time_sec.state is ResolutionState.ANNOTATED

    weights = {EventKind.LYRIC_STRESS_ONSET: 4.0}
    host_events = basin_events(annotated, annotations, "host", weight_by_kind=weights)
    guest_events = basin_events(annotated, annotations, "guest", weight_by_kind=weights)
    beat = bar / 4
    scores = basin(host_events, guest_events, [0.0, bar, -bar, 2 * bar], beat)
    assert is_distinguished(scores, 0.0, margin_beats=0.5)


def test_cli_dry_run_writes_nothing_and_no_match_exits_nonzero(tmp_path):
    labels = _write(tmp_path / "labels.txt", "1.0\t1.0\tdownbeat\n")
    store = tmp_path / "annotations.json"
    args = [
        "--construction",
        str(FIXTURE),
        "--side",
        "host",
        "--labels",
        str(labels),
        "--annotations",
        str(store),
    ]
    assert main([*args, "--dry-run"]) == 0
    assert not store.exists()

    nothing = _write(tmp_path / "nothing.txt", "1.0\t1.0\tnot a known label\n")
    args[5] = str(nothing)
    assert main(args) == 1
    assert not store.exists()
