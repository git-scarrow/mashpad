#!/usr/bin/env python3
"""Local-only harness: phrase-scale trajectory probe over candidate
registrations of two local recordings — every offset measured, none
excluded. Thin CLI shim over `mashpad.research.trajectories`.

    uv run --extra tempo-librosa scripts/trajectory_probe.py \
        fixtures/local/skyfall.wav fixtures/local/in_the_end.wav \
        --offsets=-3..26 --mark 0,20 \
        --json fixtures/local/skyfall_in_the_end.trajectories.json
"""

import sys

from mashpad.research.trajectories import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
