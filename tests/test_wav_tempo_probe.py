import struct
import wave
from pathlib import Path

import pytest

from mashpad.analysis.wav_tempo_probe import estimate_tempo_candidates_from_wav

FRAME_RATE = 8000


def _write_click_track(path: Path, bpm: float, seconds: float = 6.0) -> None:
    """Synthesize a simple periodic click track at `bpm` -- generated on the
    fly, never committed, to keep this test deterministic without real audio.
    """
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


def test_estimate_tempo_candidates_from_wav_recovers_click_track_bpm(tmp_path):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=120.0)

    candidates = estimate_tempo_candidates_from_wav(wav_path)

    primary = candidates[0]
    assert primary.multiplier_from_primary == 1.0
    assert abs(primary.bpm - 120.0) <= 6.0


def test_candidates_are_ordered_primary_half_double(tmp_path):
    wav_path = tmp_path / "clicks.wav"
    _write_click_track(wav_path, bpm=100.0)

    candidates = estimate_tempo_candidates_from_wav(wav_path)

    assert [c.multiplier_from_primary for c in candidates] == [1.0, 0.5, 2.0]
    assert candidates[1].bpm == pytest.approx(candidates[0].bpm * 0.5)
    assert candidates[2].bpm == pytest.approx(candidates[0].bpm * 2.0)


def test_rejects_non_16_bit_pcm(tmp_path):
    wav_path = tmp_path / "silence.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(FRAME_RATE)
        wav_file.writeframes(bytes(FRAME_RATE))

    with pytest.raises(ValueError):
        estimate_tempo_candidates_from_wav(wav_path)


def test_rejects_too_short_audio(tmp_path):
    wav_path = tmp_path / "tiny.wav"
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FRAME_RATE)
        wav_file.writeframes(struct.pack("<4h", 0, 0, 0, 0))

    with pytest.raises(ValueError):
        estimate_tempo_candidates_from_wav(wav_path)
