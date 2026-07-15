#!/usr/bin/env python3
"""Local-only harness: measure joint-overlay features for every candidate
registration of two local recordings — no offset excluded.

Thin CLI shim over `mashpad.research.joint_features` (the importable,
unit-tested core). Synchronizes the guest onto the host bar grid per
registration and measures transient coincidence, low-frequency
interference, spectral-band overlap, heuristic harmonic roughness, and
bar-level energy/density complementarity from the synchronized frame
pairs. Measurements only — no verdicts, no ranking, nothing wired into
production. Audio and real local paths are never committed. Run manually:

    uv run --extra tempo-librosa scripts/probe_registration_features.py \
        fixtures/local/skyfall.wav fixtures/local/in_the_end.wav \
        --offsets -3..26 --mark 0,20 \
        --json fixtures/local/skyfall_in_the_end.joint_probe.json
"""

import sys

from mashpad.research.joint_features import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
