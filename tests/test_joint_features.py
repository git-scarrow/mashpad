"""Pure-core tests for the joint-overlay registration probe.

All fixtures are synthetic `FrameSeries`/`BarSeries` built in-test — no
audio, no real paths, no librosa. The invariants locked here are the
redirect's ground rules: every offset is measured (none excluded, not
even off-phrase or negative ones), features come from synchronized
cross-source frame pairs, and the probe emits measurements, never
verdicts.
"""

import math

from mashpad.research.discovery import BarSeries
from mashpad.research.joint_features import (
    FrameSeries,
    RegistrationProbe,
    bar_complementarity,
    bar_correspondence,
    harmonic_roughness,
    lf_interference,
    probe_registration,
    probe_registrations,
    spectral_masking,
    synchronize,
    transient_features,
)

HOP = 0.025  # 25 ms frames, 1 s bars -> 40 frames per bar
FRAMES_PER_BAR = 40


def _unit_chroma(weights: dict[int, float]) -> tuple[float, ...]:
    row = [0.0] * 12
    for i, w in weights.items():
        row[i] = w
    norm = math.sqrt(sum(x * x for x in row))
    return tuple(x / norm for x in row) if norm else tuple(row)


def _frames(
    path: str,
    n_bars: int,
    onset: list[float] | None = None,
    rms: list[float] | None = None,
    lf: list[float] | None = None,
    bands_row: tuple[float, ...] = (1.0,) * 4,
    chroma_row: tuple[float, ...] = _unit_chroma({0: 1.0}),
    bands_rows: list[tuple[float, ...]] | None = None,
    chroma_rows: list[tuple[float, ...]] | None = None,
) -> FrameSeries:
    n = n_bars * FRAMES_PER_BAR
    return FrameSeries(
        path=path,
        hop_sec=HOP,
        onset=tuple(onset if onset is not None else [1.0] * n),
        rms=tuple(rms if rms is not None else [0.8] * n),
        lf=tuple(lf if lf is not None else [0.5] * n),
        bands=tuple(bands_rows if bands_rows is not None else [bands_row] * n),
        chroma=tuple(chroma_rows if chroma_rows is not None else [chroma_row] * n),
    )


def _bars(n_bars: int, bar_sec: float = 1.0, start: float = 0.0) -> BarSeries:
    times = tuple(start + i * bar_sec for i in range(n_bars))
    return BarSeries(
        first_downbeat_sec=times[0],
        downbeat_times=times,
        bar_chroma=tuple(_unit_chroma({0: 1.0}) for _ in times),
        bar_energy=tuple(0.8 for _ in times),
        bar_strengths=tuple(1.0 for _ in times),
        phase=0,
        phase_confidence=0.5,
    )


def _pulse_train(n_bars: int, period: int, phase: int = 0, high: float = 5.0) -> list[float]:
    return [high if (i - phase) % period == 0 else 0.1 for i in range(n_bars * FRAMES_PER_BAR)]


# --- correspondence and synchronization ---------------------------------------


def test_bar_correspondence_clips_positive_and_negative_offsets():
    host, guest = _bars(10), _bars(6)
    plus = bar_correspondence(host, guest, 7)
    assert [k[2] for k in plus] == [0, 1, 2]  # guest bars 0-2 land on host 7-9
    minus = bar_correspondence(host, guest, -2)
    assert [k[2] for k in minus] == [2, 3, 4, 5]  # guest bars 0-1 fall before host start
    assert minus[0][0] == host.downbeat_times[0]


def test_synchronize_pairs_frames_through_a_tempo_warp():
    # Guest bars are twice as long as host bars: the warp must map host
    # frame k to guest frame ~2k within the overlap.
    host_frames = _frames("h", 4)
    guest_frames = _frames("g", 8)
    host = _bars(4, bar_sec=1.0)
    guest = _bars(4, bar_sec=2.0)
    sync = synchronize(host_frames, guest_frames, bar_correspondence(host, guest, 0))
    assert sync.host_idx  # non-empty overlap
    for hi, gi in zip(sync.host_idx, sync.guest_idx, strict=True):
        assert abs(gi - 2 * hi) <= 1
    assert set(sync.bar_index) == {0, 1, 2, 3}


# --- individual features --------------------------------------------------------


def test_transient_features_reward_coincident_onsets():
    host = _frames("h", 8, onset=_pulse_train(8, 8))
    guest_hit = _frames("g", 8, onset=_pulse_train(8, 8))
    guest_miss = _frames("g", 8, onset=_pulse_train(8, 8, phase=2))
    bars = _bars(8)
    sync = synchronize(host, guest_hit, bar_correspondence(bars, bars, 0))
    corr_hit, excess_hit = transient_features(host, guest_hit, sync)
    corr_miss, excess_miss = transient_features(host, guest_miss, sync)
    assert corr_hit is not None and corr_hit > 0.9
    assert excess_hit is not None and excess_hit <= 0.0
    # Near-missing transients: lag-0 correlation collapses and a small
    # nonzero lag fits better (the flam signature).
    assert corr_miss is not None and corr_miss < corr_hit
    assert excess_miss is not None and excess_miss > 0.0


def test_lf_interference_separates_shared_from_alternating_bass():
    bars = _bars(8)
    n = 8 * FRAMES_PER_BAR
    host_lf = [1.0 if (i // FRAMES_PER_BAR) % 2 == 0 else 0.0 for i in range(n)]
    guest_same = _frames("g", 8, lf=list(host_lf))
    guest_alt = _frames("g", 8, lf=[1.0 - x for x in host_lf])
    host = _frames("h", 8, lf=host_lf)
    sync = synchronize(host, guest_same, bar_correspondence(bars, bars, 0))
    both = lf_interference(host, guest_same, sync)
    alternating = lf_interference(host, guest_alt, sync)
    assert both is not None and alternating is not None
    assert both > 0.4
    assert alternating < 0.1


def test_spectral_masking_separates_shared_from_disjoint_bands():
    bars = _bars(4)
    low = (1.0, 1.0, 0.0, 0.0)
    high = (0.0, 0.0, 1.0, 1.0)
    host = _frames("h", 4, bands_row=low)
    sync = synchronize(host, _frames("g", 4, bands_row=low), bar_correspondence(bars, bars, 0))
    same = spectral_masking(host, _frames("g", 4, bands_row=low), sync)
    disjoint = spectral_masking(host, _frames("g", 4, bands_row=high), sync)
    assert same is not None and same > 0.99
    assert disjoint is not None and disjoint < 0.01


def test_harmonic_roughness_orders_unison_fifth_semitone():
    bars = _bars(4)
    host = _frames("h", 4, chroma_row=_unit_chroma({0: 1.0}))
    sync = synchronize(host, host, bar_correspondence(bars, bars, 0))
    rough = {
        name: harmonic_roughness(
            host, _frames("g", 4, chroma_row=_unit_chroma({pc: 1.0})), sync, pitch_shift=0
        )
        for name, pc in (("unison", 0), ("fifth", 7), ("semitone", 1))
    }
    assert rough["unison"] is not None
    assert rough["unison"] < rough["fifth"] < rough["semitone"]


def test_harmonic_roughness_applies_the_registration_pitch_shift():
    bars = _bars(4)
    host = _frames("h", 4, chroma_row=_unit_chroma({2: 1.0}))
    guest = _frames("g", 4, chroma_row=_unit_chroma({0: 1.0}))
    sync = synchronize(host, guest, bar_correspondence(bars, bars, 0))
    unshifted = harmonic_roughness(host, guest, sync, pitch_shift=0)
    shifted_to_unison = harmonic_roughness(host, guest, sync, pitch_shift=2)
    assert unshifted is not None and shifted_to_unison is not None
    assert shifted_to_unison < unshifted


def test_bar_complementarity_sign_tracks_energy_patterns():
    bars = _bars(8)
    n = 8 * FRAMES_PER_BAR
    host_rms = [1.0 if (i // FRAMES_PER_BAR) % 2 == 0 else 0.2 for i in range(n)]
    host = _frames("h", 8, rms=host_rms, onset=list(host_rms))
    together = _frames("g", 8, rms=list(host_rms), onset=list(host_rms))
    apart_rms = [1.2 - x for x in host_rms]
    apart = _frames("g", 8, rms=apart_rms, onset=list(apart_rms))
    sync = synchronize(host, together, bar_correspondence(bars, bars, 0))
    e_same, d_same = bar_complementarity(host, together, sync)
    e_apart, d_apart = bar_complementarity(host, apart, sync)
    assert e_same is not None and e_same > 0.9
    assert d_same is not None and d_same > 0.9
    assert e_apart is not None and e_apart < -0.9
    assert d_apart is not None and d_apart < -0.9


# --- probe invariants (the redirect's ground rules) -----------------------------


def test_probe_measures_every_offset_none_excluded():
    """Off-phrase, negative, and phrase-aligned offsets are all measured:
    the probe must not encode any presumed phrase convention."""
    host_frames, guest_frames = _frames("h", 16), _frames("g", 8)
    host_bars, guest_bars = _bars(16), _bars(8)
    offsets = (-3, -2, -1, 0, 1, 2, 3, 5, 8)
    probes = probe_registrations(host_frames, guest_frames, host_bars, guest_bars, offsets, 0)
    assert [p.offset_bars for p in probes] == list(offsets)
    measured = [p for p in probes if p.n_sync_frames > 0]
    assert {p.offset_bars for p in measured} >= {-3, -2, -1, 0, 1, 2, 3}
    for p in measured:
        assert p.phrase_class_residue == p.offset_bars % 4  # metadata, not a filter
        assert p.harmonic_roughness is not None


def test_probe_reports_insufficient_overlap_instead_of_dropping():
    host_frames, guest_frames = _frames("h", 6), _frames("g", 6)
    probe = probe_registration(host_frames, guest_frames, _bars(6), _bars(6), 5, 0)
    assert probe.n_aligned_bars == 1
    assert probe.n_sync_frames == 0
    assert "insufficient overlap" in probe.note
    assert probe.harmonic_roughness is None


def test_probe_carries_no_verdict_fields():
    """The probe is measurement-only: no rank, score, fit, or verdict —
    gates may only come later from cross-pair evaluation."""
    fields = set(RegistrationProbe.__dataclass_fields__)
    assert not fields & {"rank", "rank_score", "fit", "verdict", "label", "compatible"}


# --- window-scoped features ----------------------------------------------------


def test_host_window_restricts_correspondence_to_audited_bars():
    """(start, bars) keeps only host bars [start, start+bars) — the same
    0-based downbeat indexing the audition renderer windows on, so probe
    features share scope with a window-judged blind label."""
    host_bars, guest_bars = _bars(30), _bars(20)
    knots = bar_correspondence(host_bars, guest_bars, 2, host_window=(8, 8))
    assert len(knots) == 8
    host_times = [k[0] for k in knots]
    assert host_times[0] == host_bars.downbeat_times[8]
    assert host_times[-1] == host_bars.downbeat_times[15]
    assert [k[2] for k in knots] == list(range(6, 14))  # guest bars = host bar - offset


def test_host_window_clips_against_guest_availability():
    """A window the guest cannot fill (negative offset near the guest
    start, or the guest ending inside the window) yields the fillable
    part — matching the renderer's silent padding, never an error."""
    host_bars, guest_bars = _bars(40), _bars(10)
    knots = bar_correspondence(host_bars, guest_bars, 25, host_window=(28, 8))
    assert [k[2] for k in knots] == list(range(3, 10))  # guest runs out at bar 9
    knots = bar_correspondence(host_bars, guest_bars, 12, host_window=(8, 8))
    assert [k[2] for k in knots] == [0, 1, 2, 3]  # guest starts inside the window


def test_window_scoped_probe_measures_only_window_content():
    """Content outside the window must not leak into the features: host
    LF energy exists only inside bars 8..16, so the windowed probe sees
    saturated LF interference while the whole-span probe averages it
    away."""
    n_bars = 30
    lf = [1.0 if 8 <= i // FRAMES_PER_BAR < 16 else 0.0 for i in range(n_bars * FRAMES_PER_BAR)]
    host_frames = _frames("h", n_bars, lf=lf)
    guest_frames = _frames("g", n_bars)
    host_bars, guest_bars = _bars(n_bars), _bars(n_bars)
    windowed = probe_registration(
        host_frames, guest_frames, host_bars, guest_bars, 0, 0, host_window=(8, 8)
    )
    whole = probe_registration(host_frames, guest_frames, host_bars, guest_bars, 0, 0)
    assert windowed.n_aligned_bars == 8
    assert whole.n_aligned_bars == n_bars
    assert windowed.lf_interference > 0.9
    assert whole.lf_interference < 0.5


def test_parse_window():
    from mashpad.research.joint_features import _parse_window

    assert _parse_window(None) is None
    assert _parse_window("") is None
    assert _parse_window("8:8") == (8, 8)
    assert _parse_window("28:8") == (28, 8)
    import pytest

    with pytest.raises(ValueError):
        _parse_window("8:0")
