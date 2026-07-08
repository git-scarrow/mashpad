"""Tests for the local tempo-evaluation corpus workflow (mashpad.tempo_eval).

No real audio, per the project guardrail: relation/summary logic is driven
by fake in-memory backends, and the one end-to-end CLI test synthesizes a
click-track WAV on the fly inside tmp_path.
"""

import json
import struct
import wave
from pathlib import Path

import pytest

from mashpad.models import TempoCandidate
from mashpad.tempo_eval import (
    STATUS_ERROR,
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    TempoFixture,
    accepted_interpretations,
    classify_relation,
    evaluate_fixture,
    evaluate_index,
    load_index,
    main,
    summarize,
)

EXAMPLE_INDEX = Path(__file__).parent / "fixtures" / "audio_index.example.json"
FRAME_RATE = 8000


class _FakeBackend:
    """In-memory backend returning fixed candidates (never reads the file)."""

    name = "fake_eval_backend"

    def __init__(self, candidates):
        self._candidates = tuple(candidates)

    def estimate_candidates(self, path):
        return self._candidates


class _ExplodingBackend:
    name = "exploding_backend"

    def estimate_candidates(self, path):
        raise ValueError("unsupported audio for this test")


def _candidate(bpm: float, confidence: float, multiplier: float = 1.0) -> TempoCandidate:
    return TempoCandidate(bpm=bpm, confidence=confidence, multiplier_from_primary=multiplier)


def _fixture(tmp_path: Path, **overrides) -> TempoFixture:
    """A fixture whose path exists (content irrelevant to fake backends)."""
    dummy = tmp_path / "dummy.wav"
    dummy.write_bytes(b"not real audio")
    data = {"id": "fx", "path": str(dummy), "expected_bpm": 120.0}
    data.update(overrides)
    return TempoFixture.from_dict(data)


def _write_click_track(path: Path, bpm: float, seconds: float = 8.0) -> None:
    """Synthesize a periodic click track -- generated on the fly, never
    committed, same pattern as tests/test_tempo_backend.py."""
    beat_interval = 60.0 / bpm
    n_samples = int(seconds * FRAME_RATE)
    samples = [0] * n_samples
    click_len = int(0.01 * FRAME_RATE)

    t = 0.0
    while t < seconds:
        start = int(t * FRAME_RATE)
        for i in range(click_len):
            if start + i < n_samples:
                samples[start + i] = 20000
        t += beat_interval

    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(FRAME_RATE)
        wav_file.writeframes(struct.pack(f"<{n_samples}h", *samples))


# --- schema loading -------------------------------------------------------


def test_example_index_loads():
    fixtures = load_index(EXAMPLE_INDEX)
    assert len(fixtures) >= 3
    by_id = {f.id: f for f in fixtures}
    pop = by_id["example_steady_pop_120"]
    assert pop.expected_bpm == 120.0
    assert pop.accepted_bpms == (120.0, 60.0, 240.0)
    assert pop.category == "steady_quantized_pop"
    assert pop.do_not_commit is True
    direct_only = by_id["example_click_100_direct_only"]
    assert direct_only.expected_relation == "direct"


def test_minimal_entry_gets_defaults():
    fx = TempoFixture.from_dict({"id": "m", "path": "/nowhere.wav", "expected_bpm": 90})
    assert fx.tolerance_percent == 4.0
    assert fx.category == "uncategorized"
    assert fx.expected_relation == "any"
    assert fx.accepted_bpms is None
    assert fx.do_not_commit is False
    # default accepted set: all three octave interpretations
    assert accepted_interpretations(fx) == (
        (90.0, "direct"),
        (45.0, "half_time"),
        (180.0, "double_time"),
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"id": "x", "path": "/f.wav"},  # missing expected_bpm
        {"id": "x", "expected_bpm": 120},  # missing path
        {"path": "/f.wav", "expected_bpm": 120},  # missing id
        {"id": "x", "path": "/f.wav", "expected_bpm": -3},  # non-positive bpm
        {"id": "x", "path": "/f.wav", "expected_bpm": 120, "accepted_bpms": []},
        {"id": "x", "path": "/f.wav", "expected_bpm": 120, "tolerance_percent": 0},
        {"id": "x", "path": "/f.wav", "expected_bpm": 120, "expected_relation": "triplet"},
        {"id": "x", "path": "/f.wav", "expected_bpm": 120, "expected_bmp": 120},  # typo key
        # expected_relation excludes every accepted bpm
        {
            "id": "x",
            "path": "/f.wav",
            "expected_bpm": 120,
            "accepted_bpms": [60.0],
            "expected_relation": "direct",
        },
    ],
)
def test_invalid_entries_raise(entry):
    with pytest.raises(ValueError):
        TempoFixture.from_dict(entry)


def test_duplicate_ids_raise(tmp_path):
    index = tmp_path / "index.json"
    entry = {"id": "same", "path": "/f.wav", "expected_bpm": 120}
    index.write_text(json.dumps([entry, entry]))
    with pytest.raises(ValueError, match="duplicate fixture id"):
        load_index(index)


# --- relation classification ----------------------------------------------


@pytest.mark.parametrize(
    ("bpm", "expected"),
    [
        (120.0, "direct"),
        (123.5, "direct"),  # within 4% of 120
        (60.0, "half_time"),
        (240.0, "double_time"),
        (97.0, "other"),
    ],
)
def test_classify_relation(bpm, expected):
    assert classify_relation(bpm, 120.0, 4.0) == expected


# --- evaluation: pass/fail/skip/error --------------------------------------


def test_missing_file_is_skipped(tmp_path):
    fx = TempoFixture.from_dict(
        {"id": "gone", "path": str(tmp_path / "missing.wav"), "expected_bpm": 120}
    )
    result = evaluate_fixture(fx, _FakeBackend([_candidate(120.0, 0.9)]))
    assert result.status == STATUS_SKIP
    assert "file not found" in result.detail


def test_direct_match_passes(tmp_path):
    fx = _fixture(tmp_path, expected_bpm=120.0)
    backend = _FakeBackend(
        [_candidate(119.0, 0.8), _candidate(59.5, 0.3, 0.5), _candidate(238.0, 0.2, 2.0)]
    )
    result = evaluate_fixture(fx, backend)
    assert result.status == STATUS_PASS
    assert result.selected_relation == "direct"
    assert result.selected.bpm == 119.0
    assert result.percent_error == pytest.approx(100 * 1.0 / 120.0)
    assert result.warnings == ()


def test_half_time_interpretation_passes_not_fails(tmp_path):
    """A backend reading 85 for an expected 170 pulse found a *usable*
    half-time interpretation -- pass, classified, never treated as wrong."""
    fx = _fixture(tmp_path, expected_bpm=170.0)
    result = evaluate_fixture(fx, _FakeBackend([_candidate(85.0, 0.7)]))
    assert result.status == STATUS_PASS
    assert result.selected_relation == "half_time"


def test_double_time_interpretation_passes(tmp_path):
    fx = _fixture(tmp_path, expected_bpm=70.0)
    result = evaluate_fixture(fx, _FakeBackend([_candidate(140.0, 0.7)]))
    assert result.status == STATUS_PASS
    assert result.selected_relation == "double_time"


def test_unrelated_tempo_fails(tmp_path):
    fx = _fixture(tmp_path, expected_bpm=120.0)
    result = evaluate_fixture(fx, _FakeBackend([_candidate(97.0, 0.4)]))
    assert result.status == STATUS_FAIL
    assert result.selected_relation == "other"
    assert result.percent_error > 4.0
    assert result.suspicious is False


def test_expected_relation_direct_rejects_half_time(tmp_path):
    fx = _fixture(tmp_path, expected_bpm=240.0, expected_relation="direct")
    result = evaluate_fixture(fx, _FakeBackend([_candidate(120.0, 0.9)]))
    assert result.status == STATUS_FAIL


def test_high_confidence_failure_is_flagged_suspicious(tmp_path):
    fx = _fixture(tmp_path, expected_bpm=120.0)
    result = evaluate_fixture(fx, _FakeBackend([_candidate(97.0, 0.9)]))
    assert result.status == STATUS_FAIL
    assert result.suspicious is True
    assert any("suspicious" in w for w in result.warnings)


def test_non_primary_match_passes_with_warning(tmp_path):
    """Primary wrong, companion right: usable for Mashpad (all candidates
    are scored) but flagged so a companion-leaning backend is visible."""
    fx = _fixture(tmp_path, expected_bpm=120.0)
    backend = _FakeBackend([_candidate(97.0, 0.9), _candidate(120.5, 0.4, 2.0)])
    result = evaluate_fixture(fx, backend)
    assert result.status == STATUS_PASS
    assert result.selected.bpm == 120.5
    assert any("non-primary" in w for w in result.warnings)


def test_backend_value_error_becomes_error_status(tmp_path):
    fx = _fixture(tmp_path)
    result = evaluate_fixture(fx, _ExplodingBackend())
    assert result.status == STATUS_ERROR
    assert "unsupported audio" in result.detail


def test_evaluate_index_unknown_backend_raises_immediately(tmp_path):
    fx = _fixture(tmp_path)
    with pytest.raises(ValueError, match="unknown tempo backend"):
        evaluate_index([fx], "no_such_backend")


# --- summary ----------------------------------------------------------------


def test_summary_counts_and_grouping(tmp_path):
    passing = _fixture(tmp_path, id="ok", category="steady_quantized_pop")
    failing = _fixture(tmp_path, id="bad", category="syncopated_or_swing")
    erroring = _fixture(tmp_path, id="boom", category="known_bad_or_unusable")
    missing = TempoFixture.from_dict(
        {"id": "gone", "path": str(tmp_path / "missing.wav"), "expected_bpm": 120}
    )

    results = [
        evaluate_fixture(passing, _FakeBackend([_candidate(120.0, 0.8)])),
        evaluate_fixture(failing, _FakeBackend([_candidate(97.0, 0.9)])),
        evaluate_fixture(erroring, _ExplodingBackend()),
        evaluate_fixture(missing, _FakeBackend([_candidate(120.0, 0.8)])),
    ]
    summary = summarize(results)

    assert summary.total == 4
    assert summary.passes == 1
    assert summary.failures == 1
    assert summary.errors == 1
    assert summary.skipped == 1
    assert summary.pass_rate == pytest.approx(1 / 3)
    assert summary.failures_by_category == {
        "syncopated_or_swing": 1,
        "known_bad_or_unusable": 1,
    }
    assert summary.suspicious_ids == ("bad",)


def test_summary_all_skipped_has_no_pass_rate(tmp_path):
    missing = TempoFixture.from_dict(
        {"id": "gone", "path": str(tmp_path / "missing.wav"), "expected_bpm": 120}
    )
    summary = summarize([evaluate_fixture(missing, _FakeBackend([_candidate(120.0, 0.8)]))])
    assert summary.pass_rate is None


# --- CLI (main) --------------------------------------------------------------


def _write_index(tmp_path: Path, entries: list[dict]) -> Path:
    index = tmp_path / "index.json"
    index.write_text(json.dumps(entries))
    return index


def test_main_end_to_end_with_synthetic_click(tmp_path, capsys):
    wav = tmp_path / "click_120.wav"
    _write_click_track(wav, bpm=120.0)
    index = _write_index(
        tmp_path,
        [
            {
                "id": "click_120",
                "path": str(wav),
                "expected_bpm": 120.0,
                "category": "steady_quantized_pop",
                "source_kind": "synthetic_click",
            },
            {"id": "gone", "path": str(tmp_path / "missing.wav"), "expected_bpm": 90.0},
        ],
    )
    json_out = tmp_path / "results.json"

    exit_code = main(["--index", str(index), "--backend", "energy_flux", "--json", str(json_out)])

    # missing file is skipped, not failed -- the run still exits 0
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "SKIP" in out
    assert "pass rate" in out
    assert "not a calibrated probability" in out

    payload = json.loads(json_out.read_text())
    assert payload["schema"] == "mashpad-tempo-eval-results/v1"
    assert payload["backend"] == "energy_flux"
    assert len(payload["results"]) == 2
    assert payload["summary"]["passes"] == 1
    assert payload["summary"]["skipped"] == 1
    selected = payload["results"][0]["selected"]
    assert abs(selected["bpm"] - 120.0) <= 6.0


def test_main_accepts_positional_index(tmp_path, capsys):
    wav = tmp_path / "click_100.wav"
    _write_click_track(wav, bpm=100.0)
    index = _write_index(tmp_path, [{"id": "click_100", "path": str(wav), "expected_bpm": 100.0}])
    assert main([str(index)]) == 0
    assert "click_100" in capsys.readouterr().out


def test_main_failure_sets_exit_code(tmp_path, capsys):
    wav = tmp_path / "click_120.wav"
    _write_click_track(wav, bpm=120.0)
    # expected pulse unrelated to the click track, direct-only: must fail
    index = _write_index(
        tmp_path,
        [
            {
                "id": "wrong_expectation",
                "path": str(wav),
                "expected_bpm": 97.0,
                "accepted_bpms": [97.0],
                "expected_relation": "direct",
            }
        ],
    )
    assert main([str(index)]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_unknown_backend_fails_clearly(tmp_path):
    index = _write_index(tmp_path, [{"id": "x", "path": "/f.wav", "expected_bpm": 120}])
    with pytest.raises(SystemExit) as excinfo:
        main(["--backend", "no_such_backend", str(index)])
    assert excinfo.value.code == 2


def test_main_unreadable_index_returns_2(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 2
    assert "could not load index" in capsys.readouterr().err


def test_main_requires_an_index():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
