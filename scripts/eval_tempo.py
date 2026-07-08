#!/usr/bin/env python3
"""Local-only harness: evaluate a tempo backend against a private index of
user-supplied audio fixtures.

Thin CLI shim over `mashpad.tempo_eval` (the importable, unit-tested
core). Reads a JSON index (schema: tests/fixtures/audio_index.example.json,
guide: docs/tempo-eval.md) of *local* audio files with expected/accepted
BPM interpretations, runs one `mashpad.analysis.tempo_backend` backend
against each, and reports per fixture whether an accepted interpretation
was found, whether it was direct / half-time / double-time, the percent
error, and whether the backend's confidence was misleading — plus a
summary with pass rate, failures by category, and suspicious
high-confidence misses.

Missing local files are skipped (never fail the run); audio and real local
paths are never committed — see fixtures/README.md. Not part of the
automated test suite and not wired into `mashcheck`. Run it manually:

    uv run scripts/eval_tempo.py --backend energy_flux --index path/to/local_audio_index.json
    uv run scripts/eval_tempo.py --backend autocorrelation path/to/local_audio_index.json
    uv run --extra tempo-librosa scripts/eval_tempo.py --backend librosa --index index.json
    uv run scripts/eval_tempo.py --index index.json --json results_energy_flux.json
"""

import sys

from mashpad.tempo_eval import main

if __name__ == "__main__":
    sys.exit(main())
