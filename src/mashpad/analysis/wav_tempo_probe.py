"""A WAV-only tempo *probe* for exercising the TempoCandidate harness --
not a BPM detector, and not a component of `mashcheck`'s analysis pipeline.

Deliberately isolated from `mashpad.cli` / `mashpad.analysis.analyze_track`:
`mashcheck` still uses the deterministic filename-seeded stub in
`analysis/tempo.py`, unconditionally, for every track. This module exists
only for `scripts/eval_tempo.py`, a local-only harness that checks whether
the `TempoCandidate` model produces plausible interpretations when pointed
at real, user-supplied audio -- without adding an MIR dependency
(librosa/aubio/Demucs/BeatNet etc. are still out of scope; see the project
CLAUDE.md guardrails).

The estimate itself is stdlib-only (`wave` + `struct`): a frame-level RMS
energy envelope, autocorrelated over a BPM-plausible lag range. This is a
toy beat tracker -- it exists to prove the candidate/fallback/relation
plumbing works against a real waveform, not to produce trustworthy BPM
numbers. Expect it to be wrong on anything with a weak or syncopated pulse
(most real music). Do not treat its output as ground truth, and do not
promote it into the default analysis pipeline without discussing a real
MIR dependency first. 16-bit PCM WAV only; MP3 is not supported (no
stdlib decoder) -- convert to WAV first.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from mashpad.models import TempoCandidate

MIN_BPM = 60.0
MAX_BPM = 200.0
FRAME_MS = 50.0  # envelope frame size


def _read_mono_samples(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wav_file:
        n_channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        n_frames = wav_file.getnframes()
        raw = wav_file.readframes(n_frames)

    if sample_width != 2:
        raise ValueError("wav_tempo_probe only supports 16-bit PCM WAV files")

    total_samples = len(raw) // 2
    values = struct.unpack(f"<{total_samples}h", raw[: total_samples * 2])

    if n_channels == 1:
        mono = list(values)
    else:
        mono = [
            sum(values[i : i + n_channels]) / n_channels
            for i in range(0, len(values) - n_channels + 1, n_channels)
        ]
    return mono, frame_rate


def _energy_envelope(samples: list[float], frame_rate: int, frame_ms: float) -> list[float]:
    frame_size = max(1, int(frame_rate * frame_ms / 1000))
    envelope = []
    for start in range(0, len(samples), frame_size):
        chunk = samples[start : start + frame_size]
        if not chunk:
            continue
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
        envelope.append(rms)
    return envelope


def _autocorrelation_bpm(envelope: list[float], frame_ms: float) -> tuple[float, float]:
    """Return `(bpm, confidence)` from the strongest autocorrelation peak."""
    if len(envelope) < 4:
        raise ValueError("audio is too short to estimate tempo")

    mean = sum(envelope) / len(envelope)
    centered = [v - mean for v in envelope]
    energy = sum(v * v for v in centered) or 1.0

    frame_hz = 1000.0 / frame_ms
    min_lag = max(1, int(frame_hz * 60.0 / MAX_BPM))
    max_lag = min(len(centered) - 1, int(frame_hz * 60.0 / MIN_BPM))

    if min_lag > max_lag:
        raise ValueError("audio is too short to estimate tempo in the supported BPM range")

    best_lag, best_corr = None, -1.0
    for lag in range(min_lag, max_lag + 1):
        corr = sum(centered[i] * centered[i + lag] for i in range(len(centered) - lag))
        corr /= energy
        if corr > best_corr:
            best_corr, best_lag = corr, lag

    bpm = 60.0 * frame_hz / best_lag
    confidence = max(0.0, min(1.0, best_corr))
    return round(bpm, 1), round(confidence, 3)


def estimate_tempo_candidates_from_wav(path: Path) -> tuple[TempoCandidate, ...]:
    """Probe a local 16-bit PCM WAV file for a tempo-candidate triple.

    A toy estimate, not a detector -- see module docstring. Not wired into
    `analyze_track`/`mashcheck`.
    """
    samples, frame_rate = _read_mono_samples(path)
    envelope = _energy_envelope(samples, frame_rate, FRAME_MS)
    bpm, confidence = _autocorrelation_bpm(envelope, FRAME_MS)

    return (
        TempoCandidate(bpm=bpm, confidence=confidence, multiplier_from_primary=1.0),
        TempoCandidate(
            bpm=round(bpm * 0.5, 1), confidence=confidence * 0.4, multiplier_from_primary=0.5
        ),
        TempoCandidate(
            bpm=round(bpm * 2.0, 1), confidence=confidence * 0.4, multiplier_from_primary=2.0
        ),
    )
