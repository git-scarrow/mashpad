#!/usr/bin/env python3
"""Local-only harness: blinded registration audition workflow. Thin CLI
shim over `mashpad.research.audition`.

Render a session (clips are copyrighted derived audio — keep the output
under gitignored fixtures/local/, never commit it):

    uv run --extra tempo-librosa scripts/audition_registrations.py render \
        fixtures/local/skyfall.wav fixtures/local/in_the_end.wav \
        --session anchor_neighborhood --offsets=-3..3 \
        --window-start-bar 8 --window-bars 8 --seed 41 \
        --out fixtures/local/auditions

Listen blind (do NOT open key.json), fill responses.json, then:

    uv run --extra tempo-librosa scripts/audition_registrations.py unseal \
        fixtures/local/auditions/anchor_neighborhood \
        --labels-out fixtures/local/auditions/anchor_neighborhood/labels.json
"""

import sys

from mashpad.research.audition import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
