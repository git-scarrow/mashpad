"""Tests for the research-layer construction record and alignment basin.

Three kinds of guarantee, none of which touches production scoring:

1. The ground-truth construction fixture is loadable, round-trips, and
   honestly reports its unresolved fields (anti-laundering guards included).
2. An executable *negative* result: production `evaluate_move` is
   structurally blind to alignment — shifting or scrambling every section
   time on the guest changes nothing in the CompatibilityProfile, so v0
   cannot rank the intended landing above corrupted offsets even in
   principle. If this test ever fails, production gained an offset-aware
   input and the design memo's central claim must be revisited.
3. The basin harness's two findings: beat-grid events alone leave the
   intended offset tied with whole-bar shifts (periodic ridge), and a
   single aperiodic lyric-anchor pair breaks the tie.
"""

from pathlib import Path

import pytest

from mashpad.models import (
    MashupMoveType,
    Section,
    Track,
    TrackAnalysis,
    TrackRole,
)
from mashpad.research.alignment_basin import (
    TimedEvent,
    alignment_error,
    basin,
    is_distinguished,
    rank_offsets,
)
from mashpad.research.construction import (
    AnchorEvent,
    EventKind,
    GroundTruthField,
    GuestAudibility,
    ResolutionState,
    load_construction,
)
from mashpad.research.timeline import (
    ConstructionTimeline,
    TempoAudition,
    TimelineEntry,
    load_timeline,
    render_markdown,
)
from mashpad.scoring import evaluate_move

FIXTURE = Path(__file__).parent / "fixtures" / "construction_skyfall_in_the_end.json"
TIMELINE_FIXTURE = Path(__file__).parent / "fixtures" / "timeline_skyfall_in_the_end.json"


# --- 1. The construction record -------------------------------------------


def test_fixture_loads_and_round_trips():
    construction = load_construction(FIXTURE)
    assert construction.primary_move_type is MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY
    assert construction.host_role is TrackRole.FULL_MIX
    assert construction.guest_role is TrackRole.VOCAL
    assert construction.host_retains_own_vocal is True
    assert construction.conformed_side == "guest"
    rebuilt = type(construction).from_dict(construction.to_dict())
    assert rebuilt == construction


def test_fixture_is_honest_about_what_is_unknown():
    construction = load_construction(FIXTURE)
    unresolved = construction.unresolved_fields()
    # Every empirical parameter of this construction starts unresolved or
    # as a bounded hypothesis — knowing the mashup works does not mean its
    # parameters are known.
    assert "convergence:hard_on_fall.offset_beats" in unresolved
    assert "convergence:hard_on_fall.tolerance_beats" in unresolved
    assert "event:host.fall.time_sec" in unresolved
    # Offset drift, the tempo viability region, and the window's precise
    # boundaries stay open pending verification against the source audio.
    assert "grid.offset_constant_across_window" in unresolved
    assert "grid.viable_grid_bpm_region" in unresolved
    assert "window:chorus2_through_final_chorus.start_host_measure" in unresolved
    # ...but the session tempo evidence, the user-attested +2 frame
    # relation, and the listening judgments are resolved: guest 105 was
    # correctly measured by djay, host ~74 is the user's octave
    # correction, the 74 grid point and window judgment are witnessed.
    assert "guest_bpm" not in unresolved
    assert "host_bpm" not in unresolved
    assert "grid.measure_offset" not in unresolved
    assert "grid.shared_grid_bpm" not in unresolved
    assert "window:chorus2_through_final_chorus.judgment" not in unresolved
    # And nothing claims to be measured.
    assert not any(f.startswith("measured") for f in unresolved)  # sanity on the helper's contract
    offset = construction.convergences[0].offset_beats
    assert offset.state is ResolutionState.HYPOTHESIS
    assert offset.bounds == (-1.0, 1.0)


def test_measured_state_rejects_laundering_methods():
    with pytest.raises(ValueError, match="MEASURED requires a real measurement method"):
        GroundTruthField(ResolutionState.MEASURED, value=77.0, method="manual_annotation")
    with pytest.raises(ValueError, match="MEASURED requires a real measurement method"):
        GroundTruthField(ResolutionState.MEASURED, value=77.0)


def test_event_times_cannot_claim_measured_yet():
    # No sanctioned measurement seam exists for lyric/section event times,
    # so a MEASURED event time could only be laundered annotation.
    with pytest.raises(ValueError, match="cannot be MEASURED yet"):
        AnchorEvent(
            event_id="host.fall",
            side="host",
            kind=EventKind.LYRIC_STRESS_ONSET,
            time_sec=GroundTruthField(
                ResolutionState.MEASURED, value=123.4, unit="sec", method="some_backend"
            ),
        )


def test_hypothesis_requires_bounds_or_value():
    with pytest.raises(ValueError, match="HYPOTHESIS must carry bounds"):
        GroundTruthField(ResolutionState.HYPOTHESIS)


def test_convergence_must_pair_guest_with_host():
    construction = load_construction(FIXTURE)
    data = construction.to_dict()
    bad = data["convergences"][0]
    bad["guest_event_id"], bad["host_event_id"] = bad["host_event_id"], bad["guest_event_id"]
    with pytest.raises(ValueError, match="must pair a guest event with a host event"):
        type(construction).from_dict(data)


def test_grid_alignment_records_the_djay_witness():
    """The 2026-07-09 djay Pro session evidence, with honest provenance:
    listening judgments are annotated; the guest's 105 BPM was correctly
    measured by djay (research-layer 'measured'); the host's ~74 is the
    user's correction of djay's ~148 octave-doubled reading (annotated);
    values read off djay's display or beat grids stay hypotheses."""
    construction = load_construction(FIXTURE)
    grid = construction.grid
    assert grid is not None
    # 74 is the witnessed working point, not the unique grid...
    assert grid.shared_grid_bpm.state is ResolutionState.ANNOTATED
    assert grid.shared_grid_bpm.value == 74.0
    # ...inside a provisional human-auditioned viability region.
    assert grid.viable_grid_bpm_region is not None
    assert grid.viable_grid_bpm_region.state is ResolutionState.HYPOTHESIS
    assert grid.viable_grid_bpm_region.bounds == (74.0, 90.0)
    assert grid.measure_offset.state is ResolutionState.ANNOTATED
    assert grid.measure_offset.value == 2.0
    assert (3, 1) in grid.example_correspondences
    # Tempo evidence: estimation correctness is separated from the octave
    # interpretation and from the transformation choice.
    assert construction.guest_bpm.state is ResolutionState.MEASURED
    assert construction.guest_bpm.value == 105.0
    assert construction.host_bpm.state is ResolutionState.ANNOTATED
    assert construction.host_bpm.value == 74.0  # user-corrected from djay's ~148
    assert construction.tempo_ratio.value == 0.705  # 74/105, at the witnessed point only
    assert construction.pitch_shift_semitones.state is ResolutionState.HYPOTHESIS
    assert construction.pitch_shift_semitones.value == 2.0  # verify from session, not screenshot
    window = next(w for w in grid.windows if w.window_id == "chorus2_through_final_chorus")
    assert window.host_sections == ("chorus 2", "bridge", "final chorus")
    assert window.judgment.state is ResolutionState.ANNOTATED


def test_grid_rejects_correspondences_that_contradict_the_offset():
    construction = load_construction(FIXTURE)
    data = construction.to_dict()
    data["grid"]["example_correspondences"].append([80, 50])  # offset 30, not 22
    with pytest.raises(ValueError, match="contradicts"):
        type(construction).from_dict(data)


def test_construction_is_a_witness_not_a_uniqueness_claim():
    construction = load_construction(FIXTURE)
    assert construction.claim_scope == "witness"
    data = construction.to_dict()
    data["claim_scope"] = "unique_best_overlay"
    with pytest.raises(ValueError, match="existence proof"):
        type(construction).from_dict(data)


def test_grid_anchor_is_downbeat_to_downbeat_with_session_labels_kept_apart():
    """The primary structural anchor: first metrically established downbeats
    aligned, represented by (unresolved) source timestamps + musical
    function. djay's bar labels are recorded, but only as session-specific
    annotations — an app may count Skyfall's brass opening as a measure,
    pickup, or nothing."""
    construction = load_construction(FIXTURE)
    anchor = construction.grid.anchor
    assert anchor is not None
    host_event = construction.event(anchor.host_event_id)
    guest_event = construction.event(anchor.guest_event_id)
    assert host_event.kind is EventKind.DOWNBEAT
    assert guest_event.kind is EventKind.DOWNBEAT
    assert host_event.time_sec.state is ResolutionState.UNRESOLVED  # ground truth pending
    assert "bar 3" in anchor.session_bar_labels and "bar 1" in anchor.session_bar_labels
    # The ambiguous opening is documented on the host anchor event itself.
    assert "pickup" in host_event.time_sec.note


def test_grid_anchor_must_reference_real_events_on_the_right_sides():
    construction = load_construction(FIXTURE)
    data = construction.to_dict()
    data["grid"]["anchor"]["host_event_id"] = "host.nonexistent"
    with pytest.raises(ValueError, match="unknown event"):
        type(construction).from_dict(data)
    data = construction.to_dict()
    data["grid"]["anchor"]["host_event_id"] = "guest.downbeat.first_regular"
    with pytest.raises(ValueError, match="host event .* is on side"):
        type(construction).from_dict(data)


def test_windows_encode_aligned_but_muted_and_selective_entrance():
    """Structural synchronization is not admissibility: the guest is on the
    grid from the anchor but muted through its clashing piano bars, enters
    around its bar 8, and is fully audible through the effective window.
    The clash judgment and the entrance judgment are both human-annotated;
    the cadential enabler is a hypothesis carried by its own convergence."""
    construction = load_construction(FIXTURE)
    windows = {w.window_id: w for w in construction.grid.windows}
    muted = windows["aligned_intro_guest_muted"]
    assert muted.guest_audibility is GuestAudibility.MUTED
    assert muted.judgment.state is ResolutionState.ANNOTATED
    assert "piano" in muted.judgment.note
    entrance = windows["guest_entrance"]
    assert entrance.guest_audibility is GuestAudibility.ENTERING
    assert entrance.judgment.state is ResolutionState.ANNOTATED
    main = windows["chorus2_through_final_chorus"]
    assert main.guest_audibility is GuestAudibility.AUDIBLE
    by_id = {c.convergence_id: c for c in construction.convergences}
    cadential = by_id["cadential_entrance"]
    assert cadential.offset_beats.state is ResolutionState.HYPOTHESIS
    assert "harmonic_arrival" in cadential.character


# --- 2. Executable negative result: v0 is offset-blind ---------------------


def _analysis(name: str, bpm: float, key: str, sections: tuple[Section, ...]) -> TrackAnalysis:
    return TrackAnalysis(track=Track(path=Path(name)), bpm=bpm, key=key, sections=sections)


def _sections(start_offset_sec: float) -> tuple[Section, ...]:
    return tuple(
        Section(
            label=label,
            start_sec=start_offset_sec + i * 20.0,
            end_sec=start_offset_sec + i * 20.0 + 20.0,
            confidence=0.85,
        )
        for i, label in enumerate(("intro", "verse", "chorus"))
    )


def test_production_scoring_is_structurally_offset_blind():
    """Shifting every guest section by any offset — i.e. presenting a
    completely different temporal alignment of the same two tracks — yields
    a byte-identical CompatibilityProfile. This is the locked, executable
    form of the claim that v0 cannot represent, measure, or rank *where*
    the guest enters, only whether the tracks are globally compatible."""
    host = _analysis("host.mp3", 77.0, "C minor", _sections(0.0))
    profiles = []
    for offset in (0.0, 0.39, -0.78, 3.0, 250.0):
        guest = _analysis("guest.mp3", 105.0, "D# minor", _sections(offset))
        profiles.append(
            evaluate_move(
                host,
                guest,
                move_type=MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY,
                track_a_role=TrackRole.INSTRUMENTAL,
                track_b_role=TrackRole.VOCAL,
            )
        )
    first = profiles[0]
    assert all(p == first for p in profiles[1:])


# --- 3. The alignment basin ------------------------------------------------

BEAT = 0.5  # 120 BPM beat period, arbitrary but explicit
BAR = 4 * BEAT


def _grid(kind: EventKind, start: float, step: float, count: int) -> list[TimedEvent]:
    return [TimedEvent(start + i * step, kind) for i in range(count)]


def test_beat_grid_alone_has_a_periodic_ridge():
    """With only bar-level downbeats, the intended offset (0) ties exactly
    with every whole-bar shift: grid compatibility cannot say where the
    guest should land, only that it should land *on the grid*."""
    # Guest grid sits interior to the host grid so a +/- one-bar shift keeps
    # every guest event over host coverage (no edge effects).
    host = _grid(EventKind.DOWNBEAT, 0.0, BAR, 16)
    guest = _grid(EventKind.DOWNBEAT, 4 * BAR, BAR, 8)
    offsets = [0.0, BAR, -BAR, BEAT / 2, -BEAT / 2]
    scores = {s.offset_sec: s.error_beats for s in basin(host, guest, offsets, BEAT)}
    assert scores[0.0] == pytest.approx(scores[BAR])
    assert scores[0.0] == pytest.approx(scores[-BAR])
    assert scores[BEAT / 2] > scores[0.0]  # off-grid is still worse
    assert not is_distinguished(basin(host, guest, offsets, BEAT), 0.0, margin_beats=0.1)


def test_single_lyric_anchor_breaks_the_tie():
    """Adding one aperiodic anchor pair — guest 'hard' onto host 'fall' —
    makes the intended offset a strict minimum over whole-bar shifts. This
    is the smallest feature production scoring is missing."""
    host = _grid(EventKind.DOWNBEAT, 0.0, BAR, 16) + [
        TimedEvent(6.3, EventKind.LYRIC_STRESS_ONSET, weight=4.0)
    ]
    guest = _grid(EventKind.DOWNBEAT, 4 * BAR, BAR, 8) + [
        TimedEvent(6.3, EventKind.LYRIC_STRESS_ONSET, weight=4.0)
    ]
    offsets = [0.0, BAR, -BAR, 2 * BAR, BEAT / 2]
    scores = basin(host, guest, offsets, BEAT)
    assert is_distinguished(scores, 0.0, margin_beats=0.5)
    best = rank_offsets(scores)[0]
    assert best.offset_sec == 0.0
    assert best.error_beats == pytest.approx(0.0)


def test_anchor_kinds_do_not_cross_match():
    """A guest lyric anchor near a host downbeat is not a convergence: with
    no host lyric anchor to match, the guest anchor cannot be scored, and
    scoring collapses to the grid (which is the honest reading)."""
    host = _grid(EventKind.DOWNBEAT, 0.0, BAR, 4)
    guest = [TimedEvent(0.0, EventKind.LYRIC_STRESS_ONSET)]
    with pytest.raises(ValueError, match="no guest event has a compatible host event"):
        alignment_error(host, guest, 0.0, BEAT)


def test_alignment_error_rejects_bad_beat_period():
    with pytest.raises(ValueError, match="beat_period_sec must be positive"):
        alignment_error(
            [TimedEvent(0.0, EventKind.DOWNBEAT)], [TimedEvent(0.0, EventKind.DOWNBEAT)], 0.0, 0.0
        )


# --- 4. The construction timeline ------------------------------------------


def test_timeline_loads_and_round_trips():
    timeline = load_timeline(TIMELINE_FIXTURE)
    assert timeline.construction_id == "CONSTR_skyfall_in_the_end_v1"
    # The timeline is keyed to the downbeat-anchor strategy in the djay
    # bar-label frame: Skyfall bar 3 = In the End bar 1 -> host = guest + 2.
    assert timeline.measure_offset == 2
    assert timeline.guest_measure(3) == 1
    rebuilt = ConstructionTimeline.from_dict(timeline.to_dict())
    assert rebuilt == timeline


def test_offset_frame_resolved_by_user():
    """The +2 djay-frame relation (Skyfall bar 3 = In the End bar 1) is the
    witnessed structural relationship, user-attested; the earlier '+22'
    observation was a local measure-number readout from a different
    numbering frame, not a rival alignment, and required no further
    annotation to settle. The record still keeps the epistemic layering:
    the value is frame-specific (djay labels), the musical anchor remains
    downbeat-to-downbeat with source timestamps as ground truth."""
    timeline = load_timeline(TIMELINE_FIXTURE)
    construction = load_construction(FIXTURE)
    grid = construction.grid
    assert grid is not None
    assert grid.measure_offset.state is ResolutionState.ANNOTATED
    assert grid.measure_offset.value == 2.0
    assert grid.measure_offset.method == "user_attested"
    assert timeline.measure_offset == 2  # construction and timeline frames agree
    note = grid.measure_offset.note.lower()
    assert "reconciliation pending" not in note
    assert "different numbering frame" in note
    for host_m, guest_m in grid.example_correspondences:
        assert host_m - guest_m == 2


def test_timeline_records_witness_and_unauditioned_neighbors():
    timeline = load_timeline(TIMELINE_FIXTURE)
    by_offset = {a.measure_offset: a.judgment for a in timeline.offset_auditions}
    # The witnessed +2 anchor alignment is annotated, and so is the
    # user-attested delayed registration (~+22): two distinct members of
    # the construction family, both human-attested and (for the delayed
    # one) machine-corroborated by the registration search.
    assert by_offset[2].state is ResolutionState.ANNOTATED
    assert by_offset[22].state is ResolutionState.ANNOTATED
    assert set(by_offset) == {1, 2, 3, 22}
    # ...while neighboring offsets are recorded but explicitly not yet
    # auditioned — "nearby offsets degrade the whole passage" is a
    # question, not a given.
    for neighbor in (1, 3):
        assert by_offset[neighbor].state is ResolutionState.UNRESOLVED


def test_timeline_entries_separate_app_labels_from_source_structure():
    """Application bar labels and source-audio structure are different
    facts: the entries carry djay labels and (unresolved) source-relative
    downbeat timestamps separately, and the metrically ambiguous opening
    is recorded as host material before the anchor."""
    timeline = load_timeline(TIMELINE_FIXTURE)
    by_measure = {e.host_measure: e for e in timeline.entries}
    anchor_row = by_measure[3]
    assert anchor_row.host_app_bar == 3
    assert anchor_row.guest_app_bar == 1
    assert anchor_row.host_downbeat_sec is not None
    assert anchor_row.host_downbeat_sec.state is ResolutionState.UNRESOLVED
    opening = by_measure[1]
    assert "ambiguous" in opening.events[0]


def test_timeline_entries_encode_audibility_progression():
    """Synchronized is not audible: the guest is aligned-but-muted through
    its clashing piano bars, entering at ~bar 8, then fully audible."""
    timeline = load_timeline(TIMELINE_FIXTURE)
    by_measure = {e.host_measure: e for e in timeline.entries}
    assert by_measure[3].guest_audibility is GuestAudibility.MUTED
    assert "piano" in by_measure[3].texture_conflict
    assert by_measure[10].guest_audibility is GuestAudibility.ENTERING
    assert by_measure[10].guest_app_bar == 8
    assert by_measure[10].cadential_events  # the entrance-enabler hypothesis
    assert by_measure[11].guest_audibility is GuestAudibility.AUDIBLE


def test_timeline_renders_aligned_measures():
    rendered = render_markdown(load_timeline(TIMELINE_FIXTURE))
    assert "host = guest + 2" in rendered
    assert "| 3 | 1 |" in rendered
    assert "| muted " in rendered
    assert "## Offset auditions" in rendered


def test_timeline_rejects_disorder_and_duplicates():
    with pytest.raises(ValueError, match="ascending host_measure"):
        ConstructionTimeline(
            construction_id="x",
            measure_offset=22,
            transformation_note="",
            entries=(TimelineEntry(host_measure=78), TimelineEntry(host_measure=77)),
        )
    with pytest.raises(ValueError, match="duplicate host_measure"):
        ConstructionTimeline(
            construction_id="x",
            measure_offset=22,
            transformation_note="",
            entries=(TimelineEntry(host_measure=77), TimelineEntry(host_measure=77)),
        )


def test_tempo_sweep_ledger_records_witness_and_planned_candidates():
    """The tempo-sweep protocol: 74 is the auditioned working point; the
    other grid tempos are planned sweep candidates, explicitly unresolved
    so the viability region stays an estimate-from-audition, not a fit to
    one chosen BPM. The 96 probe sits beyond the hypothesized region to
    locate the host-rushed failure boundary rather than assume it."""
    timeline = load_timeline(TIMELINE_FIXTURE)
    by_bpm = {t.grid_bpm: t.judgment for t in timeline.tempo_auditions}
    assert by_bpm[74.0].state is ResolutionState.ANNOTATED
    for bpm in (78.0, 82.0, 86.0, 90.0, 96.0):
        assert by_bpm[bpm].state is ResolutionState.UNRESOLVED
    assert max(by_bpm) == 96.0  # a probe beyond the hypothesized 74-90 region


def test_tempo_audition_rejects_duplicates_and_unknown_aspects():
    ok = GroundTruthField(ResolutionState.UNRESOLVED)
    with pytest.raises(ValueError, match="duplicate grid_bpm"):
        ConstructionTimeline(
            construction_id="x",
            measure_offset=22,
            transformation_note="",
            entries=(),
            tempo_auditions=(
                TempoAudition(grid_bpm=74.0, judgment=ok),
                TempoAudition(grid_bpm=74.0, judgment=ok),
            ),
        )
    with pytest.raises(ValueError, match="unknown tempo-sweep aspect"):
        TempoAudition(grid_bpm=74.0, judgment=ok, aspects={"vibes": ok})


def test_render_includes_tempo_sweep_section():
    rendered = render_markdown(load_timeline(TIMELINE_FIXTURE))
    assert "## Tempo auditions (shared-grid sweep)" in rendered
    assert "| 74 | annotated |" in rendered
    assert "| 96 | unresolved |" in rendered
