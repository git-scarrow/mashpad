"""Tempo (BPM) estimation.

TODO(real analysis): replace `estimate_tempo`'s internals with actual
onset-detection / autocorrelation-based BPM estimation (e.g. via aubio or
librosa's beat tracker). For now it returns a deterministic placeholder,
derived from the track's file identity, in a musically plausible range.
"""

from __future__ import annotations

from mashpad.io.audio_file import stable_seed
from mashpad.models import TempoCandidate, Track

MIN_BPM = 80.0
MAX_BPM = 175.0


def estimate_tempo(track: Track) -> float:
    seed = stable_seed(track.path)
    span = MAX_BPM - MIN_BPM
    bpm = MIN_BPM + (seed % 1000) / 1000 * span
    return round(bpm, 1)


def estimate_tempo_candidates(track: Track) -> tuple[TempoCandidate, ...]:
    """Illustrative multiple-tempo-interpretation placeholder.

    TODO(real analysis): a real beat tracker would derive genuine
    octave-ambiguity confidences (e.g. from a particle-filter posterior
    over tempo hypotheses) rather than this fixed, deterministic split.
    This exists to prove the `TrackAnalysis.tempo_candidates` seam works
    end-to-end — it is not a real ambiguity signal, and downstream
    scoring does not currently consume it (tempo_score.py does its own
    half/double check independently, given two single BPM values).
    """
    primary = estimate_tempo(track)
    return (
        TempoCandidate(bpm=primary, confidence=0.6, multiplier_from_primary=1.0),
        TempoCandidate(bpm=round(primary * 0.5, 1), confidence=0.25, multiplier_from_primary=0.5),
        TempoCandidate(bpm=round(primary * 2.0, 1), confidence=0.15, multiplier_from_primary=2.0),
    )
