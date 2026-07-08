#!/usr/bin/env python3
"""Local-only harness: check the WAV tempo probe's candidates against
user-supplied expectations.

Reads a JSON index (see tests/fixtures/audio_index.example.json for the
schema) of *local* WAV files with expected/accepted BPM values, runs
`mashpad.analysis.wav_tempo_probe.estimate_tempo_candidates_from_wav`
(a toy autocorrelation probe, not a BPM detector -- see that module's
docstring) against each, and reports whether any candidate lands within
tolerance of an accepted value.

Not part of the automated test suite (it needs real local audio, which is
never committed -- see fixtures/README.md) and not wired into `mashcheck`.
Run it manually:

    uv run python scripts/eval_tempo.py path/to/your_audio_index.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mashpad.analysis.wav_tempo_probe import estimate_tempo_candidates_from_wav

TOLERANCE_BPM = 2.0


def _check_entry(entry: dict) -> tuple[bool, str]:
    path = Path(entry["path"])
    if not path.exists():
        return False, f"{entry['id']}: file not found at {path}"

    accepted = entry.get("accepted_bpms") or [entry["expected_bpm"]]
    try:
        candidates = estimate_tempo_candidates_from_wav(path)
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
    args = parser.parse_args(argv)

    with open(args.index) as f:
        entries = json.load(f)

    passed = 0
    for entry in entries:
        ok, message = _check_entry(entry)
        print(message)
        passed += ok

    print(f"\n{passed}/{len(entries)} passed (tolerance: {TOLERANCE_BPM} BPM)")
    return 0 if passed == len(entries) else 1


if __name__ == "__main__":
    sys.exit(main())
