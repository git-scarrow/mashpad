"""Stem separation seam.

Not implemented in this pass. Real implementation would separate a track
into components (vocals/drums/bass/other) — e.g. via a pretrained source
separation model — to support mashup candidates at the stem level rather
than full mixdown sections. Kept as an explicit interface so scoring and
candidate ranking can later operate on stems without changing their
public signatures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mashpad.models import Track


@dataclass(frozen=True, slots=True)
class StemSet:
    vocals: Any | None = None
    drums: Any | None = None
    bass: Any | None = None
    other: Any | None = None


def separate_stems(track: Track) -> StemSet:
    raise NotImplementedError("Stem separation is not implemented yet (TODO seam)")
