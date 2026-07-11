#!/usr/bin/env python3
"""Local-only harness: within-pair feature ranking report. Thin CLI shim
over `mashpad.research.evaluation` — the one sanctioned consumer of
registration-corpus labels.

    uv run scripts/ranking_report.py \
        --corpus tests/fixtures/registration_corpus_v1.json \
        --pair-id skyfall_in_the_end \
        --trajectories fixtures/local/skyfall_in_the_end.trajectories.json \
        --span fixtures/local/skyfall_in_the_end.joint_probe.json \
        --allow-hypothesis-labels
"""

import sys

from mashpad.research.evaluation import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
