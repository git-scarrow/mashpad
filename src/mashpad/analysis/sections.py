"""Section boundary detection.

TODO(real analysis): replace with actual structural segmentation (e.g. a
self-similarity matrix or novelty curve over a chromagram/MFCCs). For now
this returns a fixed, deterministic section layout. Confidence is kept
low-to-moderate on purpose: section detection is the shakiest of the three
stubs, and downstream phrase-fit scoring is tuned to reflect that rather
than falsely claim certainty.
"""

from __future__ import annotations

from mashpad.io.audio_file import stable_seed
from mashpad.models import Section, Track

DEFAULT_LABELS = ("intro", "verse", "chorus", "bridge", "outro")

# Relative durations for the placeholder layout, summing to 1.0.
_RELATIVE_DURATIONS = (0.12, 0.28, 0.28, 0.16, 0.16)

_BASE_CONFIDENCE = 0.55


def estimate_sections(track: Track, duration_sec: float = 180.0) -> tuple[Section, ...]:
    seed = stable_seed(track.path)
    jitter = (seed % 21 - 10) / 100  # deterministic +/-0.10 per-track jitter

    sections = []
    cursor = 0.0
    for label, rel in zip(DEFAULT_LABELS, _RELATIVE_DURATIONS, strict=True):
        length = duration_sec * rel
        confidence = max(0.05, min(0.95, _BASE_CONFIDENCE + jitter))
        sections.append(
            Section(label=label, start_sec=cursor, end_sec=cursor + length, confidence=confidence)
        )
        cursor += length

    return tuple(sections)
