"""Track analysis orchestration.

Combines the individual (currently stubbed) tempo, key, and section
estimators into one TrackAnalysis. This is the seam real analysis plugs
into later — callers here and in `mashpad.cli` should not need to change
when the stub estimators are replaced with real DSP.
"""

from __future__ import annotations

from mashpad.analysis.harmony import estimate_key
from mashpad.analysis.sections import estimate_sections
from mashpad.analysis.tempo import estimate_tempo, estimate_tempo_candidates
from mashpad.models import Track, TrackAnalysis


def analyze_track(track: Track) -> TrackAnalysis:
    bpm = estimate_tempo(track)
    key = estimate_key(track)
    sections = estimate_sections(track)
    tempo_candidates = estimate_tempo_candidates(track)
    return TrackAnalysis(
        track=track, bpm=bpm, key=key, sections=sections, tempo_candidates=tempo_candidates
    )
