"""Local-only tempo-evaluation corpus workflow.

The importable core behind `scripts/eval_tempo.py`: given a user-maintained
*local* index of audio fixtures with expected tempo interpretations
(schema: `tests/fixtures/audio_index.example.json`, guide:
`docs/tempo-eval.md`), run one registered tempo backend
(`mashpad.analysis.tempo_backend`) over every fixture and report, per
fixture, whether the backend produced an accepted tempo interpretation,
*which* interpretation (direct / half-time / double-time), how far off it
was, and whether its confidence was misleading.

Design constraints:

- **Local-only, copyright-safe.** Audio paths point at user-supplied local
  files that are never committed (see `fixtures/README.md`). A missing
  file is *skipped*, not failed, so an index degrades gracefully across
  machines instead of aborting the run.
- **Half-/double-time are interpretations, not mistakes.** For mashup work
  a half-time reading of a 170 BPM track can be exactly the pulse you'd
  mix at. A fixture accepts a *set* of interpretations; the evaluator
  classifies what the backend chose rather than assuming direct time is
  the only truth. A fixture that really does want direct-only sets
  `expected_relation: "direct"`.
- **Confidence is backend self-consistency, not calibrated probability.**
  Results with high confidence but no accepted match are flagged
  "suspicious" precisely because confidence can mislead.

This module lives in the package (rather than in `scripts/`) so the
behavior is unit-testable (`tests/test_tempo_eval.py`) without real audio.
It is an evaluation harness only — none of it is wired into
`analyze_track`/`mashcheck`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from mashpad.analysis.tempo_backend import (
    DEFAULT_BACKEND_NAME,
    TempoBackend,
    available_backends,
    get_tempo_backend,
)
from mashpad.models import TempoCandidate

RESULTS_SCHEMA = "mashpad-tempo-eval-results/v1"

DEFAULT_TOLERANCE_PERCENT = 4.0

# A *failed* fixture whose primary candidate carries confidence at or above
# this is flagged "suspicious": the backend was sure of a tempo no accepted
# interpretation agrees with. Heuristic threshold, not a calibrated cutoff.
HIGH_CONFIDENCE_FAIL_THRESHOLD = 0.75

# Relation of a candidate BPM to a fixture's expected pulse. All three are
# potentially *valid* mashup interpretations; "other" means unrelated.
RELATION_MULTIPLIERS: dict[str, float] = {
    "direct": 1.0,
    "half_time": 0.5,
    "double_time": 2.0,
}
RELATION_OTHER = "other"
KNOWN_EXPECTED_RELATIONS = ("any", *RELATION_MULTIPLIERS)

# Recommended (not required) fixture categories, chosen to reflect real
# mashup tempo risks — see docs/tempo-eval.md. Free-form strings are
# accepted so a private index can grow its own labels.
RECOMMENDED_CATEGORIES = (
    "steady_quantized_pop",
    "half_time_ambiguous",
    "double_time_ambiguous",
    "sparse_intro",
    "drumless_or_soft_onset",
    "tempo_drift_live",
    "syncopated_or_swing",
    "known_bad_or_unusable",
)

KNOWN_SOURCE_KINDS = (
    "synthetic_click",
    "public_domain",
    "creative_commons",
    "owned_file",
    "user_private",
)

_FIXTURE_KEYS = frozenset(
    {
        "id",
        "path",
        "expected_bpm",
        "accepted_bpms",
        "tolerance_percent",
        "category",
        "notes",
        "expected_relation",
        "source_kind",
        "do_not_commit",
    }
)

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class TempoFixture:
    """One row of a local audio index: a file plus its tempo expectations."""

    id: str
    path: Path
    expected_bpm: float
    accepted_bpms: tuple[float, ...] | None = None
    tolerance_percent: float = DEFAULT_TOLERANCE_PERCENT
    category: str = "uncategorized"
    notes: str = ""
    expected_relation: str = "any"
    source_kind: str | None = None
    do_not_commit: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> TempoFixture:
        fixture_id = data.get("id")
        label = f"fixture {fixture_id!r}" if fixture_id else "fixture (missing 'id')"

        unknown = set(data) - _FIXTURE_KEYS
        if unknown:
            raise ValueError(
                f"{label}: unknown keys {sorted(unknown)} (typo? known keys: "
                f"{sorted(_FIXTURE_KEYS)})"
            )
        for required in ("id", "path", "expected_bpm"):
            if required not in data:
                raise ValueError(f"{label}: missing required key {required!r}")

        expected_bpm = float(data["expected_bpm"])
        if expected_bpm <= 0:
            raise ValueError(f"{label}: expected_bpm must be positive, got {expected_bpm}")

        accepted_raw = data.get("accepted_bpms")
        accepted: tuple[float, ...] | None = None
        if accepted_raw is not None:
            accepted = tuple(float(b) for b in accepted_raw)
            if not accepted or any(b <= 0 for b in accepted):
                raise ValueError(f"{label}: accepted_bpms must be a non-empty list of positive BPM")

        tolerance = float(data.get("tolerance_percent", DEFAULT_TOLERANCE_PERCENT))
        if tolerance <= 0:
            raise ValueError(f"{label}: tolerance_percent must be positive, got {tolerance}")

        relation = data.get("expected_relation", "any")
        if relation not in KNOWN_EXPECTED_RELATIONS:
            raise ValueError(
                f"{label}: expected_relation {relation!r} not one of {KNOWN_EXPECTED_RELATIONS}"
            )

        fixture = cls(
            id=str(data["id"]),
            path=Path(data["path"]),
            expected_bpm=expected_bpm,
            accepted_bpms=accepted,
            tolerance_percent=tolerance,
            category=str(data.get("category", "uncategorized")),
            notes=str(data.get("notes", "")),
            expected_relation=relation,
            source_kind=data.get("source_kind"),
            do_not_commit=bool(data.get("do_not_commit", False)),
        )
        if not accepted_interpretations(fixture):
            raise ValueError(
                f"{label}: expected_relation {relation!r} matches none of the accepted BPMs "
                f"{list(accepted or ())} relative to expected_bpm {expected_bpm}"
            )
        return fixture


def classify_relation(bpm: float, expected_bpm: float, tolerance_percent: float) -> str:
    """Classify `bpm` against the expected pulse: direct, half_time,
    double_time (within `tolerance_percent` of the corresponding target),
    or "other" if it matches none of those."""
    for relation, multiplier in RELATION_MULTIPLIERS.items():
        target = expected_bpm * multiplier
        if abs(bpm - target) <= target * tolerance_percent / 100.0:
            return relation
    return RELATION_OTHER


def accepted_interpretations(fixture: TempoFixture) -> tuple[tuple[float, str], ...]:
    """The (bpm, relation) pairs this fixture accepts as a usable pulse.

    With explicit `accepted_bpms`, each is classified relative to
    `expected_bpm` (an accepted BPM unrelated to the expected pulse
    classifies as "other" but still counts as accepted — the user said so).
    Without them, all three octave interpretations of `expected_bpm` are
    accepted, per the Mashpad stance that half-/double-time are valid
    readings. `expected_relation` (when not "any") then narrows the set.
    """
    if fixture.accepted_bpms is not None:
        interps = [
            (bpm, classify_relation(bpm, fixture.expected_bpm, fixture.tolerance_percent))
            for bpm in fixture.accepted_bpms
        ]
    else:
        interps = [
            (fixture.expected_bpm * multiplier, relation)
            for relation, multiplier in RELATION_MULTIPLIERS.items()
        ]
    if fixture.expected_relation != "any":
        interps = [item for item in interps if item[1] == fixture.expected_relation]
    return tuple(interps)


@dataclass(frozen=True)
class FixtureResult:
    """Outcome of running one backend against one fixture."""

    fixture: TempoFixture
    backend: str
    status: str  # STATUS_PASS / STATUS_FAIL / STATUS_SKIP / STATUS_ERROR
    candidates: tuple[TempoCandidate, ...] = ()
    selected: TempoCandidate | None = None
    selected_relation: str | None = None
    percent_error: float | None = None  # vs the nearest accepted interpretation
    warnings: tuple[str, ...] = ()
    suspicious: bool = False  # failed despite high primary confidence
    detail: str = ""  # skip/error reason

    def to_dict(self) -> dict:
        return {
            "id": self.fixture.id,
            "category": self.fixture.category,
            "backend": self.backend,
            "status": self.status,
            "expected_bpm": self.fixture.expected_bpm,
            "accepted_interpretations": [
                {"bpm": bpm, "relation": relation}
                for bpm, relation in accepted_interpretations(self.fixture)
            ],
            "tolerance_percent": self.fixture.tolerance_percent,
            "candidates": [c.to_dict() for c in self.candidates],
            "selected": self.selected.to_dict() if self.selected else None,
            "selected_relation": self.selected_relation,
            "percent_error": self.percent_error,
            "warnings": list(self.warnings),
            "suspicious": self.suspicious,
            "detail": self.detail,
            "notes": self.fixture.notes,
        }


def evaluate_fixture(fixture: TempoFixture, backend: TempoBackend) -> FixtureResult:
    """Run one backend against one fixture.

    Missing file -> skip (never fails the run). Backend `ValueError`
    (unreadable/too-short/unsupported audio) -> error. Otherwise pass if
    *any* returned candidate lands within tolerance of an accepted
    interpretation — candidate-aware on purpose, matching how
    `score_tempo_candidates` searches every interpretation. The primary
    candidate is selected when it matches; otherwise the best matching
    companion is, with a warning (not a downgrade).
    `ImportError` (e.g. librosa extra not installed) is deliberately not
    caught: it would fail every fixture identically, so the caller aborts.
    """
    if not fixture.path.exists():
        return FixtureResult(
            fixture=fixture,
            backend=backend.name,
            status=STATUS_SKIP,
            detail=f"file not found: {fixture.path}",
        )

    try:
        candidates = backend.estimate_candidates(fixture.path)
    except ValueError as exc:
        return FixtureResult(
            fixture=fixture, backend=backend.name, status=STATUS_ERROR, detail=str(exc)
        )

    interps = accepted_interpretations(fixture)
    tolerance = fixture.tolerance_percent
    matches = [
        (candidate, target_bpm, relation)
        for candidate in candidates
        for target_bpm, relation in interps
        if abs(candidate.bpm - target_bpm) <= target_bpm * tolerance / 100.0
    ]

    if matches:
        # Prefer the primary candidate when it matched (the backend's own
        # choice was acceptable); otherwise the best-matching companion.
        def _selection_key(match: tuple[TempoCandidate, float, str]):
            candidate, target_bpm, _ = match
            relative_error = abs(candidate.bpm - target_bpm) / target_bpm
            return (candidate is not candidates[0], -candidate.confidence, relative_error)

        candidate, target_bpm, relation = min(matches, key=_selection_key)
        warnings = []
        primary = candidates[0]
        if candidate is not primary:
            warnings.append(
                f"matched via non-primary candidate; primary was {primary.bpm:g} BPM "
                f"(confidence {primary.confidence:g})"
            )
        return FixtureResult(
            fixture=fixture,
            backend=backend.name,
            status=STATUS_PASS,
            candidates=candidates,
            selected=candidate,
            selected_relation=relation,
            percent_error=abs(candidate.bpm - target_bpm) / target_bpm * 100.0,
            warnings=tuple(warnings),
        )

    primary = candidates[0]
    percent_error = min(
        abs(primary.bpm - target_bpm) / target_bpm * 100.0 for target_bpm, _ in interps
    )
    suspicious = primary.confidence >= HIGH_CONFIDENCE_FAIL_THRESHOLD
    warnings = []
    if suspicious:
        warnings.append(
            f"suspicious: confidence {primary.confidence:g} >= "
            f"{HIGH_CONFIDENCE_FAIL_THRESHOLD} but no accepted interpretation matched"
        )
    return FixtureResult(
        fixture=fixture,
        backend=backend.name,
        status=STATUS_FAIL,
        candidates=candidates,
        selected=primary,
        selected_relation=classify_relation(primary.bpm, fixture.expected_bpm, tolerance),
        percent_error=percent_error,
        warnings=tuple(warnings),
        suspicious=suspicious,
    )


def evaluate_index(fixtures: list[TempoFixture], backend_name: str) -> list[FixtureResult]:
    """Evaluate every fixture with one backend.

    Resolves the backend *once* up front so an unknown backend name raises
    a clear `ValueError` immediately instead of surfacing as a per-fixture
    error on every row.
    """
    backend = get_tempo_backend(backend_name)
    return [evaluate_fixture(fixture, backend) for fixture in fixtures]


@dataclass(frozen=True)
class EvalSummary:
    total: int
    passes: int
    failures: int
    errors: int
    skipped: int
    pass_rate: float | None  # passes / (passes + failures + errors); None if nothing evaluated
    failures_by_category: dict[str, int]  # fail + error rows, grouped
    suspicious_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "passes": self.passes,
            "failures": self.failures,
            "errors": self.errors,
            "skipped": self.skipped,
            "pass_rate": self.pass_rate,
            "failures_by_category": dict(self.failures_by_category),
            "suspicious_ids": list(self.suspicious_ids),
        }


def summarize(results: list[FixtureResult]) -> EvalSummary:
    passes = sum(r.status == STATUS_PASS for r in results)
    failures = sum(r.status == STATUS_FAIL for r in results)
    errors = sum(r.status == STATUS_ERROR for r in results)
    skipped = sum(r.status == STATUS_SKIP for r in results)
    evaluated = passes + failures + errors

    failures_by_category: dict[str, int] = {}
    for result in results:
        if result.status in (STATUS_FAIL, STATUS_ERROR):
            category = result.fixture.category
            failures_by_category[category] = failures_by_category.get(category, 0) + 1

    return EvalSummary(
        total=len(results),
        passes=passes,
        failures=failures,
        errors=errors,
        skipped=skipped,
        pass_rate=(passes / evaluated) if evaluated else None,
        failures_by_category=failures_by_category,
        suspicious_ids=tuple(r.fixture.id for r in results if r.suspicious),
    )


# --- rendering ------------------------------------------------------------


def _format_candidates(candidates: tuple[TempoCandidate, ...]) -> str:
    return " ".join(f"{c.bpm:g}@{c.confidence:.2f}" for c in candidates)


def render_table(results: list[FixtureResult]) -> str:
    """Fixed-width text table, one row per fixture, warnings indented below
    their row. `conf` is the selected candidate's backend confidence —
    self-consistency of the estimator, not a calibrated probability."""
    headers = ("id", "status", "expected", "selected", "relation", "err%", "conf", "candidates")
    rows: list[tuple[str, ...]] = []
    for result in results:
        fixture = result.fixture
        if result.status in (STATUS_SKIP, STATUS_ERROR):
            rows.append(
                (
                    fixture.id,
                    result.status.upper(),
                    f"{fixture.expected_bpm:g}",
                    "-",
                    "-",
                    "-",
                    "-",
                    result.detail,
                )
            )
            continue
        selected = result.selected
        assert selected is not None  # pass/fail rows always carry a selection
        rows.append(
            (
                fixture.id,
                result.status.upper(),
                f"{fixture.expected_bpm:g}",
                f"{selected.bpm:g}",
                result.selected_relation or "-",
                f"{result.percent_error:.1f}",
                f"{selected.confidence:.2f}",
                _format_candidates(result.candidates),
            )
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    lines = [
        "  ".join(header.ljust(widths[i]) for i, header in enumerate(headers)).rstrip(),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    for row, result in zip(rows, results):
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
        for warning in result.warnings:
            lines.append(f"    ! {warning}")
    return "\n".join(lines)


def render_summary(summary: EvalSummary, backend_name: str) -> str:
    lines = [
        f"== summary (backend: {backend_name}) ==",
        (
            f"fixtures: {summary.total} total | {summary.passes} passed | "
            f"{summary.failures} failed | {summary.errors} errors | "
            f"{summary.skipped} skipped (missing files)"
        ),
    ]
    if summary.pass_rate is None:
        lines.append("pass rate: n/a (no fixtures were evaluated — all skipped?)")
    else:
        evaluated = summary.passes + summary.failures + summary.errors
        lines.append(f"pass rate: {summary.pass_rate:.0%} of {evaluated} evaluated")
    if summary.failures_by_category:
        lines.append("failures/errors by category:")
        for category in sorted(summary.failures_by_category):
            lines.append(f"  {category}: {summary.failures_by_category[category]}")
    if summary.suspicious_ids:
        lines.append(
            f"suspicious (confidence >= {HIGH_CONFIDENCE_FAIL_THRESHOLD} but no accepted match):"
        )
        for fixture_id in summary.suspicious_ids:
            lines.append(f"  {fixture_id}")
    lines.append(
        "note: backend confidence is estimator self-consistency, not a calibrated probability."
    )
    return "\n".join(lines)


def results_to_json(
    results: list[FixtureResult], summary: EvalSummary, backend_name: str, index_path: str
) -> dict:
    """Machine-readable record of one run, for comparing backends/runs later."""
    return {
        "schema": RESULTS_SCHEMA,
        "backend": backend_name,
        "index": index_path,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "default_tolerance_percent": DEFAULT_TOLERANCE_PERCENT,
        "confidence_caveat": "backend self-consistency, not calibrated probability",
        "results": [r.to_dict() for r in results],
        "summary": summary.to_dict(),
    }


# --- index loading / CLI ----------------------------------------------------


def load_index(path: str | Path) -> list[TempoFixture]:
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("audio index must be a JSON list of fixture entries")
    fixtures = [TempoFixture.from_dict(entry) for entry in data]
    seen: set[str] = set()
    for fixture in fixtures:
        if fixture.id in seen:
            raise ValueError(f"duplicate fixture id {fixture.id!r} in index")
        seen.add(fixture.id)
    return fixtures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="eval_tempo.py",
        description=(
            "Local-only tempo evaluation: run one tempo backend over a private index of "
            "local audio fixtures and report which accepted tempo interpretation "
            "(direct / half-time / double-time) it found, how far off it was, and whether "
            "its confidence was misleading. See docs/tempo-eval.md and "
            "tests/fixtures/audio_index.example.json. Never commit audio or local paths."
        ),
    )
    parser.add_argument(
        "index_positional",
        nargs="?",
        metavar="index",
        help="path to a local audio_index.json (alternative to --index)",
    )
    parser.add_argument("--index", dest="index_flag", help="path to a local audio_index.json")
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND_NAME,
        choices=available_backends(),
        help=f"tempo backend to run (default: {DEFAULT_BACKEND_NAME})",
    )
    parser.add_argument(
        "--json",
        dest="json_path",
        metavar="PATH",
        help="also write machine-readable results to this file",
    )
    args = parser.parse_args(argv)

    index_path = args.index_flag or args.index_positional
    if not index_path:
        parser.error("an index file is required (positional or --index)")

    try:
        fixtures = load_index(index_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"error: could not load index {index_path}: {exc}", file=sys.stderr)
        return 2

    try:
        results = evaluate_index(fixtures, args.backend)
    except ImportError as exc:
        # e.g. --backend librosa without the tempo-librosa extra installed:
        # every fixture would fail identically, so abort with the real cause.
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = summarize(results)
    print(render_table(results))
    print()
    print(render_summary(summary, args.backend))

    if args.json_path:
        payload = results_to_json(results, summary, args.backend, str(index_path))
        with open(args.json_path, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"\nwrote machine-readable results to {args.json_path}")

    return 0 if (summary.failures == 0 and summary.errors == 0) else 1
