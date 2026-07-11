#!/usr/bin/env python3
"""Local-only harness: experimental stem-aware joint measurements. Thin
CLI shim over `mashpad.research.stems`. Research instrumentation only —
never a production dependency or gate. External stems are user-provided
files (separated outside this repo); --pseudo adds crude librosa HPSS
pseudo-stems (which never include vocals).

    uv run --extra tempo-librosa scripts/stem_probe.py \
        fixtures/local/skyfall.wav fixtures/local/in_the_end.wav \
        --pseudo --offsets=-3..26 \
        --json fixtures/local/skyfall_in_the_end.stem_probe.json
"""

import sys

from mashpad.research.stems import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
