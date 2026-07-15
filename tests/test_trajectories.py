"""Pure-core tests for the phrase-scale trajectory probe. Synthetic
FrameSeries/BarSeries only. The point of this generation of features is
preserved temporal shape — so the tests build signals whose *order*
differs and assert the probe can tell, where span averages could not."""

import math

from mashpad.research.discovery import BarSeries
from mashpad.research.joint_features import FrameSeries
from mashpad.research.trajectories import (
    TrajectoryProbe,
    bar_correspondence,
    bar_trajectories,
    complementarity_index,
    conflict_series,
    local_correlations,
    peak_bars,
    peak_cooccurrence,
    synchronize,
    trajectory_probe,
    trajectory_probes,
)

HOP = 0.025
FRAMES_PER_BAR = 40


def _unit_chroma(weights: dict[int, float]) -> tuple[float, ...]:
    row = [0.0] * 12
    for i, w in weights.items():
        row[i] = w
    norm = math.sqrt(sum(x * x for x in row))
    return tuple(x / norm for x in row) if norm else tuple(row)


def _frames_per_bar_values(bar_values: list[float]) -> list[float]:
    return [v for v in bar_values for _ in range(FRAMES_PER_BAR)]


def _frames(
    path: str,
    n_bars: int,
    rms_by_bar: list[float] | None = None,
    onset_by_bar: list[float] | None = None,
    chroma_by_bar: list[tuple[float, ...]] | None = None,
    bands_row: tuple[float, ...] = (1.0,) * 16,
) -> FrameSeries:
    n = n_bars * FRAMES_PER_BAR
    rms = _frames_per_bar_values(rms_by_bar) if rms_by_bar else [0.8] * n
    onset = _frames_per_bar_values(onset_by_bar) if onset_by_bar else [1.0] * n
    if chroma_by_bar:
        chroma = [c for c in chroma_by_bar for _ in range(FRAMES_PER_BAR)]
    else:
        chroma = [_unit_chroma({0: 1.0})] * n
    return FrameSeries(
        path=path,
        hop_sec=HOP,
        onset=tuple(onset),
        rms=tuple(rms),
        lf=tuple(0.5 for _ in range(n)),
        bands=tuple(bands_row for _ in range(n)),
        chroma=tuple(chroma),
    )


def _bars(n_bars: int) -> BarSeries:
    times = tuple(float(i) for i in range(n_bars))
    return BarSeries(
        first_downbeat_sec=0.0,
        downbeat_times=times,
        bar_chroma=tuple(_unit_chroma({0: 1.0}) for _ in times),
        bar_energy=tuple(0.8 for _ in times),
        bar_strengths=tuple(1.0 for _ in times),
        phase=0,
        phase_confidence=0.5,
    )


def _sync(host: FrameSeries, guest: FrameSeries, n_bars: int, offset: int = 0):
    return synchronize(host, guest, bar_correspondence(_bars(n_bars), _bars(n_bars), offset))


# --- trajectories ---------------------------------------------------------------


def test_harmonic_change_and_novelty_mark_a_material_boundary():
    a, b = _unit_chroma({0: 1.0}), _unit_chroma({6: 1.0})
    chroma = [a] * 8 + [b] * 8
    frames = _frames("h", 16, chroma_by_bar=chroma)
    sync = _sync(frames, frames, 16)
    traj = bar_trajectories(frames, sync, "host")
    boundary = 8
    assert max(range(len(traj.harmonic_change)), key=lambda t: traj.harmonic_change[t]) == boundary
    assert traj.harmonic_change[3] < 1e-9  # constant material: no change
    peaks = peak_bars(traj.novelty)
    assert any(abs(p - boundary) <= 1 for p in peaks)


def test_repetition_high_inside_repeated_material_low_at_new_material():
    a, b = _unit_chroma({0: 1.0}), _unit_chroma({6: 1.0})
    chroma = [a] * 8 + [b] * 8
    traj = bar_trajectories(
        _frames("h", 16, chroma_by_bar=chroma),
        _sync(_frames("h", 16), _frames("h", 16), 16),
        "host",
    )
    # recompute on the right frames: repetition of bar 4 (same as bars 0-3) high
    frames = _frames("h", 16, chroma_by_bar=chroma)
    traj = bar_trajectories(frames, _sync(frames, frames, 16), "host")
    assert traj.repetition[4] > 0.99
    assert traj.repetition[8] < 0.01  # first bar of new material


def test_build_and_drop_track_energy_shape():
    rms = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.2, 0.2]
    frames = _frames("h", 8, rms_by_bar=rms)
    traj = bar_trajectories(frames, _sync(frames, frames, 8), "host")
    assert traj.build[2] > 0.0  # rising through the ramp
    assert traj.drop[6] > 0.4  # the break
    assert traj.drop[3] < 1e-9


def test_local_correlations_expose_a_relationship_that_flips():
    # First half: identical shape; second half: inverted. Whole-span
    # Pearson washes this out; the local minimum finds the bad stretch.
    xs = tuple([0.1, 0.9] * 8)
    ys = tuple([0.1, 0.9] * 4 + [0.9, 0.1] * 4)
    locals_ = local_correlations(xs, ys, window=4)
    assert max(locals_) > 0.9
    assert min(locals_) < -0.9


def test_complementarity_index_separates_turn_taking_from_together():
    xs = tuple([1.0, 0.0] * 8)
    assert complementarity_index(xs, tuple([0.0, 1.0] * 8)) == 1.0
    assert complementarity_index(xs, xs) == 0.0


def test_peak_cooccurrence_rewards_aligned_change_points():
    aligned = peak_cooccurrence((8, 16, 24), (8, 17, 24))
    shifted = peak_cooccurrence((8, 16, 24), (11, 19, 27))
    assert aligned is not None and shifted is not None
    assert aligned == 1.0  # ±1 bar tolerance
    assert shifted == 0.0
    assert peak_cooccurrence((), ()) is None  # nothing to co-occur is not a zero


def test_conflict_series_localizes_the_clash():
    n = 16
    host_chroma = [_unit_chroma({0: 1.0})] * n
    guest_chroma = [_unit_chroma({0: 1.0})] * 8 + [_unit_chroma({1: 1.0})] * 8
    host = _frames("h", n, chroma_by_bar=host_chroma)
    guest = _frames("g", n, chroma_by_bar=guest_chroma)
    sync = _sync(host, guest, n)
    h_traj = bar_trajectories(host, sync, "host")
    g_traj = bar_trajectories(guest, sync, "guest")
    conflicts = conflict_series(h_traj, g_traj, pitch_shift=0)
    assert max(conflicts[8:]) > 10 * max(conflicts[:8])  # clash only where the semitone is


# --- probe invariants -----------------------------------------------------------


def test_trajectory_probe_measures_every_offset_none_excluded():
    host = _frames("h", 24)
    guest = _frames("g", 12)
    offsets = (-3, -2, -1, 0, 1, 2, 3, 9)
    probes = trajectory_probes(host, guest, _bars(24), _bars(12), offsets, 0)
    assert [p.offset_bars for p in probes] == list(offsets)
    for p in probes:
        if p.n_bars >= 8:
            assert p.conflict_mean is not None
            assert set(p.curves) == {"onset_density", "rms", "midband_salience"}


def test_trajectory_probe_reports_insufficient_overlap():
    probe = trajectory_probe(_frames("h", 8), _frames("g", 8), _bars(8), _bars(8), 6, 0)
    assert probe.n_bars == 2
    assert "insufficient overlap" in probe.note
    assert probe.curves == {}


def test_trajectory_probe_carries_no_verdict_fields():
    fields = set(TrajectoryProbe.__dataclass_fields__)
    assert not fields & {"rank", "rank_score", "fit", "verdict", "label", "compatible"}


def test_flat_features_names_are_stable_for_the_ranking_eval():
    probe = trajectory_probe(_frames("h", 24), _frames("g", 12), _bars(24), _bars(12), 0, 0)
    flat = probe.flat_features()
    assert "onset_density.agreement" in flat
    assert "novelty.peak_cooccurrence" in flat
    assert "conflict_max" in flat


def test_window_scoped_trajectory_probe_covers_only_the_window():
    """With a host window the trajectory probe measures exactly the
    audited bars; without one it spans the whole overlap. An 8-bar
    audition window meets the LOCAL_WINDOW_BARS minimum exactly."""
    host_frames, guest_frames = _frames("h", 30), _frames("g", 30)
    host_bars, guest_bars = _bars(30), _bars(30)
    windowed = trajectory_probe(
        host_frames, guest_frames, host_bars, guest_bars, 0, 0, host_window=(8, 8)
    )
    whole = trajectory_probe(host_frames, guest_frames, host_bars, guest_bars, 0, 0)
    assert windowed.n_bars == 8
    assert whole.n_bars == 30
    assert windowed.note == ""  # measured, not refused
    too_small = trajectory_probe(
        host_frames, guest_frames, host_bars, guest_bars, 0, 0, host_window=(8, 4)
    )
    assert "insufficient overlap" in too_small.note
