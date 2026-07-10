#!/usr/bin/env python3
"""Local-only harness: propose mashup construction hypotheses for two
local audio files — automatic discovery, no manual pins.

Thin CLI shim over `mashpad.research.discovery` (the importable,
unit-tested core). Decodes both recordings (librosa, optional
tempo-librosa extra), generates tempo-octave interpretations, estimates
beat grids and first stable downbeats, ranks common-tempo candidates
with role-asymmetric transformation cost, picks a pitch shift by chroma
rotation, and emits ranked hypotheses with entry/mute windows, evidence,
and uncertainty. Nothing here writes provenance or touches production
scoring. Audio and real local paths are never committed. Run manually:

    uv run --extra tempo-librosa scripts/propose_construction.py \
        fixtures/local/skyfall.mp3 fixtures/local/in_the_end.mp3 \
        --witness tests/fixtures/construction_skyfall_in_the_end.json \
        --json fixtures/local/skyfall_in_the_end.hypotheses.json
"""

import sys

from mashpad.research.discovery import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
