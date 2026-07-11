"""Within-pair ranking evaluation of probe features against grounded
registration labels.

For each labeled *success* on a pair, does a feature rank it above the
pair's negatives? Metrics per feature and direction: pairwise preference
accuracy, success rank, top-k recall, and abstentions. Reporting only —
this module fits nothing, tunes nothing, and both directions
(higher-is-better and lower-is-better) are always reported side by side:
picking the better direction *is* in-sample fitting, so on a single pair
the direction column is explicitly provisional.

Label discipline: only `annotated` labels are evaluation truth. Records
whose state is `hypothesis` may be included in a run only with
`allow_hypothesis_labels=True`, and the report then carries
`provisional=True` — such a run plans listening work; it can never
support a feature claim. This module is the one sanctioned *consumer* of
corpus labels; probe/discovery code must never read them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TOP_K = 3


@dataclass(frozen=True, slots=True)
class LabeledCandidate:
    offset_bars: int
    label: str  # corpus taxonomy: success / *_negative
    state: str  # annotated / hypothesis / unresolved
    features: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class FeatureReport:
    feature: str
    direction: str  # "higher" or "lower" (is better)
    pairwise_accuracy: float | None  # success preferred over negative
    n_pairs_compared: int
    success_ranks: tuple[int, ...]  # 1-based rank of each success
    n_candidates_ranked: int
    top_k_recall: float | None
    abstentions: int  # candidates where the feature is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "direction": self.direction,
            "pairwise_accuracy": self.pairwise_accuracy,
            "n_pairs_compared": self.n_pairs_compared,
            "success_ranks": list(self.success_ranks),
            "n_candidates_ranked": self.n_candidates_ranked,
            "top_k_recall": self.top_k_recall,
            "abstentions": self.abstentions,
        }


def _usable(
    candidates: tuple[LabeledCandidate, ...], allow_hypothesis: bool
) -> tuple[tuple[LabeledCandidate, ...], bool]:
    provisional = False
    usable = []
    for c in candidates:
        if c.state == "annotated":
            usable.append(c)
        elif c.state == "hypothesis" and allow_hypothesis:
            usable.append(c)
            provisional = True
    return tuple(usable), provisional


def evaluate_feature(
    candidates: tuple[LabeledCandidate, ...],
    feature: str,
    direction: str,
    *,
    top_k: int = TOP_K,
) -> FeatureReport:
    """Rank one pair's candidates by one feature in one stated direction."""
    if direction not in ("higher", "lower"):
        raise ValueError("direction must be 'higher' or 'lower'")
    scored = [c for c in candidates if c.features.get(feature) is not None]
    abstained = len(candidates) - len(scored)
    successes = [c for c in scored if c.label == "success"]
    negatives = [c for c in scored if c.label.endswith("_negative")]

    sign = 1.0 if direction == "higher" else -1.0
    wins, comparisons = 0.0, 0
    for s in successes:
        for n in negatives:
            sv = sign * s.features[feature]  # type: ignore[operator]
            nv = sign * n.features[feature]  # type: ignore[operator]
            comparisons += 1
            if sv > nv:
                wins += 1.0
            elif sv == nv:
                wins += 0.5  # a tie discriminates nothing

    ranked = sorted(scored, key=lambda c: -sign * c.features[feature])  # type: ignore[operator]
    ranks = tuple(
        1 + next(i for i, c in enumerate(ranked) if c.offset_bars == s.offset_bars)
        for s in successes
    )
    in_top = sum(1 for r in ranks if r <= top_k)

    return FeatureReport(
        feature=feature,
        direction=direction,
        pairwise_accuracy=wins / comparisons if comparisons else None,
        n_pairs_compared=comparisons,
        success_ranks=ranks,
        n_candidates_ranked=len(ranked),
        top_k_recall=in_top / len(successes) if successes else None,
        abstentions=abstained,
    )


def within_pair_report(
    candidates: tuple[LabeledCandidate, ...],
    *,
    allow_hypothesis_labels: bool = False,
    top_k: int = TOP_K,
) -> dict[str, Any]:
    """Evaluate every feature present, both directions, on one pair.

    Returns a report dict (JSON-able). `provisional` is True whenever any
    hypothesis-state label was used — the report is then audition
    planning, not evidence. With fewer than one annotated success or one
    annotated negative, the honest output is an abstention report, not
    metrics."""
    usable, provisional = _usable(candidates, allow_hypothesis_labels)
    feature_names = sorted({name for c in usable for name in c.features})
    successes = [c for c in usable if c.label == "success"]
    negatives = [c for c in usable if c.label.endswith("_negative")]

    reports = []
    if successes and negatives:
        for name in feature_names:
            for direction in ("higher", "lower"):
                reports.append(evaluate_feature(usable, name, direction, top_k=top_k).to_dict())

    return {
        "n_candidates": len(candidates),
        "n_usable": len(usable),
        "n_successes": len(successes),
        "n_negatives": len(negatives),
        "provisional": provisional,
        "single_pair_warning": (
            "single-pair evaluation: direction choices and any separation "
            "are in-sample observations; no feature claim without "
            "leave-one-pair-out results across the corpus"
        ),
        "abstention_report": (
            None
            if successes and negatives
            else "insufficient usable labels (need >=1 success and >=1 negative) — no metrics"
        ),
        "features": reports,
    }


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Join probe features (trajectory and/or span JSON artifacts) with
    corpus labels for one pair and print the within-pair ranking report."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Within-pair feature ranking report")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--pair-id", required=True)
    parser.add_argument(
        "--trajectories", type=Path, default=None, help="trajectory_probe.py --json artifact"
    )
    parser.add_argument(
        "--span", type=Path, default=None, help="probe_registration_features.py --json artifact"
    )
    parser.add_argument(
        "--allow-hypothesis-labels",
        action="store_true",
        help="include hypothesis-state labels (report becomes provisional planning output)",
    )
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    features_by_offset: dict[int, dict[str, float | None]] = {}
    if args.trajectories:
        payload = json.loads(args.trajectories.read_text())
        for off, flat in payload.get("flat_features", {}).items():
            features_by_offset.setdefault(int(off), {}).update(flat)
    if args.span:
        payload = json.loads(args.span.read_text())
        for probe in payload.get("probes", []):
            flat = {
                k: v
                for k, v in probe.items()
                if k not in ("offset_bars", "phrase_class_residue", "note")
                and isinstance(v, (int, float, type(None)))
            }
            features_by_offset.setdefault(int(probe["offset_bars"]), {}).update(flat)
    if not features_by_offset:
        parser.error("need --trajectories and/or --span")

    corpus = json.loads(args.corpus.read_text())
    pair = next(p for p in corpus["pairs"] if p["pair_id"] == args.pair_id)
    candidates = tuple(
        LabeledCandidate(
            offset_bars=reg["offset_bars"],
            label=reg["label"],
            state=reg["state"],
            features=features_by_offset.get(reg["offset_bars"], {}),
        )
        for reg in pair["registrations"]
        if reg["offset_bars"] in features_by_offset
    )
    report = within_pair_report(candidates, allow_hypothesis_labels=args.allow_hypothesis_labels)
    report["pair_id"] = args.pair_id
    report["labels_dropped_no_features"] = sorted(
        reg["offset_bars"]
        for reg in pair["registrations"]
        if reg["offset_bars"] not in features_by_offset
    )

    print(
        f"pair {args.pair_id}: {report['n_usable']}/{report['n_candidates']} labeled "
        f"candidates usable ({report['n_successes']} success, "
        f"{report['n_negatives']} negative)"
        + ("  [PROVISIONAL: hypothesis labels included]" if report["provisional"] else "")
    )
    if report["abstention_report"]:
        print(report["abstention_report"])
    else:
        print(f"{'feature':<38} {'dir':<6} {'pairwise':>8} {'ranks':>10} {'top3':>5} {'abst':>5}")
        ordered = sorted(
            report["features"],
            key=lambda f: -(f["pairwise_accuracy"] if f["pairwise_accuracy"] is not None else -1),
        )
        for f in ordered:
            acc = f["pairwise_accuracy"]
            print(
                f"{f['feature']:<38} {f['direction']:<6} "
                f"{acc if acc is not None else '-':>8} "
                f"{','.join(str(r) for r in f['success_ranks']):>10} "
                f"{f['top_k_recall'] if f['top_k_recall'] is not None else '-':>5} "
                f"{f['abstentions']:>5}"
            )
        print(f"\n{report['single_pair_warning']}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2))
        print(f"wrote {args.json}")
    return 0
