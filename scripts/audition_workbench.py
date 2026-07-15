#!/usr/bin/env python3
"""Local-only harness: blinded-audition workbench web UI. Thin CLI shim
over `mashpad.research.workbench`. Stdlib http.server only — no
accounts, no auth, no cloud, no production deployment. key.json stays
sealed; nothing in the UI or API reveals offsets before finalization.

    uv run scripts/audition_workbench.py \
        fixtures/local/auditions/anchor_neighborhood \
        fixtures/local/auditions/delayed_neighborhood \
        --lan --port 8765 \
        --trajectories fixtures/local/skyfall_in_the_end.trajectories.json \
        --span fixtures/local/skyfall_in_the_end.joint_probe.json
"""

import sys

from mashpad.research.workbench import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
