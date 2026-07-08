"""Pluggable tempo-estimation backends behind one candidate interface.

This module is the "real backend" seam the project asked for: not a real
BPM *detector* (there is still no MIR dependency — see the CLAUDE.md
guardrail), but a real *interface* that decouples the caller
(`scripts/eval_tempo.py`) from whichever estimator is producing
`TempoCandidate`s. A backend is anything satisfying `TempoBackend`:

    def estimate_candidates(self, path: Path) -> tuple[TempoCandidate, ...]

Two stdlib-only backends ship here, plus a registry, plus one *optional*
external backend (`librosa`) that is imported lazily and only if the
caller installed it. A future backend (aubio/BeatNet/…) drops in the same
way — `register_backend(...)` from its own module, no caller change — and
`analyze_track`/`mashcheck` stay untouched (still the filename-seeded stub
in `analysis/tempo.py`) regardless of which backends are registered.

Honest labeling, per the same guardrail that renamed an earlier
`real_tempo.py` to a "probe": the stdlib backends are *estimates*, not
detection, and even the librosa backend is the *first practical external
candidate*, not a blessed production detector for this repo. The two
stdlib backends are `wave` + `struct` + `math` only, 16-bit PCM WAV only
(MP3 unsupported — no stdlib decoder); the librosa backend uses librosa's
own loader and supports whatever it can decode.

- `autocorrelation` — the original toy: a frame-RMS energy envelope
  autocorrelated over a BPM-plausible lag range, with fixed
  half/double-time companions. Preserved verbatim so its long-standing
  behavior/tests don't move.
- `energy_flux` (default) — an improved estimate: a half-wave-rectified
  log-energy *onset-strength* envelope (emphasizes transients over
  sustained loudness), autocorrelated with a log-Gaussian perceptual
  tempo prior (centered ~120 BPM) to fight octave error, and parabolic
  peak interpolation for sub-frame BPM resolution. Its half/double
  companions carry *measured* correlation strength at those lags rather
  than a flat guess. Still an estimate — expect it to struggle on weak or
  syncopated pulses, like any envelope autocorrelator.
- `librosa` — optional, external (`pip`/`uv` extra `tempo-librosa`; not a
  core dependency). Wraps `librosa.beat.beat_track` for the primary tempo
  and derives an honest per-frame agreement confidence from
  `librosa.feature.tempo`. Imported lazily: requesting it without the
  extra raises a clear, actionable `ImportError`, and its absence never
  affects the stdlib backends. Tempo-candidate extraction only — no
  chroma/key/section/beat-grid use.

None of these is wired into `analyze_track`/`mashcheck`; all are reachable
only via `scripts/eval_tempo.py` against user-supplied local audio.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Protocol, runtime_checkable

from mashpad.models import TempoCandidate

MIN_BPM = 60.0
MAX_BPM = 200.0

# Log-Gaussian perceptual tempo prior (Ellis 2007, "Beat Tracking by
# Dynamic Programming"): weight tempo hypotheses by proximity, in octaves,
# to a central preferred tempo. Used only to pick which autocorrelation
# peak is the *primary* interpretation, so a strong double-time pulse
# doesn't win over the tempo a listener would tap. Confidence numbers stay
# tied to the raw (unweighted) correlation.
PERCEPTUAL_BPM0 = 120.0
PERCEPTUAL_SIGMA_OCTAVES = 1.4


@runtime_checkable
class TempoBackend(Protocol):
    """A source of ranked tempo interpretations for a local audio file.

    The single seam every estimator implements. `estimate_candidates`
    returns a non-empty, primary-first tuple of `TempoCandidate`
    (`multiplier_from_primary == 1.0` for the primary). A real MIR backend
    plugs in by implementing this and calling `register_backend` — nothing
    that consumes candidates needs to change.
    """

    name: str

    def estimate_candidates(self, path: Path) -> tuple[TempoCandidate, ...]: ...


# --- shared stdlib WAV helpers ------------------------------------------


def _read_mono_samples(path: Path) -> tuple[list[float], int]:
    with wave.open(str(path), "rb") as wav_file:
        n_channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        n_frames = wav_file.getnframes()
        raw = wav_file.readframes(n_frames)

    if sample_width != 2:
        raise ValueError("tempo backends only support 16-bit PCM WAV files")

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


def _lag_bounds(n: int, frame_hz: float) -> tuple[int, int]:
    min_lag = max(1, int(frame_hz * 60.0 / MAX_BPM))
    max_lag = min(n - 1, int(frame_hz * 60.0 / MIN_BPM))
    if min_lag > max_lag:
        raise ValueError("audio is too short to estimate tempo in the supported BPM range")
    return min_lag, max_lag


def _perceptual_weight(bpm: float) -> float:
    octaves = math.log2(bpm / PERCEPTUAL_BPM0)
    return math.exp(-0.5 * (octaves / PERCEPTUAL_SIGMA_OCTAVES) ** 2)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


# --- backend: autocorrelation (original toy, preserved) -----------------


class AutocorrelationWavBackend:
    """Frame-RMS envelope autocorrelated over a BPM-plausible lag range.

    The original `wav_tempo_probe` algorithm, unchanged, kept as a
    reference/baseline backend. Emits the strongest-peak BPM as primary
    plus fixed half/double-time companions at a flat 0.4x confidence.
    """

    name = "autocorrelation"
    frame_ms = 50.0

    def estimate_candidates(self, path: Path) -> tuple[TempoCandidate, ...]:
        samples, frame_rate = _read_mono_samples(path)
        envelope = _energy_envelope(samples, frame_rate, self.frame_ms)
        bpm, confidence = self._autocorrelation_bpm(envelope)
        return (
            TempoCandidate(bpm=bpm, confidence=confidence, multiplier_from_primary=1.0),
            TempoCandidate(
                bpm=round(bpm * 0.5, 1), confidence=confidence * 0.4, multiplier_from_primary=0.5
            ),
            TempoCandidate(
                bpm=round(bpm * 2.0, 1), confidence=confidence * 0.4, multiplier_from_primary=2.0
            ),
        )

    def _autocorrelation_bpm(self, envelope: list[float]) -> tuple[float, float]:
        if len(envelope) < 4:
            raise ValueError("audio is too short to estimate tempo")

        mean = sum(envelope) / len(envelope)
        centered = [v - mean for v in envelope]
        energy = sum(v * v for v in centered) or 1.0

        frame_hz = 1000.0 / self.frame_ms
        min_lag, max_lag = _lag_bounds(len(centered), frame_hz)

        best_lag, best_corr = min_lag, -1.0
        for lag in range(min_lag, max_lag + 1):
            corr = sum(centered[i] * centered[i + lag] for i in range(len(centered) - lag))
            corr /= energy
            if corr > best_corr:
                best_corr, best_lag = corr, lag

        bpm = 60.0 * frame_hz / best_lag
        return round(bpm, 1), round(_clamp01(best_corr), 3)


# --- backend: energy_flux (improved default) ----------------------------


class EnergyFluxWavBackend:
    """Onset-strength autocorrelation with a perceptual tempo prior.

    Improvements over the plain autocorrelation backend, all stdlib:
    - **Onset strength**, not raw loudness: a half-wave-rectified
      first difference of the log-energy envelope, so sustained energy is
      suppressed and transients (beats) drive the signal.
    - **Perceptual prior** on peak selection (`_perceptual_weight`) to
      resist octave error when choosing the primary tempo.
    - **Triangular lag smoothing** (`_smooth`) before peak-picking, so a
      beat period that falls between two integer frame-lags isn't split
      into two half-strength peaks and beaten by its integer-consistent
      2x-period lag (a frame-quantization octave error).
    - **Parabolic interpolation** around the winning lag for sub-frame
      BPM resolution (a finer 20 ms frame alone would be coarse).
    - **Measured** half/double companions: their confidence is the actual
      correlation at those lags, not a flat fraction of the primary's.

    Still an estimate: envelope autocorrelation with no spectral or
    machine-learned onset model. Weak/syncopated pulses will still fool it.
    """

    name = "energy_flux"
    frame_ms = 20.0

    def estimate_candidates(self, path: Path) -> tuple[TempoCandidate, ...]:
        samples, frame_rate = _read_mono_samples(path)
        envelope = _energy_envelope(samples, frame_rate, self.frame_ms)
        onset = self._onset_strength(envelope)
        if len(onset) < 4:
            raise ValueError("audio is too short to estimate tempo")

        frame_hz = 1000.0 / self.frame_ms
        min_lag, max_lag = _lag_bounds(len(onset), frame_hz)
        raw = self._autocorrelation(onset, min_lag, max_lag)
        # Triangular smoothing across adjacent lags before peak-picking. A
        # beat period that isn't an integer number of frames (e.g. 23.4)
        # splits its autocorrelation energy between lags 23 and 24, so each
        # single-lag peak reads ~half strength while the 2x-period lag
        # stays integer-consistent and spuriously wins -- a frame-
        # quantization octave error. Recombining neighbors restores the
        # fundamental. `_parabolic_peak` then recovers the sub-frame period.
        corr = self._smooth(raw, min_lag, max_lag)

        # Primary: the smoothed peak most favored by the perceptual prior.
        primary_lag = max(
            corr, key=lambda lag: corr[lag] * _perceptual_weight(60.0 * frame_hz / lag)
        )
        refined_lag = self._parabolic_peak(corr, primary_lag, min_lag, max_lag)
        primary_bpm = 60.0 * frame_hz / refined_lag
        primary_conf = _clamp01(corr[primary_lag])

        candidates = [
            TempoCandidate(
                bpm=round(primary_bpm, 1),
                confidence=round(primary_conf, 3),
                multiplier_from_primary=1.0,
            )
        ]

        # Half- and double-time companions, with confidence measured at
        # the corresponding lag when it falls in range (else a small floor
        # so downstream octave logic still sees the interpretation).
        for multiplier in (0.5, 2.0):
            companion_bpm = primary_bpm * multiplier
            companion_lag = round(60.0 * frame_hz / companion_bpm)
            if min_lag <= companion_lag <= max_lag:
                companion_conf = _clamp01(corr[companion_lag])
            else:
                companion_conf = 0.05
            candidates.append(
                TempoCandidate(
                    bpm=round(companion_bpm, 1),
                    confidence=round(companion_conf, 3),
                    multiplier_from_primary=multiplier,
                )
            )

        primary, *companions = candidates
        companions.sort(key=lambda c: c.confidence, reverse=True)
        return (primary, *companions)

    @staticmethod
    def _onset_strength(envelope: list[float]) -> list[float]:
        log_energy = [math.log(1e-9 + max(0.0, v)) for v in envelope]
        return [max(0.0, log_energy[i] - log_energy[i - 1]) for i in range(1, len(log_energy))]

    @staticmethod
    def _smooth(corr: dict[int, float], min_lag: int, max_lag: int) -> dict[int, float]:
        """Triangular (0.5, 1, 0.5) smoothing, normalized to stay on the
        same scale as `corr` so confidence numbers remain comparable."""
        smoothed = {}
        for lag in range(min_lag, max_lag + 1):
            total = weight = 0.0
            for offset, w in ((-1, 0.5), (0, 1.0), (1, 0.5)):
                if min_lag <= lag + offset <= max_lag:
                    total += w * corr[lag + offset]
                    weight += w
            smoothed[lag] = total / weight if weight else corr[lag]
        return smoothed

    @staticmethod
    def _autocorrelation(signal: list[float], min_lag: int, max_lag: int) -> dict[int, float]:
        n = len(signal)
        mean = sum(signal) / n
        centered = [v - mean for v in signal]
        energy = sum(v * v for v in centered) or 1.0
        return {
            lag: sum(centered[i] * centered[i + lag] for i in range(n - lag)) / energy
            for lag in range(min_lag, max_lag + 1)
        }

    @staticmethod
    def _parabolic_peak(corr: dict[int, float], lag: int, min_lag: int, max_lag: int) -> float:
        if lag <= min_lag or lag >= max_lag:
            return float(lag)
        y0, y1, y2 = corr[lag - 1], corr[lag], corr[lag + 1]
        denom = y0 - 2.0 * y1 + y2
        if denom == 0.0:
            return float(lag)
        offset = 0.5 * (y0 - y2) / denom
        # A well-formed peak has |offset| < 1; clamp to guard flat/noisy cases.
        return lag + max(-1.0, min(1.0, offset))


# --- backend: librosa (optional, external) ------------------------------

_LIBROSA_INSTALL_HINT = (
    "the 'librosa' tempo backend requires the optional 'tempo-librosa' "
    "dependency; install it with `uv sync --extra tempo-librosa` "
    "(or `pip install 'mashpad[tempo-librosa]'`)"
)


class LibrosaTempoBackend:
    """Optional external backend wrapping librosa's beat tracker.

    The first *practical* external tempo backend candidate — a real MIR
    library rather than a stdlib toy — but deliberately not treated as a
    blessed production detector here: librosa is an optional extra
    (`tempo-librosa`), never a core dependency, and this backend is never
    wired into `analyze_track`/`mashcheck`. Tempo-candidate extraction
    only; no chroma/key/section/beat-grid use.

    librosa is imported lazily inside `estimate_candidates`, so importing
    this module (hence the whole deterministic stub pipeline) never needs
    librosa installed. Requesting this backend without the extra raises a
    clear, actionable `ImportError` instead of a cryptic failure, and its
    absence never affects the stdlib backends.
    """

    name = "librosa"

    def estimate_candidates(self, path: Path) -> tuple[TempoCandidate, ...]:
        try:
            import librosa
            import numpy as np
        except ImportError as exc:
            raise ImportError(_LIBROSA_INSTALL_HINT) from exc

        y, sr = librosa.load(str(path), sr=None, mono=True)
        if y.size < sr:  # shorter than ~1s: no trustworthy tempo
            raise ValueError("audio is too short to estimate tempo")

        primary_bpm = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
        if not math.isfinite(primary_bpm) or primary_bpm <= 0:
            raise ValueError("librosa could not estimate a tempo for this audio")

        # Honest, data-derived confidence: the fraction of per-frame tempo
        # estimates that agree with a given interpretation. Not a
        # calibrated probability — just how self-consistent librosa's own
        # frame-level tempo track is around each candidate.
        per_frame = np.atleast_1d(librosa.feature.tempo(y=y, sr=sr, aggregate=None))

        def agreement(target_bpm: float) -> float:
            if target_bpm <= 0:
                return 0.0
            within = np.abs(per_frame - target_bpm) <= 0.04 * target_bpm
            return _clamp01(float(np.mean(within)))

        primary = TempoCandidate(
            bpm=round(primary_bpm, 1),
            confidence=round(agreement(primary_bpm), 3),
            multiplier_from_primary=1.0,
        )
        companions = [
            TempoCandidate(
                bpm=round(primary_bpm * multiplier, 1),
                confidence=round(agreement(primary_bpm * multiplier), 3),
                multiplier_from_primary=multiplier,
            )
            for multiplier in (0.5, 2.0)
        ]
        companions.sort(key=lambda c: c.confidence, reverse=True)
        return (primary, *companions)


# --- registry -----------------------------------------------------------

_BACKENDS: dict[str, TempoBackend] = {}
DEFAULT_BACKEND_NAME = "energy_flux"


def register_backend(backend: TempoBackend) -> None:
    """Register a tempo backend under its `name`.

    The extension point for a future real MIR backend: import-time
    `register_backend(MyAubioBackend())` makes it selectable by name from
    `scripts/eval_tempo.py` with no other change here.
    """
    _BACKENDS[backend.name] = backend


def available_backends() -> tuple[str, ...]:
    return tuple(sorted(_BACKENDS))


def get_tempo_backend(name: str | None = None) -> TempoBackend:
    resolved = name or DEFAULT_BACKEND_NAME
    try:
        return _BACKENDS[resolved]
    except KeyError:
        raise ValueError(
            f"unknown tempo backend {resolved!r}; available: {', '.join(available_backends())}"
        ) from None


def estimate_tempo_candidates_from_wav(
    path: Path, *, backend: str | None = None
) -> tuple[TempoCandidate, ...]:
    """Estimate tempo candidates for a local WAV via the selected backend.

    Defaults to `energy_flux`. An estimate, not detection — see module
    docstring. Not wired into `analyze_track`/`mashcheck`.
    """
    return get_tempo_backend(backend).estimate_candidates(Path(path))


register_backend(AutocorrelationWavBackend())
register_backend(EnergyFluxWavBackend())
# Registered unconditionally (librosa imported lazily on use) so the name
# is always selectable and a missing extra yields a clear error, not an
# "unknown backend" that hides the real cause.
register_backend(LibrosaTempoBackend())
