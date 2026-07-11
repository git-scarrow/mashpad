"""Tests for automatic construction discovery (`mashpad.research.discovery`).

The hypothesis core is pure over `TrackFeatures`, so everything decision-
shaped is tested here with synthetic features — no audio, no librosa, and
no witnessed Skyfall/In the End values baked into the algorithm (the
74/148/105 numbers below are *test data* exercising general rules; the
real acceptance comparison runs through `witness_agreement` against the
committed construction fixture). One librosa-gated test synthesizes WAVs
in-test and drives the full extract -> propose path."""

import importlib.util
import json
import math
import struct
import wave
from pathlib import Path

import pytest

from mashpad.models import TempoCandidate
from mashpad.research.construction import load_construction
from mashpad.research.discovery import (
    AlignedBar,
    AlignmentCandidate,
    ConstructionHypothesis,
    TrackFeatures,
    best_pitch_shifts,
    choose_downbeat_phase,
    derive_bars,
    extract_features,
    find_entry_windows,
    first_stable_beat_index,
    metrical_interpretations,
    propose_constructions,
    propose_shared_tempos,
    rotate_chroma,
    search_alignments,
    witness_agreement,
)

FIXTURE = Path(__file__).parent / "fixtures" / "construction_skyfall_in_the_end.json"
_LIBROSA_INSTALLED = importlib.util.find_spec("librosa") is not None


# --- pitch shift ------------------------------------------------------------


def _unit(pitch_classes: dict[int, float]) -> tuple[float, ...]:
    vec = [0.0] * 12
    for pc, w in pitch_classes.items():
        vec[pc % 12] = w
    return tuple(vec)


def test_pitch_shift_recovers_a_transposition():
    host = _unit({0: 1.0, 4: 0.8, 7: 0.9})  # C-E-G mass
    guest = _unit({10: 1.0, 2: 0.8, 5: 0.9})  # the same mass two semitones down
    assert rotate_chroma(guest, 2) == host
    shifts = best_pitch_shifts(host, guest)
    assert shifts[0][0] == 2
    assert shifts[0][1] == pytest.approx(1.0)


# --- downbeats and stability --------------------------------------------------


def test_choose_downbeat_phase_prefers_the_accented_phase():
    strengths = tuple([3.0, 1.0, 1.0, 1.0] * 8)
    phase, confidence = choose_downbeat_phase(strengths, group=4)
    assert phase == 0
    assert confidence == pytest.approx(0.5)  # 3 / (3 + 1 + 1 + 1)


def test_first_stable_beat_skips_an_irregular_opening():
    # Two rubato openings, then a regular 0.5s grid: the stable index must
    # land where the prevailing meter starts, with no manual pin.
    beat_times = (0.0, 0.9, 1.2, 1.7, 2.2, 2.7, 3.2, 3.7, 4.2)
    assert first_stable_beat_index(beat_times) == 2


def _features(
    path: str,
    tracked_bpm: float,
    candidates: tuple[TempoCandidate, ...],
    n_beats: int = 64,
    accent_group: int = 4,
    chroma_row: tuple[float, ...] = _unit({0: 1.0, 4: 0.8, 7: 0.9}),
    chroma_rows: tuple[tuple[float, ...], ...] | None = None,
) -> TrackFeatures:
    period = 60.0 / tracked_bpm
    return TrackFeatures(
        path=path,
        duration_sec=n_beats * period,
        tracked_bpm=tracked_bpm,
        tempo_candidates=candidates,
        beat_times=tuple(i * period for i in range(n_beats)),
        beat_strengths=tuple(3.0 if i % accent_group == 0 else 1.0 for i in range(n_beats)),
        beat_chroma=chroma_rows
        if chroma_rows is not None
        else tuple(chroma_row for _ in range(n_beats)),
        beat_energy=tuple(0.8 for _ in range(n_beats)),
    )


def test_derive_bars_groups_tracked_beats_and_finds_the_phase():
    features = _features("x.wav", 120.0, (TempoCandidate(120.0, 0.6),), n_beats=33)
    bars = derive_bars(features, tracked_beats_per_bar=4)
    assert bars.phase == 0
    assert bars.first_downbeat_sec == 0.0
    assert len(bars.downbeat_times) == len(bars.bar_chroma) == len(bars.bar_energy) == 8


# --- metrical interpretations and shared tempo ---------------------------------


def test_half_time_interpretation_comes_from_the_candidate_set():
    features = _features(
        "x.wav",
        148.0,
        (
            TempoCandidate(148.0, 0.6),
            TempoCandidate(74.0, 0.25, multiplier_from_primary=0.5),
            TempoCandidate(296.0, 0.15, multiplier_from_primary=2.0),
        ),
    )
    interps = metrical_interpretations(features)
    assert [(round(i.bpm, 1), i.tracked_beats_per_bar) for i in interps] == [
        (148.0, 4),
        (74.0, 8),  # half-time reading; double-time (296) is not searched in v1
    ]


def test_shared_tempo_prefers_preserving_the_host():
    """Role-asymmetric cost: with a slow host and a faster guest, the
    host-preserving grid (guest slowed) must outrank host-stretched grids —
    a general rule, exercised here with the case's numbers as data."""
    grids = propose_shared_tempos(74.0, 105.0)
    assert grids[0].grid_bpm == 74.0
    assert grids[0].host_ratio == 1.0
    assert grids[0].guest_ratio == pytest.approx(74.0 / 105.0, abs=1e-4)
    assert [g.cost for g in grids] == sorted(g.cost for g in grids)


def test_octave_corrected_host_reading_beats_the_doubled_reading():
    """The best grid under the half-time host interpretation (74) must cost
    less than the best grid under the doubled reading (148): the octave
    choice changes the transformation path, and the asymmetric cost model
    must surface that without any hard-coded preference for slower."""
    best_half_time = propose_shared_tempos(74.0, 105.0)[0]
    best_doubled = propose_shared_tempos(148.0, 105.0)[0]
    assert best_half_time.cost < best_doubled.cost


# --- admissibility and entry windows -------------------------------------------


def _bar(index: int, harmonic: float, density: float = 0.5) -> AlignedBar:
    return AlignedBar(guest_bar=index, host_bar=index, harmonic_fit=harmonic, density=density)


def test_entry_window_starts_after_a_clashing_opening():
    """Seven aligned-but-clashing bars followed by a sustained admissible
    run: the ranked entrance must start at bar 8 and imply a mute window
    through bar 7 — the aligned-but-muted structure, machine-derived."""
    profile = tuple(_bar(i, 0.3) for i in range(1, 8)) + tuple(_bar(i, 0.9) for i in range(8, 24))
    windows = find_entry_windows(profile)
    assert windows[0].start_guest_bar == 8
    assert windows[0].end_guest_bar == 23
    assert windows[0].mean_harmonic_fit == pytest.approx(0.9)


def test_short_lucky_runs_are_not_entrances():
    profile = (
        tuple(_bar(i, 0.3) for i in range(1, 5))
        + tuple(_bar(i, 0.9) for i in range(5, 7))  # only 2 bars — too short
        + tuple(_bar(i, 0.3) for i in range(7, 12))
    )
    assert find_entry_windows(profile) == ()


# --- end to end on synthetic features -------------------------------------------


def test_propose_constructions_ranks_and_serializes():
    host_chroma = _unit({0: 1.0, 4: 0.8, 7: 0.9})
    guest_chroma = _unit({10: 1.0, 2: 0.8, 5: 0.9})  # +2 st below the host
    fast = _features(
        "fast.wav",
        148.0,
        (
            TempoCandidate(148.0, 0.6),
            TempoCandidate(74.0, 0.25, multiplier_from_primary=0.5),
        ),
        chroma_row=host_chroma,
    )
    other = _features(
        "other.wav",
        105.0,
        (TempoCandidate(105.0, 0.6),),
        chroma_row=guest_chroma,
    )
    hypotheses = propose_constructions(fast, other, top=10)
    assert hypotheses
    scores = [h.rank_score for h in hypotheses]
    assert scores == sorted(scores)
    # Both role assignments were searched.
    assert {h.host_path for h in hypotheses} == {"fast.wav", "other.wav"}
    # Among fast-as-host hypotheses, the half-time (74) host-preserving grid
    # must outrank every doubled-reading (148-anchored) hypothesis.
    fast_host = [h for h in hypotheses if h.host_path == "fast.wav"]
    best = fast_host[0]
    assert best.host_metrical_bpm == pytest.approx(74.0)
    assert best.shared_grid_bpm == pytest.approx(74.0)
    assert all(h.rank_score >= best.rank_score for h in fast_host if h.host_metrical_bpm > 100)
    # The transposition is recovered regardless of assignment direction.
    assert abs(best.pitch_shift_semitones) == 2
    # Uniform compatible chroma: admissible from the first bar, no mute.
    assert best.entry_windows and best.entry_windows[0].start_guest_bar == 1
    assert best.mute_through_guest_bar == 0
    assert best.evidence and best.uncertainty
    json.dumps([h.to_dict() for h in hypotheses])  # JSON-serializable


# --- acceptance comparison against the witnessed fixture -------------------------


def _hypothesis(**overrides) -> ConstructionHypothesis:
    base = dict(
        host_path="skyfall.mp3",
        guest_path="in_the_end.mp3",
        host_metrical_bpm=74.0,
        host_metrical_note="half-time reading",
        guest_metrical_bpm=105.0,
        shared_grid_bpm=74.0,
        host_ratio=1.0,
        guest_ratio=0.705,
        transformation_cost=0.295,
        pitch_shift_semitones=2,
        pitch_shift_score=0.9,
        host_anchor_sec=4.9,
        guest_anchor_sec=0.2,
        host_downbeat_confidence=0.3,
        guest_downbeat_confidence=0.3,
        entry_windows=(),
        mute_through_guest_bar=7,
        alignment_offset_bars=0,
        alignment_fit=0.8,
        rank_score=0.2,
    )
    base.update(overrides)
    return ConstructionHypothesis(**base)


def test_witness_agreement_reads_expectations_from_the_fixture_only():
    """Acceptance evidence lives in the committed fixture, not in the
    discovery rules: a hypothesis matching the witnessed values agrees on
    every comparable field; a doubled-tempo hypothesis is reported as
    differing — by comparison against fixture data, not constants."""
    construction = load_construction(FIXTURE)
    from mashpad.research.discovery import EntryWindow

    matching = _hypothesis(
        entry_windows=(
            EntryWindow(
                start_guest_bar=8, end_guest_bar=40, mean_harmonic_fit=0.8, mean_density=0.4
            ),
        )
    )
    report = witness_agreement(matching, construction)
    assert report and all(line.startswith("AGREES") for line in report)
    assert any("guest entry" in line for line in report)

    doubled = _hypothesis(host_metrical_bpm=148.0, shared_grid_bpm=148.0)
    report = witness_agreement(doubled, construction)
    assert any(line.startswith("DIFFERS") for line in report)


# --- real DSP path (optional extra) ----------------------------------------------


def _write_chord_clicks(path: Path, bpm: float, seconds: float, root_hz: float) -> None:
    """Synthesized in-test WAV (no committed audio): a sustained minor triad
    with a click accent every beat, louder on downbeats."""
    sr = 22050
    period = 60.0 / bpm
    n = int(seconds * sr)
    samples = []
    for i in range(n):
        t = i / sr
        chord = sum(
            0.15 * math.sin(2 * math.pi * f * t)
            for f in (root_hz, root_hz * 2 ** (3 / 12), root_hz * 2 ** (7 / 12))
        )
        beat_position = t / period
        nearest_beat = round(beat_position)
        click = 0.0
        if abs(beat_position - nearest_beat) * period < 0.02:
            click = 0.6 if nearest_beat % 4 == 0 else 0.3
        samples.append(max(-1.0, min(1.0, chord + click)))
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))


@pytest.mark.skipif(
    not _LIBROSA_INSTALLED, reason="librosa not installed (optional extra tempo-librosa)"
)
def test_extract_and_propose_on_synthesized_audio(tmp_path):
    """The full automatic path on real (synthesized) audio: decode both
    files, extract features, and return at least one ranked hypothesis
    with anchors, a grid, a pitch shift, and evidence — no manual pins."""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_chord_clicks(a, bpm=120.0, seconds=16.0, root_hz=220.0)
    _write_chord_clicks(b, bpm=100.0, seconds=16.0, root_hz=220.0 * 2 ** (2 / 12))
    features_a = extract_features(a)
    features_b = extract_features(b)
    assert len(features_a.beat_times) >= 8
    assert all(len(row) == 12 for row in features_a.beat_chroma)
    assert all(0.0 <= e <= 1.0 for e in features_a.beat_energy)
    hypotheses = propose_constructions(features_a, features_b, top=3)
    assert hypotheses
    top = hypotheses[0]
    assert top.shared_grid_bpm > 0
    assert top.host_anchor_sec >= 0.0
    assert top.evidence and top.uncertainty
    json.dumps(top.to_dict())


# --- structural registration search ----------------------------------------------


def test_search_alignments_surfaces_a_delayed_registration():
    """Repetitive/segmented material admits multiple registrations: when
    the guest's material only matches host content that begins 20 bars in,
    the delayed registration must be proposed and outrank the
    anchor-coincident one — no offset is privileged beyond tie-breaking."""
    a_row = _unit({0: 1.0})
    b_row = _unit({6: 1.0})  # orthogonal to a_row
    host = _features(
        "host.wav",
        120.0,
        (TempoCandidate(120.0, 0.6),),
        n_beats=160,  # 40 bars: 20 bars of A material, then 20 bars of B
        chroma_rows=tuple(a_row if i < 80 else b_row for i in range(160)),
    )
    guest = _features(
        "guest.wav",
        120.0,
        (TempoCandidate(120.0, 0.6),),
        n_beats=80,  # 20 bars, all B material
        chroma_row=b_row,
    )
    from mashpad.research.discovery import derive_bars as _derive

    host_bars = _derive(host, 4)
    guest_bars = _derive(guest, 4)
    alignments = search_alignments(host_bars, guest_bars, pitch_shift=0)
    assert isinstance(alignments[0], AlignmentCandidate)
    assert alignments[0].host_bar_offset == 20
    assert alignments[0].fit > 0.9
    by_offset = {a.host_bar_offset: a for a in alignments}
    assert all(a.fit <= alignments[0].fit for a in alignments)
    assert 0 not in by_offset or by_offset[0].fit < alignments[0].fit


def test_anchor_registration_wins_ties_and_hypotheses_carry_offsets():
    """With uniform material every registration fits equally: the
    anchor-coincident registration (offset 0) must win the tie as the
    simplest, and hypotheses must expose their registration offset."""
    host_chroma = _unit({0: 1.0, 4: 0.8, 7: 0.9})
    fast = _features("fast.wav", 148.0, (TempoCandidate(148.0, 0.6),), chroma_row=host_chroma)
    other = _features("other.wav", 105.0, (TempoCandidate(105.0, 0.6),), chroma_row=host_chroma)
    hypotheses = propose_constructions(fast, other, top=10)
    assert hypotheses[0].alignment_offset_bars == 0
    assert hypotheses[0].alignment_fit > 0.9
    offsets = {h.alignment_offset_bars for h in hypotheses}
    assert len(offsets) > 1  # alternative registrations are proposed, not hidden


def test_anchor_registration_is_always_proposed_even_when_outranked():
    """When delayed registrations fit better, the anchor-coincident
    registration must still appear among the proposals — it is the one
    registration the downbeat anchors define, and hiding it would drop
    the canonical family member instead of ranking it."""
    a_row = _unit({0: 1.0})
    b_row = _unit({6: 1.0})
    host = _features(
        "host.wav",
        120.0,
        (TempoCandidate(120.0, 0.6),),
        n_beats=160,
        chroma_rows=tuple(a_row if i < 80 else b_row for i in range(160)),
    )
    guest = _features(
        "guest.wav", 120.0, (TempoCandidate(120.0, 0.6),), n_beats=80, chroma_row=b_row
    )
    from mashpad.research.discovery import derive_bars as _derive

    alignments = search_alignments(_derive(host, 4), _derive(guest, 4), pitch_shift=0)
    offsets = [a.host_bar_offset for a in alignments]
    assert alignments[0].host_bar_offset == 20  # the delayed registration still wins
    assert 0 in offsets  # but the anchor registration is proposed alongside it


def _hyper_features(
    path: str,
    n_beats: int,
    chroma_rows: tuple[tuple[float, ...], ...] | None = None,
    chroma_row: tuple[float, ...] = _unit({0: 1.0}),
) -> TrackFeatures:
    """120 BPM features with 4-bar hypermetric accents: strongest onset
    every 16th beat (phrase downbeat), strong every 4th (bar downbeat)."""
    period = 0.5
    strengths = tuple(5.0 if i % 16 == 0 else (3.0 if i % 4 == 0 else 1.0) for i in range(n_beats))
    return TrackFeatures(
        path=path,
        duration_sec=n_beats * period,
        tracked_bpm=120.0,
        tempo_candidates=(TempoCandidate(120.0, 0.6),),
        beat_times=tuple(i * period for i in range(n_beats)),
        beat_strengths=strengths,
        beat_chroma=chroma_rows
        if chroma_rows is not None
        else tuple(chroma_row for _ in range(n_beats)),
        beat_energy=tuple(0.8 for _ in range(n_beats)),
    )


def test_off_phrase_registrations_are_not_proposed():
    """Shifting a registration by 1-3 bars breaks 4-bar phrase structure
    even where bar-level harmony matches: with the guest's material
    matching host content that begins 18 bars in (an off-phrase offset),
    the search must NOT propose 17/18/19 — it proposes the nearest
    phrase-consistent registrations instead, accepting the partial clash."""
    a_row = _unit({0: 1.0})
    b_row = _unit({6: 1.0})
    host = _hyper_features(
        "host.wav",
        192,  # 48 bars: A material through bar 18, B from bar 19 (0-based 18)
        chroma_rows=tuple(a_row if i < 72 else b_row for i in range(192)),
    )
    guest = _hyper_features("guest.wav", 80, chroma_row=b_row)  # 20 bars, all B
    from mashpad.research.discovery import derive_bars as _derive

    alignments = search_alignments(_derive(host, 4), _derive(guest, 4), pitch_shift=0)
    offsets = [a.host_bar_offset for a in alignments]
    # The raw-chroma optimum (18) and its loose-bar neighbors are excluded...
    assert not {17, 18, 19} & set(offsets)
    # ...every proposal is phrase-consistent (both sides' phrase phase is 0
    # here, so valid registrations are whole-phrase multiples)...
    assert all(o % 4 == 0 for o in offsets)
    # ...and the best proposal is the nearest phrase-aligned registration
    # past the material boundary, not the off-phrase chroma optimum.
    assert alignments[0].host_bar_offset == 20
    assert all(a.hypermetric_aligned for a in alignments)
