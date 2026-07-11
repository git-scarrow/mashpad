"""Pure-core tests for the stem-aware measurement path: provenance
honesty (every measurement names its stems; pseudo-stems never
masquerade as real ones) and abstention when stems are missing. No
librosa, no audio — synthetic FrameSeries stand in for stems."""

from mashpad.research.discovery import BarSeries
from mashpad.research.joint_features import FrameSeries
from mashpad.research.stems import STEM_ROLES, stem_joint_measures

HOP = 0.025
FRAMES_PER_BAR = 40


def _frames(path: str, n_bars: int, rms: float = 0.8) -> FrameSeries:
    n = n_bars * FRAMES_PER_BAR
    return FrameSeries(
        path=path,
        hop_sec=HOP,
        onset=tuple(1.0 for _ in range(n)),
        rms=tuple(rms for _ in range(n)),
        lf=tuple(0.5 for _ in range(n)),
        bands=tuple((1.0,) * 16 for _ in range(n)),
        chroma=tuple((1.0,) + (0.0,) * 11 for _ in range(n)),
    )


def _bars(n_bars: int) -> BarSeries:
    times = tuple(float(i) for i in range(n_bars))
    return BarSeries(
        first_downbeat_sec=0.0,
        downbeat_times=times,
        bar_chroma=tuple(((1.0,) + (0.0,) * 11) for _ in times),
        bar_energy=tuple(0.8 for _ in times),
        bar_strengths=tuple(1.0 for _ in times),
        phase=0,
        phase_confidence=0.5,
    )


def test_roles_vocabulary():
    assert STEM_ROLES == ("vocals", "drums", "bass", "other")


def test_measurements_name_their_stem_sources():
    host = {
        "other": _frames("h_other", 12),
        "bass": _frames("h_bass", 12),
        "drums": _frames("h_drums", 12),
        "vocals": _frames("h_voc", 12),
    }
    guest = {
        "vocals": _frames("g_voc", 12),
        "bass": _frames("g_bass", 12),
        "drums": _frames("g_drums", 12),
    }
    out = stem_joint_measures(host, guest, _bars(12), _bars(12), 0)
    assert out["vocal_masking"] is not None
    assert out["vocal_masking_source"] == "host:other x guest:vocals"
    assert out["bass_interference_source"] == "host:bass x guest:bass"
    assert out["transient_source"] == "host:drums x guest:drums"
    assert out["foreground_competition_source"] == "host:vocals x guest:vocals"


def test_pseudo_stems_are_visible_in_provenance_and_never_fake_vocals():
    host = {
        "pseudo_harmonic": _frames("h_h", 12),
        "pseudo_bass": _frames("h_b", 12),
        "pseudo_percussive": _frames("h_p", 12),
    }
    guest = {"pseudo_bass": _frames("g_b", 12), "pseudo_percussive": _frames("g_p", 12)}
    out = stem_joint_measures(host, guest, _bars(12), _bars(12), 0)
    # vocal masking abstains: no real guest vocal stem, and no pseudo fallback
    assert out["vocal_masking"] is None
    assert out["vocal_masking_source"] is None
    # bass/transients run on pseudo-stems, and say so
    assert "pseudo_bass" in out["bass_interference_source"]
    assert "pseudo_percussive" in out["transient_source"]
    assert out["foreground_competition"] is None  # needs real vocals both sides


def test_missing_everything_abstains_cleanly():
    out = stem_joint_measures({}, {}, _bars(12), _bars(12), 0)
    assert all(
        out[k] is None
        for k in (
            "vocal_masking",
            "bass_interference",
            "transient_sync_corr",
            "foreground_competition",
        )
    )


def test_insufficient_overlap_is_a_note_not_a_crash():
    host = {"bass": _frames("h_b", 4)}
    guest = {"bass": _frames("g_b", 4)}
    out = stem_joint_measures(host, guest, _bars(4), _bars(4), 100)
    assert out.get("note") == "insufficient overlap — not measured"
