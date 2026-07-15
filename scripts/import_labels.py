#!/usr/bin/env python3
"""Local-only harness: import an exported label file (e.g. an Audacity
label track) into a construction's local annotation set.

Thin CLI shim over `mashpad.research.annotations` (the importable,
unit-tested core). A label file annotates ONE recording's timeline, so
each run names a --side. Labels naming a construction event_id annotate
that event; labels naming an event kind ("downbeat", "cadence",
"phrase_onset", "section_boundary", "lyric_stress_onset") become grid
events for the alignment basin; anything else is reported unmatched.

The annotation JSON contains real timestamps of local recordings — keep
it under fixtures/local/ (gitignored) and never commit it, same policy
as audio_index.json. See fixtures/README.md. Run it manually:

    uv run scripts/import_labels.py \
        --construction tests/fixtures/construction_skyfall_in_the_end.json \
        --side host --labels fixtures/local/skyfall_labels.txt \
        --annotations fixtures/local/skyfall_in_the_end.annotations.json
"""

import sys

from mashpad.research.annotations import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
