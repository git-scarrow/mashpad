"""Phrase-scale joint structure: ordered per-bar trajectories and
shape-preserving comparisons, per candidate registration.

Second probe generation for the joint-feature program
(`docs/experiment-joint-registration-features.md`). The first probe's
span-averaged frame statistics failed to discriminate attested
successes from loose-bar corruptions — structurally so: whole-bar
shifts preserve beat alignment, so anything averaged over the span
measures grid quality shared by all candidates. This module keeps the
*order* of events: per-aligned-bar series for each side, compared as
curves (local correlation, complementarity, change-point co-occurrence,
localized conflict maxima) rather than collapsed to means.

Same ground rules as `joint_features`: every requested offset is
measured (none excluded), all features come from explicitly
synchronized cross-source representations, no constant encodes a
witness-pair value, and the output is measurement — no rank, fit, or
verdict fields. Several curves are declared *crude proxies*
(`midband_salience` for melodic/vocal salience without stems;
`cadence_proxy` for cadence likelihood; `novelty` for section
boundaries); the stem-aware path (`mashpad.research.stems`) refines the
salience/masking measurements when stems exist. Cadence-to-*entry*
relationships need an arrangement plan (an entry decision), which a
registration alone does not define — declared out of scope here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from mashpad.research.discovery import BarSeries, rotate_chroma
from mashpad.research.joint_features import (
    _INTERVAL_DISSONANCE,
    FrameSeries,
    SyncFrames,
    _pearson,
    bar_correspondence,
    synchronize,
)

# --- explicit, uncalibrated policy defaults ---------------------------------

LOCAL_WINDOW_BARS = 8  # window for local (running) curve correlation
REPETITION_HORIZON_BARS = 8  # lookback for the repetition curve
PEAK_Z = 1.0  # a change-point is a local max at least this many SDs above the mean
PEAK_TOLERANCE_BARS = 1  # peaks within this distance count as co-occurring
NOVELTY_HALF_SPAN = 2  # bars each side of t compared for the novelty curve
# Coarse mel-band grouping of the 16-band profile (crude, declared):
LOW_BANDS = range(0, 3)  # ~sub + bass region
MID_BANDS = range(3, 10)  # ~melodic/vocal region -> `midband_salience` proxy
HIGH_BANDS = range(10, 16)

# Curves compared as shapes (agreement / local corr / complementarity):
SHAPE_CURVES = ("onset_density", "rms", "midband_salience")
# Curves whose change-points are matched across sides:
PEAK_CURVES = ("novelty", "harmonic_change", "cadence_proxy")


# --- per-side bar trajectories ------------------------------------------------


@dataclass(frozen=True, slots=True)
class BarTrajectories:
    """Ordered per-aligned-bar series for one side. All lists share the
    same length and bar indexing (aligned-bar order, both sides)."""

    onset_density: tuple[float, ...]
    rms: tuple[float, ...]
    energy_low: tuple[float, ...]
    energy_mid: tuple[float, ...]
    energy_high: tuple[float, ...]
    chroma: tuple[tuple[float, ...], ...]
    harmonic_change: tuple[float, ...]  # 1 - cos(chroma_t, chroma_{t-1})
    tension: tuple[float, ...]  # self-dissonance of the bar's own sonority
    novelty: tuple[float, ...]  # local past-vs-future contrast (boundary proxy)
    repetition: tuple[float, ...]  # max chroma similarity to recent bars
    midband_salience: tuple[float, ...]  # crude melodic/vocal-salience proxy
    build: tuple[float, ...]  # local energy trend (positive = building)
    drop: tuple[float, ...]  # sudden energy loss vs previous bar (break proxy)
    cadence_proxy: tuple[float, ...]  # harmonic motion resolving into an energy dip

    def curve(self, name: str) -> tuple[float, ...]:
        return getattr(self, name)


def _cos(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na > 0 and nb > 0 else 0.0


def _self_tension(chroma: tuple[float, ...]) -> float:
    total = sum(chroma)
    if total <= 0:
        return 0.0
    return sum(
        chroma[i] * chroma[j] * _INTERVAL_DISSONANCE[(i - j) % 12]
        for i in range(12)
        for j in range(12)
    ) / (total * total)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bar_trajectories(frames: FrameSeries, sync: SyncFrames, side: str) -> BarTrajectories:
    """Aggregate one side's synchronized frames into ordered per-bar series.

    `side` selects which index stream of `sync` to read ('host'/'guest');
    both sides use the same aligned-bar order, so curves are directly
    comparable position by position."""
    idx = sync.host_idx if side == "host" else sync.guest_idx
    by_bar: dict[int, list[int]] = {}
    for frame, bar in zip(idx, sync.bar_index, strict=True):
        by_bar.setdefault(bar, []).append(frame)
    bars = sorted(by_bar)

    onset, rms, e_low, e_mid, e_high, chroma_rows, salience = [], [], [], [], [], [], []
    for b in bars:
        rows = by_bar[b]
        onset.append(_mean([frames.onset[i] for i in rows]))
        rms.append(_mean([frames.rms[i] for i in rows]))
        low = _mean([sum(frames.bands[i][k] for k in LOW_BANDS) for i in rows])
        mid = _mean([sum(frames.bands[i][k] for k in MID_BANDS) for i in rows])
        high = _mean([sum(frames.bands[i][k] for k in HIGH_BANDS) for i in rows])
        e_low.append(low)
        e_mid.append(mid)
        e_high.append(high)
        total = low + mid + high
        salience.append((mid / total if total > 0 else 0.0) * rms[-1])
        mean_c = tuple(_mean([frames.chroma[i][k] for i in rows]) for k in range(12))
        norm = math.sqrt(sum(x * x for x in mean_c))
        chroma_rows.append(tuple(x / norm for x in mean_c) if norm > 0 else mean_c)

    n = len(bars)
    harmonic_change = [0.0] + [1.0 - _cos(chroma_rows[t], chroma_rows[t - 1]) for t in range(1, n)]
    tension = [_self_tension(c) for c in chroma_rows]
    repetition = [
        max(
            (
                _cos(chroma_rows[t], chroma_rows[t - k])
                for k in range(1, REPETITION_HORIZON_BARS + 1)
                if t - k >= 0
            ),
            default=0.0,
        )
        for t in range(n)
    ]

    def _profile(t: int) -> tuple[float, ...]:
        total = e_low[t] + e_mid[t] + e_high[t]
        bands = (e_low[t] / total, e_mid[t] / total, e_high[t] / total) if total > 0 else (0.0,) * 3
        return chroma_rows[t] + bands

    novelty = []
    for t in range(n):
        past = [_profile(u) for u in range(max(0, t - NOVELTY_HALF_SPAN), t + 1)]
        future = [_profile(u) for u in range(t + 1, min(n, t + 1 + NOVELTY_HALF_SPAN))]
        if not future:
            novelty.append(0.0)
            continue
        mean_past = tuple(_mean([p[k] for p in past]) for k in range(15))
        mean_future = tuple(_mean([p[k] for p in future]) for k in range(15))
        novelty.append(1.0 - _cos(mean_past, mean_future))

    build = []
    for t in range(n):
        lo, hi = max(0, t - 1), min(n - 1, t + 2)
        span = hi - lo
        build.append((rms[hi] - rms[lo]) / span if span > 0 else 0.0)
    drop = [0.0] + [max(0.0, rms[t - 1] - rms[t]) for t in range(1, n)]
    cadence = [harmonic_change[t] * (drop[t + 1] if t + 1 < n else 0.0) for t in range(n)]

    return BarTrajectories(
        onset_density=tuple(onset),
        rms=tuple(rms),
        energy_low=tuple(e_low),
        energy_mid=tuple(e_mid),
        energy_high=tuple(e_high),
        chroma=tuple(chroma_rows),
        harmonic_change=tuple(harmonic_change),
        tension=tuple(tension),
        novelty=tuple(novelty),
        repetition=tuple(repetition),
        midband_salience=tuple(salience),
        build=tuple(build),
        drop=tuple(drop),
        cadence_proxy=tuple(cadence),
    )


# --- shape-preserving comparisons ----------------------------------------------


def local_correlations(
    xs: tuple[float, ...], ys: tuple[float, ...], window: int = LOCAL_WINDOW_BARS
) -> tuple[float, ...]:
    """Running windowed Pearson correlation — the curve relationship *over
    time*, not collapsed to one number. Windows with a constant side are
    skipped (no correlation is not zero correlation)."""
    out = []
    for start in range(0, max(len(xs) - window + 1, 0)):
        r = _pearson(list(xs[start : start + window]), list(ys[start : start + window]))
        if r is not None:
            out.append(r)
    return tuple(out)


def complementarity_index(xs: tuple[float, ...], ys: tuple[float, ...]) -> float | None:
    """Fraction of bars where exactly one side is above its own mean —
    'taking turns'. 1.0 = perfectly complementary, 0.0 = always together
    (both up or both down)."""
    if len(xs) < 4:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    turns = sum(1 for x, y in zip(xs, ys, strict=True) if (x > mx) != (y > my))
    return turns / len(xs)


def peak_bars(curve: tuple[float, ...], z: float = PEAK_Z) -> tuple[int, ...]:
    """Local maxima at least `z` standard deviations above the curve mean —
    the change-point/event candidates of one side."""
    n = len(curve)
    if n < 3:
        return ()
    mean = sum(curve) / n
    var = sum((v - mean) ** 2 for v in curve) / n
    sd = math.sqrt(var)
    if sd <= 0:
        return ()
    threshold = mean + z * sd
    return tuple(
        t
        for t in range(1, n - 1)
        if curve[t] >= threshold and curve[t] >= curve[t - 1] and curve[t] >= curve[t + 1]
    )


def peak_cooccurrence(
    host_peaks: tuple[int, ...],
    guest_peaks: tuple[int, ...],
    tolerance: int = PEAK_TOLERANCE_BARS,
) -> float | None:
    """Jaccard-style co-occurrence of two sides' change-points: matches
    within ±tolerance bars over the union. None when neither side has a
    peak (nothing to co-occur — not a zero)."""
    if not host_peaks and not guest_peaks:
        return None
    matched_guest: set[int] = set()
    matches = 0
    for hp in host_peaks:
        best = None
        for gp in guest_peaks:
            if gp in matched_guest or abs(gp - hp) > tolerance:
                continue
            if best is None or abs(gp - hp) < abs(best - hp):
                best = gp
        if best is not None:
            matched_guest.add(best)
            matches += 1
    union = len(host_peaks) + len(guest_peaks) - matches
    return matches / union if union > 0 else None


def conflict_series(
    host: BarTrajectories, guest: BarTrajectories, pitch_shift: int
) -> tuple[float, ...]:
    """Per-bar joint conflict: pairwise pitch-class dissonance of the two
    bar sonorities (guest rotated by the registration's pitch shift),
    weighted by both sides' loudness — so a clash only counts where both
    are actually sounding. The *maximum* and its location matter as much
    as the mean: one unbearable phrase can sink an overlay that averages
    fine."""
    out = []
    for t in range(len(host.rms)):
        h = host.chroma[t]
        g = rotate_chroma(guest.chroma[t], pitch_shift)
        h_sum, g_sum = sum(h), sum(g)
        if h_sum <= 0 or g_sum <= 0:
            out.append(0.0)
            continue
        rough = sum(
            h[i] * g[j] * _INTERVAL_DISSONANCE[(i - j) % 12] for i in range(12) for j in range(12)
        ) / (h_sum * g_sum)
        out.append(rough * host.rms[t] * guest.rms[t])
    return tuple(out)


# --- the trajectory probe -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CurveComparison:
    agreement: float | None  # whole-span Pearson
    local_corr_mean: float | None
    local_corr_min: float | None
    complementarity: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agreement": self.agreement,
            "local_corr_mean": self.local_corr_mean,
            "local_corr_min": self.local_corr_min,
            "complementarity": self.complementarity,
        }


@dataclass(frozen=True, slots=True)
class TrajectoryProbe:
    """Shape-level joint measurements for one registration. Measurements
    only — no rank, fit, or verdict fields."""

    offset_bars: int
    n_bars: int
    curves: dict[str, CurveComparison]  # keyed by SHAPE_CURVES name
    peak_cooccurrences: dict[str, float | None]  # keyed by PEAK_CURVES name
    foreground_collision: float | None  # both-salient simultaneously (mean)
    conflict_mean: float | None
    conflict_max: float | None
    conflict_max_bar: int | None  # aligned-bar index of the worst clash
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset_bars": self.offset_bars,
            "n_bars": self.n_bars,
            "curves": {k: v.to_dict() for k, v in self.curves.items()},
            "peak_cooccurrences": dict(self.peak_cooccurrences),
            "foreground_collision": self.foreground_collision,
            "conflict_mean": self.conflict_mean,
            "conflict_max": self.conflict_max,
            "conflict_max_bar": self.conflict_max_bar,
            "note": self.note,
        }

    def flat_features(self) -> dict[str, float | None]:
        """One flat name->value view for the within-pair ranking
        evaluation. Values only; no direction-of-merit is implied."""
        flat: dict[str, float | None] = {}
        for name, cmp_ in self.curves.items():
            flat[f"{name}.agreement"] = cmp_.agreement
            flat[f"{name}.local_corr_mean"] = cmp_.local_corr_mean
            flat[f"{name}.local_corr_min"] = cmp_.local_corr_min
            flat[f"{name}.complementarity"] = cmp_.complementarity
        for name, value in self.peak_cooccurrences.items():
            flat[f"{name}.peak_cooccurrence"] = value
        flat["foreground_collision"] = self.foreground_collision
        flat["conflict_mean"] = self.conflict_mean
        flat["conflict_max"] = self.conflict_max
        return flat


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None else None


def trajectory_probe(
    host_frames: FrameSeries,
    guest_frames: FrameSeries,
    host_bars: BarSeries,
    guest_bars: BarSeries,
    offset_bars: int,
    pitch_shift: int,
) -> TrajectoryProbe:
    """Measure phrase-scale joint structure for one registration.
    Registrations with too little overlap are reported, never dropped."""
    knots = bar_correspondence(host_bars, guest_bars, offset_bars)
    if len(knots) < LOCAL_WINDOW_BARS:
        return TrajectoryProbe(
            offset_bars=offset_bars,
            n_bars=len(knots),
            curves={},
            peak_cooccurrences={},
            foreground_collision=None,
            conflict_mean=None,
            conflict_max=None,
            conflict_max_bar=None,
            note=(f"insufficient overlap ({len(knots)} bars < {LOCAL_WINDOW_BARS}) — not measured"),
        )
    sync = synchronize(host_frames, guest_frames, knots)
    host = bar_trajectories(host_frames, sync, "host")
    guest = bar_trajectories(guest_frames, sync, "guest")

    curves: dict[str, CurveComparison] = {}
    for name in SHAPE_CURVES:
        xs, ys = host.curve(name), guest.curve(name)
        locals_ = local_correlations(xs, ys)
        curves[name] = CurveComparison(
            agreement=_round(_pearson(list(xs), list(ys))),
            local_corr_mean=_round(sum(locals_) / len(locals_)) if locals_ else None,
            local_corr_min=_round(min(locals_)) if locals_ else None,
            complementarity=_round(complementarity_index(xs, ys)),
        )

    cooccur = {
        name: _round(peak_cooccurrence(peak_bars(host.curve(name)), peak_bars(guest.curve(name))))
        for name in PEAK_CURVES
    }

    h_sal, g_sal = host.midband_salience, guest.midband_salience
    h_ref = sorted(h_sal)[int(0.95 * (len(h_sal) - 1))] or 1.0
    g_ref = sorted(g_sal)[int(0.95 * (len(g_sal) - 1))] or 1.0
    collision = _mean(
        [min(min(h / h_ref, 1.0), min(g / g_ref, 1.0)) for h, g in zip(h_sal, g_sal, strict=True)]
    )

    conflicts = conflict_series(host, guest, pitch_shift)
    max_bar = max(range(len(conflicts)), key=lambda t: conflicts[t]) if conflicts else None

    return TrajectoryProbe(
        offset_bars=offset_bars,
        n_bars=len(knots),
        curves=curves,
        peak_cooccurrences=cooccur,
        foreground_collision=_round(collision),
        conflict_mean=_round(_mean(list(conflicts))),
        conflict_max=_round(max(conflicts)) if conflicts else None,
        conflict_max_bar=max_bar,
    )


def trajectory_probes(
    host_frames: FrameSeries,
    guest_frames: FrameSeries,
    host_bars: BarSeries,
    guest_bars: BarSeries,
    offsets: tuple[int, ...],
    pitch_shift: int,
) -> tuple[TrajectoryProbe, ...]:
    """One probe per requested offset, in the order given — nothing is
    filtered, ranked, or excluded."""
    return tuple(
        trajectory_probe(host_frames, guest_frames, host_bars, guest_bars, off, pitch_shift)
        for off in offsets
    )


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    from mashpad.research.discovery import (
        BEATS_PER_BAR,
        best_pitch_shifts,
        derive_bars,
        extract_features,
        metrical_interpretations,
        propose_shared_tempos,
    )
    from mashpad.research.joint_features import _parse_offsets, extract_frame_series

    parser = argparse.ArgumentParser(
        description="Phrase-scale trajectory probe — every offset measured, none excluded"
    )
    parser.add_argument("host", type=Path)
    parser.add_argument("guest", type=Path)
    parser.add_argument("--offsets", default="-3..26")
    parser.add_argument("--pitch-shift", default="auto")
    parser.add_argument("--mark", default="", help="display-only flags for known offsets")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    host_feat = extract_features(args.host)
    guest_feat = extract_features(args.guest)
    interp = min(
        metrical_interpretations(host_feat),
        key=lambda i: propose_shared_tempos(i.bpm, guest_feat.tracked_bpm)[0].cost,
    )
    host_bars = derive_bars(host_feat, interp.tracked_beats_per_bar)
    guest_bars = derive_bars(guest_feat, BEATS_PER_BAR)
    if args.pitch_shift == "auto":
        host_mean = tuple(
            sum(col) / len(host_bars.bar_chroma) for col in zip(*host_bars.bar_chroma, strict=True)
        )
        guest_mean = tuple(
            sum(col) / len(guest_bars.bar_chroma)
            for col in zip(*guest_bars.bar_chroma, strict=True)
        )
        pitch_shift = best_pitch_shifts(host_mean, guest_mean)[0][0]
    else:
        pitch_shift = int(args.pitch_shift)

    host_frames = extract_frame_series(args.host)
    guest_frames = extract_frame_series(args.guest)
    offsets = _parse_offsets(args.offsets)
    marked = {int(x) for x in args.mark.split(",") if x.strip()}

    probes = trajectory_probes(
        host_frames, guest_frames, host_bars, guest_bars, offsets, pitch_shift
    )

    def _f(v: float | None) -> str:
        return f"{v: .3f}" if v is not None else "     -"

    print(f"host  = {args.host.name}: {interp.note}")
    print(
        f"guest = {args.guest.name}: tracked {guest_feat.tracked_bpm:.1f} BPM; "
        f"pitch {pitch_shift:+d} st"
    )
    print("phrase-scale joint structure — measurements, not verdicts\n")
    print(
        f"{'off':>4} {'bars':>4} {'dens.agr':>8} {'dens.min':>8} {'sal.comp':>8} "
        f"{'nov.co':>7} {'hc.co':>7} {'cad.co':>7} {'fg.coll':>8} {'cf.mean':>8} "
        f"{'cf.max':>7} {'@bar':>5}"
    )
    for p in probes:
        mark = "  <-- marked" if p.offset_bars in marked else ""
        note = f"  ({p.note})" if p.note else ""
        dens = p.curves.get("onset_density")
        sal = p.curves.get("midband_salience")
        print(
            f"{p.offset_bars:>4} {p.n_bars:>4} "
            f"{_f(dens.agreement if dens else None):>8} "
            f"{_f(dens.local_corr_min if dens else None):>8} "
            f"{_f(sal.complementarity if sal else None):>8} "
            f"{_f(p.peak_cooccurrences.get('novelty')):>7} "
            f"{_f(p.peak_cooccurrences.get('harmonic_change')):>7} "
            f"{_f(p.peak_cooccurrences.get('cadence_proxy')):>7} "
            f"{_f(p.foreground_collision):>8} {_f(p.conflict_mean):>8} "
            f"{_f(p.conflict_max):>7} "
            f"{p.conflict_max_bar if p.conflict_max_bar is not None else '-':>5}{mark}{note}"
        )

    if args.json:
        payload = {
            "host": str(args.host),
            "guest": str(args.guest),
            "host_interpretation": interp.note,
            "guest_tracked_bpm": guest_feat.tracked_bpm,
            "pitch_shift_semitones": pitch_shift,
            "probes": [p.to_dict() for p in probes],
            "flat_features": {str(p.offset_bars): p.flat_features() for p in probes},
        }
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"\nwrote {args.json}")
    return 0
