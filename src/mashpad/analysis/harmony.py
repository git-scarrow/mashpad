"""Key estimation and the small key-relation vocabulary scoring builds on.

TODO(real analysis): replace `estimate_key`'s internals with actual
chroma-based key detection (e.g. Krumhansl-Schmuckler profiles over a
chromagram). For now it returns a deterministic placeholder derived from
the track's file identity.

The parsing/distance helpers below are real, not stubbed — they encode
basic circle-of-fifths music theory and are used by
`mashpad.scoring.harmonic_score`.
"""

from __future__ import annotations

from mashpad.io.audio_file import stable_seed
from mashpad.models import Track

PITCH_CLASSES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
MODES = ["major", "minor"]

# Circle-of-fifths order, used for harmonic distance between tonics.
CIRCLE_OF_FIFTHS = ["C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#", "F"]


def parse_key(key: str) -> tuple[str, str]:
    """Split a human-readable key like "A minor" into (tonic, mode)."""
    tonic, _, mode = key.strip().partition(" ")
    mode = mode.lower() or "major"
    if tonic not in PITCH_CLASSES:
        raise ValueError(f"Unknown pitch class in key: {key!r}")
    if mode not in MODES:
        raise ValueError(f"Unknown mode in key: {key!r}")
    return tonic, mode


def format_key(tonic: str, mode: str) -> str:
    return f"{tonic} {mode}"


def fifths_distance(tonic_a: str, tonic_b: str) -> int:
    """Shortest distance between two tonics on the circle of fifths (0-6)."""
    i = CIRCLE_OF_FIFTHS.index(tonic_a)
    j = CIRCLE_OF_FIFTHS.index(tonic_b)
    diff = abs(i - j) % 12
    return min(diff, 12 - diff)


def semitone_distance(tonic_a: str, tonic_b: str) -> int:
    """Shortest chromatic distance between two tonics in semitones (0-6)."""
    i = PITCH_CLASSES.index(tonic_a)
    j = PITCH_CLASSES.index(tonic_b)
    diff = abs(i - j) % 12
    return min(diff, 12 - diff)


def semitone_shift(tonic_a: str, tonic_b: str) -> int:
    """Signed semitone shift to move tonic_b onto tonic_a, in [-6, 6]."""
    i = PITCH_CLASSES.index(tonic_a)
    j = PITCH_CLASSES.index(tonic_b)
    diff = (i - j) % 12
    return diff if diff <= 6 else diff - 12


def estimate_key(track: Track) -> str:
    seed = stable_seed(track.path)
    tonic = PITCH_CLASSES[seed % 12]
    mode = MODES[(seed // 12) % 2]
    return format_key(tonic, mode)
