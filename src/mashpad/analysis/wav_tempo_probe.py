"""Deprecated shim — the toy WAV probe now lives behind a backend interface.

This module's algorithm (frame-RMS envelope autocorrelation) was promoted
into `mashpad.analysis.tempo_backend` as the `autocorrelation` backend,
one implementation behind the `TempoBackend` interface. A better stdlib
default (`energy_flux`) ships alongside it, and a real MIR backend can
register there later without touching callers.

Kept only so existing imports of `estimate_tempo_candidates_from_wav` (and
`tests/test_wav_tempo_probe.py`) keep working; it forwards to the
`autocorrelation` backend to preserve the exact original behavior. New
code should call `mashpad.analysis.tempo_backend` directly. Still an
estimate, not a BPM detector; 16-bit PCM WAV only.
"""

from __future__ import annotations

from pathlib import Path

from mashpad.analysis.tempo_backend import (
    MAX_BPM,
    MIN_BPM,
)
from mashpad.analysis.tempo_backend import (
    estimate_tempo_candidates_from_wav as _estimate_via_backend,
)
from mashpad.models import TempoCandidate

__all__ = ["MIN_BPM", "MAX_BPM", "estimate_tempo_candidates_from_wav"]


def estimate_tempo_candidates_from_wav(path: Path) -> tuple[TempoCandidate, ...]:
    """Probe a local 16-bit PCM WAV via the `autocorrelation` backend.

    Deprecated: prefer `mashpad.analysis.tempo_backend`. Forwards to the
    original toy algorithm to preserve behavior for existing callers.
    """
    return _estimate_via_backend(path, backend="autocorrelation")
