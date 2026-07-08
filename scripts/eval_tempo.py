#!/usr/bin/env python3
"""Local-only harness: check a tempo backend's candidates against
user-supplied expectations.

Reads a JSON index (see tests/fixtures/audio_index.example.json for the
schema) of *local* WAV files with expected/accepted BPM values, runs a
`mashpad.analysis.tempo_backend` backend (an *estimate*, not a BPM
detector -- see that module's docstring) against each, and reports whether
any candidate lands within tolerance of an accepted value.

The backend is selectable with `--backend` (default `energy_flux`); this
is the seam a real MIR backend would plug into. Not part of the automated
test suite (it needs real local audio, which is never committed -- see
fixtures/README.md) and not wired into `mashcheck`. Run it manually:

    uv run python scripts/eval_tempo.py path/to/your_audio_index.json
    uv run python scripts/eval_tempo.py --backend autocorrelation index.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mashpad.analysis.tempo_backend import (
    DEFAULT_BACKEND_NAME,
    available_backends,
    estimate_tempo_candidates_from_wav,
)

TOLERANCE_BPM = 2.0


def _check_entry(entry: dict, backend: str) -> tuple[bool, str]:
    path = Path(entry["path"])
    if not path.exists():
        return False, f"{entry['id']}: file not found at {path}"

    accepted = entry.get("accepted_bpms") or [entry["expected_bpm"]]
    try:
        candidates = estimate_tempo_candidates_from_wav(path, backend=backend)
    except ValueError as exc:
        return False, f"{entry['id']}: {exc}"

    for candidate in candidates:
        if any(abs(candidate.bpm - target) <= TOLERANCE_BPM for target in accepted):
            return True, (
                f"{entry['id']}: OK -- candidate {candidate.bpm} BPM matched an accepted "
                f"value (confidence {candidate.confidence})"
            )

    got = ", ".join(f"{c.bpm}" for c in candidates)
    return False, (
        f"{entry['id']}: MISS -- candidates [{got}] not within {TOLERANCE_BPM} BPM of {accepted}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", help="Path to a local audio_index.json (see example schema)")
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND_NAME,
        choices=available_backends(),
        help=f"tempo backend to run (default: {DEFAULT_BACKEND_NAME})",
    )
    args = parser.parse_args(argv)

    with open(args.index) as f:
        entries = json.load(f)

    passed = 0
    for entry in entries:
        ok, message = _check_entry(entry, args.backend)
        print(message)
        passed += ok

    print(
        f"\n{passed}/{len(entries)} passed "
        f"(backend: {args.backend}, tolerance: {TOLERANCE_BPM} BPM)"
    )
    return 0 if passed == len(entries) else 1


if __name__ == "__main__":
    sys.exit(main())
