"""Command-line entry point: mashcheck.

`build_report` is kept separate from `run`/`main` on purpose: it takes
already-built TrackAnalysis objects and does no filesystem or analysis
I/O, so tests can drive the scoring + reporting pipeline directly with
TrackAnalysis objects built from JSON fixtures (see tests/fixtures/).
"""

from __future__ import annotations

import argparse
import sys

from mashpad.analysis import analyze_track
from mashpad.io.audio_file import load_track
from mashpad.models import MashupMoveType, TrackAnalysis, TrackRole
from mashpad.report.text_report import render_report
from mashpad.scoring import evaluate_move
from mashpad.scoring.candidate_score import rank_candidates
from mashpad.scoring.verdict import assess_compatibility


def build_report(
    analysis_a: TrackAnalysis,
    analysis_b: TrackAnalysis,
    top_n: int = 3,
    *,
    move_type: MashupMoveType = MashupMoveType.VOCAL_OVER_INSTRUMENTAL_OVERLAY,
    track_a_role: TrackRole = TrackRole.VOCAL,
    track_b_role: TrackRole = TrackRole.INSTRUMENTAL,
) -> str:
    profile = evaluate_move(
        analysis_a,
        analysis_b,
        move_type=move_type,
        track_a_role=track_a_role,
        track_b_role=track_b_role,
    )
    verdict = assess_compatibility(profile, analysis_a, analysis_b)
    candidates = (
        rank_candidates(list(analysis_a.sections), list(analysis_b.sections), profile.scores, top_n)
        if profile.scores is not None
        else []
    )
    return render_report(analysis_a, analysis_b, profile, verdict, candidates)


def run(song_a: str, song_b: str) -> str:
    analysis_a = analyze_track(load_track(song_a))
    analysis_b = analyze_track(load_track(song_b))
    return build_report(analysis_a, analysis_b)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mashcheck",
        description="Check whether two local songs are plausible mashup candidates.",
    )
    parser.add_argument("song_a", help="Path to the first audio file")
    parser.add_argument("song_b", help="Path to the second audio file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        print(run(args.song_a, args.song_b))
    except (FileNotFoundError, ValueError) as exc:
        print(f"mashcheck: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
