import importlib.util
import struct
import wave
from pathlib import Path

import pytest

from mashpad.analysis.tempo_backend import (
    DEFAULT_BACKEND_NAME,
    TempoBackend,
    available_backends,
    estimate_tempo_candidates_from_wav,
    get_tempo_backend,
    register_backend,
)
from mashpad.models import TempoCandidate

FRAME_RATE = 8000

# The librosa backend is registered unconditionally, but librosa itself is
# an optional extra (`tempo-librosa`) imported lazily. Which librosa tests
# apply depends on whether the extra is installed in the current env.
_LIBROSA_INSTALLED = importlib.util.find_spec("librosa") is not None


def _write_click_track(path: Path, bpm: float, seconds: float = 8.0) -> None:
    """Synthesize a periodic click track at `bpm` -- generated on the fly,
    never committed, to keep this test deterministic without real audio."""
    beat_interval = 60.0 / bpm
    n_samples = int(seconds * FRAME_RATE)
    samples = [0] * n_samples
    click_len = int(0.01 * FRAME_RATE)

    t = 0.0
    while t < seconds:
        start = int(t * FRAME_RATE)
        for i in range(click_len):
            if start + i < n_samples:
                samples[start + i] = 20000
        t += beat_interval

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FRAME_RATE)
        wav_file.writeframes(struct.pack(f"<{n_samples}h", *samples))


# --- registry / interface ------------------------------------------------


def test_default_backend_is_registered_and_energy_flux():
    assert DEFAULT_BACKEND_NAME == "energy_flux"
    assert "energy_flux" in available_backends()
    assert "autocorrelation" in available_backends()


def test_registered_backends_satisfy_the_protocol():
    for name in available_backends():
        backend = get_tempo_backend(name)
        assert isinstance(backend, TempoBackend)
        assert backend.name == name


def test_get_unknown_backend_raises():
    with pytest.raises(ValueError):
        get_tempo_backend("no_such_backend")


def test_register_backend_makes_it_selectable():
    class _FakeBackend:
        name = "fake_test_backend"

        def estimate_candidates(self, path):
            return (TempoCandidate(bpm=128.0, confidence=1.0, multiplier_from_primary=1.0),)

    register_backend(_FakeBackend())
    try:
        assert "fake_test_backend" in available_backends()
        got = get_tempo_backend("fake_test_backend").estimate_candidates(Path("ignored"))
        assert got[0].bpm == 128.0
    finally:
        from mashpad.analysis import tempo_backend

        tempo_backend._BACKENDS.pop("fake_test_backend", None)


# --- both stdlib backends recover a click track --------------------------


@pytest.mark.parametrize("backend", ["autocorrelation", "energy_flux"])
def test_backend_recovers_click_track_bpm(tmp_path, backend):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=120.0)

    candidates = estimate_tempo_candidates_from_wav(wav_path, backend=backend)

    primary = candidates[0]
    assert primary.multiplier_from_primary == 1.0
    assert abs(primary.bpm - 120.0) <= 6.0


def test_default_backend_used_when_unspecified(tmp_path):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=100.0)

    default = estimate_tempo_candidates_from_wav(wav_path)
    explicit = estimate_tempo_candidates_from_wav(wav_path, backend=DEFAULT_BACKEND_NAME)

    assert default == explicit


def test_energy_flux_beats_autocorrelation_accuracy(tmp_path):
    """The improved backend's parabolic interpolation should land at least
    as close to the true tempo as the coarse-frame baseline."""
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=125.0)

    flux = estimate_tempo_candidates_from_wav(wav_path, backend="energy_flux")[0]
    auto = estimate_tempo_candidates_from_wav(wav_path, backend="autocorrelation")[0]

    assert abs(flux.bpm - 125.0) <= abs(auto.bpm - 125.0) + 1e-6
    assert abs(flux.bpm - 125.0) <= 2.0


# --- candidate structure -------------------------------------------------


def test_energy_flux_primary_is_the_fundamental_not_half_time(tmp_path):
    """Regression for the frame-quantization octave error: a fast tempo
    whose beat period isn't an integer number of frames must still be
    picked at its fundamental, not its (integer-consistent) half-time. The
    correct tempo must be the *primary*, not merely present as a companion."""
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=132.0)

    primary = estimate_tempo_candidates_from_wav(wav_path, backend="energy_flux")[0]

    assert primary.multiplier_from_primary == 1.0
    assert abs(primary.bpm - 132.0) <= 3.0


def test_energy_flux_emits_primary_and_octave_companions(tmp_path):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=100.0)

    candidates = estimate_tempo_candidates_from_wav(wav_path, backend="energy_flux")

    assert candidates[0].multiplier_from_primary == 1.0
    multipliers = {round(c.multiplier_from_primary, 3) for c in candidates}
    assert {0.5, 2.0} <= multipliers
    for candidate in candidates:
        assert 0.0 <= candidate.confidence <= 1.0


def test_autocorrelation_backend_ordering_is_primary_half_double(tmp_path):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=100.0)

    candidates = estimate_tempo_candidates_from_wav(wav_path, backend="autocorrelation")

    assert [c.multiplier_from_primary for c in candidates] == [1.0, 0.5, 2.0]
    assert candidates[1].bpm == pytest.approx(candidates[0].bpm * 0.5)
    assert candidates[2].bpm == pytest.approx(candidates[0].bpm * 2.0)


# --- input validation (shared helpers) -----------------------------------


@pytest.mark.parametrize("backend", ["autocorrelation", "energy_flux"])
def test_rejects_non_16_bit_pcm(tmp_path, backend):
    wav_path = tmp_path / "silence.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(FRAME_RATE)
        wav_file.writeframes(bytes(FRAME_RATE))

    with pytest.raises(ValueError):
        estimate_tempo_candidates_from_wav(wav_path, backend=backend)


@pytest.mark.parametrize("backend", ["autocorrelation", "energy_flux"])
def test_rejects_too_short_audio(tmp_path, backend):
    wav_path = tmp_path / "tiny.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FRAME_RATE)
        wav_file.writeframes(struct.pack("<4h", 0, 0, 0, 0))

    with pytest.raises(ValueError):
        estimate_tempo_candidates_from_wav(wav_path, backend=backend)


# --- optional librosa backend --------------------------------------------


def test_librosa_backend_is_registered_and_selectable():
    """Registered unconditionally (librosa imported lazily), so the name is
    always known regardless of whether the optional extra is installed."""
    assert "librosa" in available_backends()
    assert get_tempo_backend("librosa").name == "librosa"


def test_registering_librosa_does_not_disturb_stdlib_backends():
    assert "autocorrelation" in available_backends()
    assert "energy_flux" in available_backends()
    assert DEFAULT_BACKEND_NAME == "energy_flux"


@pytest.mark.skipif(
    _LIBROSA_INSTALLED, reason="librosa installed; missing-dependency path is not exercised"
)
def test_librosa_backend_missing_dependency_error_is_clear(tmp_path):
    """Without the optional extra, requesting the backend must raise a clear,
    actionable error naming the extra -- not a cryptic ImportError or an
    'unknown backend' that hides the cause."""
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=120.0)

    with pytest.raises(ImportError, match="tempo-librosa"):
        estimate_tempo_candidates_from_wav(wav_path, backend="librosa")


@pytest.mark.skipif(
    not _LIBROSA_INSTALLED, reason="librosa not installed (optional extra tempo-librosa)"
)
def test_librosa_backend_output_shape_matches_tempo_candidate(tmp_path):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=120.0)

    candidates = estimate_tempo_candidates_from_wav(wav_path, backend="librosa")

    assert candidates  # non-empty
    assert candidates[0].multiplier_from_primary == 1.0
    for candidate in candidates:
        assert isinstance(candidate, TempoCandidate)
        assert candidate.bpm > 0
        assert 0.0 <= candidate.confidence <= 1.0
    multipliers = {round(c.multiplier_from_primary, 3) for c in candidates}
    assert {0.5, 2.0} <= multipliers
    # Sanity: the primary should be in the neighborhood of the click tempo
    # (or a clean octave of it) -- this is an estimate, not a precise assert.
    assert min(abs(candidates[0].bpm - t) for t in (60.0, 120.0, 240.0)) <= 8.0
