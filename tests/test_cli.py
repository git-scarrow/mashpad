import json
from pathlib import Path

import pytest

from mashpad.cli import build_report, main
from mashpad.models import MashupMoveType, TrackAnalysis, TrackRole

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_REPORT = """\
Song A:
  BPM: 122.4  [stub estimate — seeded from file name, not audio]
  Key: A minor  [stub estimate — seeded from file name, not audio]
  Sections: intro, verse, chorus, bridge, outro  [stub estimate — seeded from file name, not audio]
Song B:
  BPM: 124.1  [stub estimate — seeded from file name, not audio]
  Key: C major  [stub estimate — seeded from file name, not audio]
  Sections: intro, verse, chorus, bridge, outro  [stub estimate — seeded from file name, not audio]
Assumed move: vocal_over_instrumental_overlay (Song A = vocal, Song B = instrumental) [supported]

Musical judgment
  Verdict: MAYBE — Plausible, but not confirmed — analysis is stubbed, not measured.
  Evidence for this call:
    - move_support: vocal_over_instrumental_overlay is a v0-supported move.
    - tempo: Tempo aligns directly at ~122.4 BPM (1.4% deviation).
    - harmonic: Keys relate as relative major/minor (harmonically workable).
  Missing / ambiguous / conditional evidence:
    - role: Vocal/instrumental roles are caller-asserted, not verified (no stem separation in v0).
    - provenance: BPM/key/section values are deterministic stubs (seeded from the file name), \
not real-audio measurements — enough to sketch a hypothesis, not to confirm or rule out \
compatibility.
    - phrase: Section-boundary confidence is too low (tentative) to support a phrase-level \
pairing suggestion.

Analysis evidence (backend components — inputs to the judgment, not the verdict)
  Tempo fit: strong
  Tempo interpretation: [fallback: no tempo_candidates on one or both tracks, using nominal \
BPM only] Selected 122.4 BPM vs 124.1 BPM (relation=direct)
  Harmonic fit: strong
  Phrase fit: tentative
  Composite component score: 0.8177 (strong)  [not the verdict]
Suggested adjustments:
  Stretch B to 122.4 BPM
  No pitch shift required
Best candidates:
  1. A verse over B chorus
  2. A verse over B bridge
  3. A chorus over B verse"""


def _load_fixture(name: str) -> TrackAnalysis:
    with open(FIXTURES / name) as f:
        return TrackAnalysis.from_dict(json.load(f))


def test_build_report_matches_expected_shape_from_json_fixtures():
    analysis_a = _load_fixture("track_a.json")
    analysis_b = _load_fixture("track_b.json")
    assert build_report(analysis_a, analysis_b) == EXPECTED_REPORT


def test_build_report_honors_explicit_move_type_and_roles():
    analysis_a = _load_fixture("track_a.json")
    analysis_b = _load_fixture("track_b.json")

    report = build_report(
        analysis_a,
        analysis_b,
        move_type=MashupMoveType.SAMPLE_COLLAGE,
        track_a_role=TrackRole.VOCAL,
        track_b_role=TrackRole.INSTRUMENTAL,
    )

    assert "Assumed move: sample_collage" in report
    assert "[out_of_scope]" in report
    assert "Not scored" in report
    # Out-of-scope is an explicit abstention, not a fabricated score.
    assert "Verdict: UNCERTAIN" in report


def test_cli_prints_report_for_dummy_audio_files(tmp_path, capsys):
    song_a = tmp_path / "a.mp3"
    song_b = tmp_path / "b.mp3"
    song_a.touch()
    song_b.touch()

    exit_code = main([str(song_a), str(song_b)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Song A:" in captured.out
    assert "Song B:" in captured.out
    assert "Musical judgment" in captured.out
    assert "Verdict:" in captured.out
    assert "Analysis evidence" in captured.out
    assert "Best candidates:" in captured.out
    # Stub-derived analysis must never present as a confident verdict.
    assert "Verdict: COMPATIBLE" not in captured.out
    assert "Verdict: UNLIKELY" not in captured.out


def test_cli_is_deterministic_for_the_same_file(tmp_path, capsys):
    song_a = tmp_path / "a.mp3"
    song_b = tmp_path / "b.mp3"
    song_a.touch()
    song_b.touch()

    main([str(song_a), str(song_b)])
    first = capsys.readouterr().out
    main([str(song_a), str(song_b)])
    second = capsys.readouterr().out

    assert first == second


def test_cli_errors_on_missing_file(tmp_path, capsys):
    song_a = tmp_path / "missing.mp3"
    song_b = tmp_path / "b.mp3"
    song_b.touch()

    exit_code = main([str(song_a), str(song_b)])

    assert exit_code == 1
    assert "not found" in capsys.readouterr().err


def test_cli_errors_on_unsupported_extension(tmp_path, capsys):
    song_a = tmp_path / "a.txt"
    song_b = tmp_path / "b.mp3"
    song_a.touch()
    song_b.touch()

    exit_code = main([str(song_a), str(song_b)])

    assert exit_code == 1
    assert "Unsupported audio file extension" in capsys.readouterr().err


def test_cli_requires_two_arguments():
    with pytest.raises(SystemExit):
        main(["only_one.mp3"])
