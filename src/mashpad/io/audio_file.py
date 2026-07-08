"""Audio file loading.

TODO(real analysis): replace with actual audio decoding (duration, sample
rate, channel count) via a library such as soundfile or pydub. For now
this only validates the file reference and derives a stable per-file seed
used by the analysis stubs in `mashpad.analysis`, so the same input file
always produces the same placeholder analysis.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mashpad.models import Track

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"}


def load_track(path: str | Path) -> Track:
    p = Path(path)
    if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported audio file extension: {p.suffix!r} ({p})")
    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")
    return Track(path=p)


def stable_seed(path: str | Path) -> int:
    """Deterministic integer seed derived from a file name.

    Used by analysis stubs so the same input file always produces the same
    placeholder output. Hashes the file name only (not contents), since
    the stubs don't read audio data.
    """
    digest = hashlib.sha256(Path(path).name.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
