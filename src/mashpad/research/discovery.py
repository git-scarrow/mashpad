"""Automatic construction discovery: two audio files in, ranked
construction hypotheses out.

This is the research-layer slice for the re-centered spike objective:
Mashpad receives two recordings and independently proposes plausible
mashup constructions — metrical interpretation, common target tempo,
pitch shift, downbeat-to-downbeat alignment, guest entry/mute windows —
with explicit evidence and uncertainty, and **no manual pins**: no label
editor, no DJ software, no hand-edited JSON in the loop. Manual
annotations (`mashpad.research.annotations`) remain optional evaluation
truth, never an input to this pipeline.

Architecture: a **pure hypothesis core** over `TrackFeatures`
(beat-granular times/strengths/chroma/energy), so every decision rule is
unit-testable with synthetic features and cannot be quietly fitted to one
song pair — plus one thin extractor, `extract_features`, that produces
`TrackFeatures` from a real file via librosa. librosa stays an OPTIONAL
extra (`tempo-librosa`), lazily imported, and this expanded use (onset
envelope, beat tracking, chroma, RMS) is **research-layer only** — the
production guardrail (tempo-candidate extraction only, nothing wired into
`analyze_track`/`mashcheck`) still stands; see the decision log entry
authorizing this scope.

Honesty rules:

- Everything emitted is a machine-generated *estimate*. Confidences are
  self-consistency heuristics, never calibrated probabilities, and
  nothing here produces or implies `MEASURED` provenance.
- Thresholds and weights below are explicit, uncalibrated policy
  defaults. The witnessed Skyfall/In the End values are ACCEPTANCE
  EVIDENCE (compare via `witness_agreement` against the committed
  construction fixture) and must never be hard-coded into the
  discovery rules.
- Known v1 limitations are declared in each hypothesis's `uncertainty`
  list rather than silently absorbed: 4/4 meter is assumed, faster-than-
  tracked (double-time) interpretations are not searched, section labels
  are not estimated (windows are bar-level), and admissibility is a
  crude chroma/energy proxy for harmonic/textural compatibility.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mashpad.models import TempoCandidate

# --- explicit, uncalibrated policy defaults ---------------------------------

BEATS_PER_BAR = 4  # 4/4 assumed; a v1 limitation declared in every hypothesis
HOST_STRETCH_WEIGHT = 3.0  # host character is the scarcer resource...
GUEST_STRETCH_WEIGHT = 1.0  # ...the conformed guest tolerates more
GRID_STEPS = (0.0, 0.05, 0.10, 0.15, 0.20)  # host-stretch steps toward the guest
MAX_INTERPRETATION_DEVIATION = 0.08  # candidate BPM must sit near tracked/f
STABLE_IBI_TOLERANCE = 0.08  # inter-beat interval within 8% of median = stable
HARMONIC_ADMISSIBLE_THRESHOLD = 0.60  # per-bar chroma cosine floor for overlap
MIN_WINDOW_BARS = 4  # an entrance needs a sustained run, not one lucky bar
PITCH_SHIFT_RANGE = range(-5, 7)  # semitone shifts searched (guest vs host)


# --- features (produced by extract_features, consumed by the pure core) ------


@dataclass(frozen=True, slots=True)
class TrackFeatures:
    """Beat-granular features of one recording.

    `tracked_bpm` is the beat tracker's working tempo; `tempo_candidates`
    carries the octave-aware interpretations (primary + half/double) from
    the sanctioned librosa tempo backend. Chroma rows are 12-dim,
    energies are RMS normalized to the track max."""

    path: str
    duration_sec: float
    tracked_bpm: float
    tempo_candidates: tuple[TempoCandidate, ...]
    beat_times: tuple[float, ...]
    beat_strengths: tuple[float, ...]
    beat_chroma: tuple[tuple[float, ...], ...]
    beat_energy: tuple[float, ...]

    def __post_init__(self) -> None:
        n = len(self.beat_times)
        if not (len(self.beat_strengths) == len(self.beat_chroma) == len(self.beat_energy) == n):
            raise ValueError("beat-level feature lists must have equal length")


# --- pure helpers -------------------------------------------------------------


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm > 0 else 0.0


def rotate_chroma(chroma: tuple[float, ...], semitones: int) -> tuple[float, ...]:
    """Rotate a 12-dim chroma vector up by `semitones` (what a +n semitone
    pitch shift does to pitch classes)."""
    n = len(chroma)
    return tuple(chroma[(i - semitones) % n] for i in range(n))


def best_pitch_shifts(
    host_chroma: tuple[float, ...], guest_chroma: tuple[float, ...]
) -> tuple[tuple[int, float], ...]:
    """Semitone shifts of the guest ranked by chroma correlation with the
    host, best first. A crude global-key alignment: the top entry is the
    hypothesis, the runner-up is reported as uncertainty context."""
    scored = [
        (shift, _cosine(host_chroma, rotate_chroma(guest_chroma, shift)))
        for shift in PITCH_SHIFT_RANGE
    ]
    return tuple(sorted(scored, key=lambda pair: -pair[1]))


def choose_downbeat_phase(beat_strengths: tuple[float, ...], group: int) -> tuple[int, float]:
    """Pick the downbeat phase (0..group-1) whose beats carry the most
    onset strength. Returns (phase, confidence) where confidence is the
    winner's share of total phase strength — a self-consistency heuristic,
    not a calibrated probability."""
    if len(beat_strengths) < group:
        return 0, 0.0
    totals = [0.0] * group
    counts = [0] * group
    for i, s in enumerate(beat_strengths):
        totals[i % group] += s
        counts[i % group] += 1
    means = [t / c if c else 0.0 for t, c in zip(totals, counts, strict=True)]
    total = sum(means)
    phase = max(range(group), key=lambda p: means[p])
    confidence = means[phase] / total if total > 0 else 0.0
    return phase, confidence


def first_stable_beat_index(beat_times: tuple[float, ...]) -> int:
    """First beat whose local inter-beat interval sits within tolerance of
    the median IBI — the tracker has settled into the prevailing meter.
    This is what lets an irregular opening gesture (a rubato brass hit, a
    pickup) fall outside the regular grid without being hand-flagged."""
    if len(beat_times) < 3:
        return 0
    ibis = [b - a for a, b in zip(beat_times, beat_times[1:], strict=False)]
    median_ibi = sorted(ibis)[len(ibis) // 2]
    for i, ibi in enumerate(ibis):
        if abs(ibi - median_ibi) <= STABLE_IBI_TOLERANCE * median_ibi:
            return i
    return 0


@dataclass(frozen=True, slots=True)
class BarSeries:
    """One track re-barred under a metrical interpretation: downbeat times
    plus per-bar aggregated chroma/energy, starting at the first stable
    downbeat."""

    first_downbeat_sec: float
    downbeat_times: tuple[float, ...]
    bar_chroma: tuple[tuple[float, ...], ...]
    bar_energy: tuple[float, ...]
    phase: int
    phase_confidence: float


def derive_bars(features: TrackFeatures, tracked_beats_per_bar: int) -> BarSeries:
    """Group tracked beats into bars of `tracked_beats_per_bar` (4 for the
    tracked tempo, 8 for its half-time interpretation, ...), choosing the
    downbeat phase by onset strength and starting at the first stable
    downbeat."""
    phase, confidence = choose_downbeat_phase(features.beat_strengths, tracked_beats_per_bar)
    stable = first_stable_beat_index(features.beat_times)
    start = stable + ((phase - stable) % tracked_beats_per_bar)

    downbeats: list[float] = []
    chroma: list[tuple[float, ...]] = []
    energy: list[float] = []
    i = start
    while i + tracked_beats_per_bar <= len(features.beat_times):
        downbeats.append(features.beat_times[i])
        rows = features.beat_chroma[i : i + tracked_beats_per_bar]
        mean = tuple(sum(col) / len(rows) for col in zip(*rows, strict=True))
        norm = math.sqrt(sum(x * x for x in mean))
        chroma.append(tuple(x / norm for x in mean) if norm > 0 else mean)
        window = features.beat_energy[i : i + tracked_beats_per_bar]
        energy.append(sum(window) / len(window))
        i += tracked_beats_per_bar
    if not downbeats:
        raise ValueError(f"{features.path}: too few beats to form one bar")
    return BarSeries(
        first_downbeat_sec=downbeats[0],
        downbeat_times=tuple(downbeats),
        bar_chroma=tuple(chroma),
        bar_energy=tuple(energy),
        phase=phase,
        phase_confidence=confidence,
    )


# --- metrical interpretations and shared tempo --------------------------------


@dataclass(frozen=True, slots=True)
class MetricalInterpretation:
    """One way to read a track's tracked beat grid: `bpm` is the metrical
    tempo, `tracked_beats_per_bar` how many tracked beats one bar spans
    (4 = as tracked, 8 = half-time reading)."""

    bpm: float
    tracked_beats_per_bar: int
    note: str


def metrical_interpretations(features: TrackFeatures) -> tuple[MetricalInterpretation, ...]:
    """Interpretations supported by the track's tempo candidates: the
    tracked reading plus any candidate near tracked/2 (half-time — bars
    span 8 tracked beats). Candidates faster than tracked are declared,
    not searched (v1 limitation: no beat subdivision)."""
    interps = [
        MetricalInterpretation(
            bpm=features.tracked_bpm,
            tracked_beats_per_bar=BEATS_PER_BAR,
            note=f"as tracked ({features.tracked_bpm:.1f} BPM)",
        )
    ]
    for candidate in features.tempo_candidates:
        ratio = features.tracked_bpm / candidate.bpm if candidate.bpm > 0 else 0.0
        if abs(ratio - 2.0) <= 2.0 * MAX_INTERPRETATION_DEVIATION:
            interps.append(
                MetricalInterpretation(
                    bpm=candidate.bpm,
                    tracked_beats_per_bar=2 * BEATS_PER_BAR,
                    note=(
                        f"half-time reading of the tracked grid "
                        f"({features.tracked_bpm:.1f} -> {candidate.bpm:.1f} BPM, "
                        f"candidate confidence {candidate.confidence:.2f})"
                    ),
                )
            )
    return tuple(interps)


@dataclass(frozen=True, slots=True)
class SharedTempoCandidate:
    grid_bpm: float
    host_ratio: float  # grid / host metrical bpm
    guest_ratio: float  # grid / guest metrical bpm
    cost: float  # role-asymmetric transformation cost, lower is better
    note: str


def propose_shared_tempos(host_bpm: float, guest_bpm: float) -> tuple[SharedTempoCandidate, ...]:
    """Common-grid candidates anchored at the host's metrical tempo,
    stepping toward the guest. Cost is deliberately role-asymmetric
    (HOST_STRETCH_WEIGHT vs GUEST_STRETCH_WEIGHT): the same percentage
    change is costed harder on the host, encoding host-character
    preservation as a *selection pressure*, not a hard rule — weights are
    uncalibrated policy defaults."""
    direction = 1.0 if guest_bpm >= host_bpm else -1.0
    candidates = []
    for step in GRID_STEPS:
        grid = host_bpm * (1.0 + direction * step)
        # never step past the guest's tempo — beyond it both sides lose
        if direction > 0:
            grid = min(grid, guest_bpm)
        else:
            grid = max(grid, guest_bpm)
        host_ratio = grid / host_bpm
        guest_ratio = grid / guest_bpm
        cost = HOST_STRETCH_WEIGHT * abs(host_ratio - 1.0) + GUEST_STRETCH_WEIGHT * abs(
            guest_ratio - 1.0
        )
        candidates.append(
            SharedTempoCandidate(
                grid_bpm=round(grid, 2),
                host_ratio=round(host_ratio, 4),
                guest_ratio=round(guest_ratio, 4),
                cost=round(cost, 4),
                note=(
                    f"host {'stretched' if abs(host_ratio - 1) > 1e-9 else 'preserved'} "
                    f"{(host_ratio - 1) * 100:+.1f}%, guest {(guest_ratio - 1) * 100:+.1f}%"
                ),
            )
        )
    unique: dict[float, SharedTempoCandidate] = {}
    for c in candidates:
        unique.setdefault(c.grid_bpm, c)
    return tuple(sorted(unique.values(), key=lambda c: c.cost))


# --- alignment and admissibility ----------------------------------------------


@dataclass(frozen=True, slots=True)
class AlignedBar:
    """Guest bar `guest_bar` (1-based from the guest's first stable
    downbeat) against the host bar at the same index from the host's
    first stable downbeat — the downbeat-to-downbeat structural anchor."""

    guest_bar: int
    host_bar: int
    harmonic_fit: float  # chroma cosine after the pitch shift, 0..1
    density: float  # min(host, guest) bar energy — both-loud masking proxy


def admissibility_profile(
    host_bars: BarSeries, guest_bars: BarSeries, pitch_shift: int
) -> tuple[AlignedBar, ...]:
    n = min(len(host_bars.bar_chroma), len(guest_bars.bar_chroma))
    profile = []
    for j in range(n):
        harmonic = _cosine(
            host_bars.bar_chroma[j], rotate_chroma(guest_bars.bar_chroma[j], pitch_shift)
        )
        density = min(host_bars.bar_energy[j], guest_bars.bar_energy[j])
        profile.append(
            AlignedBar(
                guest_bar=j + 1,
                host_bar=j + 1,
                harmonic_fit=round(harmonic, 4),
                density=round(density, 4),
            )
        )
    return tuple(profile)


@dataclass(frozen=True, slots=True)
class EntryWindow:
    start_guest_bar: int
    end_guest_bar: int
    mean_harmonic_fit: float
    mean_density: float


def find_entry_windows(profile: tuple[AlignedBar, ...]) -> tuple[EntryWindow, ...]:
    """Maximal runs of admissible aligned bars (chroma fit at or above the
    threshold, at least MIN_WINDOW_BARS long), ranked by mean harmonic
    fit. The region before the first window is the implied mute/exclusion
    window: the tracks are synchronized there but not admissible."""
    windows = []
    run: list[AlignedBar] = []
    for bar in (*profile, None):
        if bar is not None and bar.harmonic_fit >= HARMONIC_ADMISSIBLE_THRESHOLD:
            run.append(bar)
            continue
        if len(run) >= MIN_WINDOW_BARS:
            windows.append(
                EntryWindow(
                    start_guest_bar=run[0].guest_bar,
                    end_guest_bar=run[-1].guest_bar,
                    mean_harmonic_fit=round(sum(b.harmonic_fit for b in run) / len(run), 4),
                    mean_density=round(sum(b.density for b in run) / len(run), 4),
                )
            )
        run = []
    return tuple(sorted(windows, key=lambda w: -w.mean_harmonic_fit))


# --- the hypothesis ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConstructionHypothesis:
    """One machine-generated construction proposal. Everything here is an
    estimate; `evidence` says where each element came from, `uncertainty`
    says what was assumed or not searched."""

    host_path: str
    guest_path: str
    host_metrical_bpm: float
    host_metrical_note: str
    guest_metrical_bpm: float
    shared_grid_bpm: float
    host_ratio: float
    guest_ratio: float
    transformation_cost: float
    pitch_shift_semitones: int
    pitch_shift_score: float
    host_anchor_sec: float
    guest_anchor_sec: float
    host_downbeat_confidence: float
    guest_downbeat_confidence: float
    entry_windows: tuple[EntryWindow, ...]
    mute_through_guest_bar: int  # 0 = no mute needed; guest admissible from bar 1
    rank_score: float  # lower is better
    evidence: tuple[str, ...] = ()
    uncertainty: tuple[str, ...] = ()
    profile: tuple[AlignedBar, ...] = field(default=(), repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "host_path": self.host_path,
            "guest_path": self.guest_path,
            "host_metrical_bpm": self.host_metrical_bpm,
            "host_metrical_note": self.host_metrical_note,
            "guest_metrical_bpm": self.guest_metrical_bpm,
            "shared_grid_bpm": self.shared_grid_bpm,
            "host_ratio": self.host_ratio,
            "guest_ratio": self.guest_ratio,
            "transformation_cost": self.transformation_cost,
            "pitch_shift_semitones": self.pitch_shift_semitones,
            "pitch_shift_score": self.pitch_shift_score,
            "host_anchor_sec": self.host_anchor_sec,
            "guest_anchor_sec": self.guest_anchor_sec,
            "host_downbeat_confidence": self.host_downbeat_confidence,
            "guest_downbeat_confidence": self.guest_downbeat_confidence,
            "entry_windows": [
                {
                    "start_guest_bar": w.start_guest_bar,
                    "end_guest_bar": w.end_guest_bar,
                    "mean_harmonic_fit": w.mean_harmonic_fit,
                    "mean_density": w.mean_density,
                }
                for w in self.entry_windows
            ],
            "mute_through_guest_bar": self.mute_through_guest_bar,
            "rank_score": self.rank_score,
            "evidence": list(self.evidence),
            "uncertainty": list(self.uncertainty),
            "aligned_bars": [
                {
                    "guest_bar": b.guest_bar,
                    "host_bar": b.host_bar,
                    "harmonic_fit": b.harmonic_fit,
                    "density": b.density,
                }
                for b in self.profile
            ],
        }


_V1_UNCERTAINTY = (
    "meter assumed 4/4 throughout; no meter estimation",
    "downbeat phase chosen by onset-strength heuristic (confidence is a share, "
    "not a calibrated probability)",
    "faster-than-tracked (double-time) metrical interpretations not searched",
    "admissibility is a chroma/energy proxy; section labels and lyric/phrase "
    "events are not estimated",
    "harmonic threshold, window length, and stretch weights are uncalibrated policy defaults",
    "pitch shift chosen by global mean-chroma rotation, not per-section analysis",
)


def _hypotheses_for_assignment(
    host: TrackFeatures, guest: TrackFeatures
) -> list[ConstructionHypothesis]:
    guest_bpm = guest.tracked_bpm
    guest_bars = derive_bars(guest, BEATS_PER_BAR)
    hypotheses = []
    for interp in metrical_interpretations(host):
        host_bars = derive_bars(host, interp.tracked_beats_per_bar)
        host_mean = tuple(
            sum(col) / len(host_bars.bar_chroma) for col in zip(*host_bars.bar_chroma, strict=True)
        )
        guest_mean = tuple(
            sum(col) / len(guest_bars.bar_chroma)
            for col in zip(*guest_bars.bar_chroma, strict=True)
        )
        shifts = best_pitch_shifts(host_mean, guest_mean)
        (shift, shift_score), runner_up = shifts[0], shifts[1]
        profile = admissibility_profile(host_bars, guest_bars, shift)
        windows = find_entry_windows(profile)
        mute_through = windows[0].start_guest_bar - 1 if windows else len(profile)
        for grid in propose_shared_tempos(interp.bpm, guest_bpm):
            best_fit = windows[0].mean_harmonic_fit if windows else 0.0
            hypotheses.append(
                ConstructionHypothesis(
                    host_path=host.path,
                    guest_path=guest.path,
                    host_metrical_bpm=round(interp.bpm, 2),
                    host_metrical_note=interp.note,
                    guest_metrical_bpm=round(guest_bpm, 2),
                    shared_grid_bpm=grid.grid_bpm,
                    host_ratio=grid.host_ratio,
                    guest_ratio=grid.guest_ratio,
                    transformation_cost=grid.cost,
                    pitch_shift_semitones=shift,
                    pitch_shift_score=round(shift_score, 4),
                    host_anchor_sec=round(host_bars.first_downbeat_sec, 3),
                    guest_anchor_sec=round(guest_bars.first_downbeat_sec, 3),
                    host_downbeat_confidence=round(host_bars.phase_confidence, 4),
                    guest_downbeat_confidence=round(guest_bars.phase_confidence, 4),
                    entry_windows=windows,
                    mute_through_guest_bar=mute_through,
                    rank_score=round(grid.cost - 0.2 * best_fit, 4),
                    evidence=(
                        f"host metrical reading: {interp.note}",
                        f"guest tracked at {guest_bpm:.1f} BPM",
                        f"shared grid {grid.grid_bpm:.1f} BPM: {grid.note} "
                        f"(asymmetric cost {grid.cost:.3f})",
                        f"pitch shift {shift:+d} st by mean-chroma rotation "
                        f"(score {shift_score:.3f}; runner-up {runner_up[0]:+d} st "
                        f"at {runner_up[1]:.3f})",
                        "structural anchor: first stable downbeats aligned "
                        f"(host {host_bars.first_downbeat_sec:.2f}s @ phase confidence "
                        f"{host_bars.phase_confidence:.2f}, guest "
                        f"{guest_bars.first_downbeat_sec:.2f}s @ "
                        f"{guest_bars.phase_confidence:.2f})",
                        (
                            f"guest admissible from bar {windows[0].start_guest_bar} "
                            f"(muted through bar {mute_through}; window mean chroma fit "
                            f"{windows[0].mean_harmonic_fit:.2f})"
                            if windows
                            else "no admissible entry window found at this pitch shift"
                        ),
                    ),
                    uncertainty=_V1_UNCERTAINTY,
                    profile=profile,
                )
            )
    return hypotheses


def propose_constructions(
    features_a: TrackFeatures, features_b: TrackFeatures, top: int = 5
) -> tuple[ConstructionHypothesis, ...]:
    """Ranked construction hypotheses for a pair, trying both host/guest
    assignments — the role decision is part of the search, not an input.
    Rank = transformation cost minus a small bonus for a strong entry
    window (both components visible on the hypothesis)."""
    hypotheses = _hypotheses_for_assignment(features_a, features_b)
    hypotheses += _hypotheses_for_assignment(features_b, features_a)
    return tuple(sorted(hypotheses, key=lambda h: h.rank_score))[:top]


# --- acceptance evaluation against the witnessed construction ------------------


def witness_agreement(hypothesis: ConstructionHypothesis, construction) -> tuple[str, ...]:
    """Compare a machine-generated hypothesis against a witnessed
    `MashupConstruction` (acceptance evidence for one case — the witness
    values live in the fixture, never in the discovery rules). Returns
    human-readable agree/disagree lines; silence on fields the fixture
    leaves unresolved."""
    lines = []

    def check(name: str, expected: float | None, actual: float, tolerance: float) -> None:
        if expected is None:
            return
        ok = abs(actual - float(expected)) <= tolerance
        lines.append(
            f"{'AGREES' if ok else 'DIFFERS'}: {name} — witnessed {expected}, proposed {actual}"
        )

    check("host metrical BPM", _value(construction.host_bpm), hypothesis.host_metrical_bpm, 4.0)
    check("guest metrical BPM", _value(construction.guest_bpm), hypothesis.guest_metrical_bpm, 4.0)
    if construction.grid is not None:
        region = construction.grid.viable_grid_bpm_region
        if region is not None and region.bounds is not None:
            lo, hi = region.bounds
            ok = lo - 2.0 <= hypothesis.shared_grid_bpm <= hi + 2.0
            lines.append(
                f"{'AGREES' if ok else 'DIFFERS'}: shared grid — witnessed viable region "
                f"[{lo}, {hi}] BPM, proposed {hypothesis.shared_grid_bpm}"
            )
    check(
        "pitch shift (semitones)",
        _value(construction.pitch_shift_semitones),
        float(hypothesis.pitch_shift_semitones),
        0.0,
    )
    if construction.grid is not None:
        entrance = next(
            (w for w in construction.grid.windows if w.guest_audibility.value == "entering"), None
        )
        if entrance is not None and hypothesis.entry_windows:
            witnessed_start = _value(entrance.start_host_measure)
            offset = _value(construction.grid.measure_offset)
            if witnessed_start is not None and offset is not None:
                witnessed_guest_bar = float(witnessed_start) - float(offset)
                proposed = hypothesis.entry_windows[0].start_guest_bar
                ok = abs(proposed - witnessed_guest_bar) <= 2.0
                lines.append(
                    f"{'AGREES' if ok else 'DIFFERS'}: guest entry — witnessed ~guest bar "
                    f"{witnessed_guest_bar:.0f}, proposed bar {proposed}"
                )
    return tuple(lines)


def _value(gt_field) -> float | None:
    return None if gt_field.value is None else float(gt_field.value)


# --- feature extraction (the only non-pure part; librosa, lazily) --------------


def _load_librosa():
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "construction discovery needs the optional 'tempo-librosa' extra "
            "(uv sync --extra tempo-librosa); librosa is not installed"
        ) from exc
    return librosa


def extract_features(path: Path, *, sr: int = 22050) -> TrackFeatures:
    """Decode one recording and produce beat-granular `TrackFeatures`.

    Research-layer use of librosa beyond tempo candidates (onset envelope,
    beat tracking, chroma, RMS) — gated behind the same optional extra,
    never imported at module import time, never touched by production."""
    librosa = _load_librosa()
    from mashpad.analysis.tempo_backend import get_tempo_backend

    y, sr = librosa.load(str(path), sr=sr, mono=True)
    duration = float(len(y)) / sr
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo = tempo.item() if hasattr(tempo, "item") else float(tempo)  # 0-d or (1,) array
    beat_frames = list(int(f) for f in beat_frames)
    if len(beat_frames) < 2 * BEATS_PER_BAR:
        raise ValueError(f"{path}: too few beats tracked to analyze structure")
    beat_times = tuple(float(t) for t in librosa.frames_to_time(beat_frames, sr=sr))
    beat_strengths = tuple(float(onset_env[f]) for f in beat_frames)

    chroma = librosa.feature.chroma_stft(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)[0]
    rms_max = float(rms.max()) or 1.0

    beat_chroma: list[tuple[float, ...]] = []
    beat_energy: list[float] = []
    frame_bounds = [*beat_frames, chroma.shape[1]]
    for start, end in zip(frame_bounds, frame_bounds[1:], strict=False):
        end = max(end, start + 1)
        segment = chroma[:, start:end]
        mean = segment.mean(axis=1)
        norm = float((mean**2).sum() ** 0.5)
        beat_chroma.append(tuple(float(x / norm) if norm > 0 else float(x) for x in mean))
        rms_segment = rms[start : min(end, len(rms))]
        beat_energy.append(float(rms_segment.mean()) / rms_max if len(rms_segment) else 0.0)

    candidates = get_tempo_backend("librosa").estimate_candidates(Path(path))
    return TrackFeatures(
        path=str(path),
        duration_sec=duration,
        tracked_bpm=float(tempo),
        tempo_candidates=candidates,
        beat_times=beat_times,
        beat_strengths=beat_strengths,
        beat_chroma=tuple(beat_chroma),
        beat_energy=tuple(beat_energy),
    )


# --- CLI ------------------------------------------------------------------------


def _render(hypothesis: ConstructionHypothesis, index: int) -> str:
    lines = [
        f"#{index}  host={Path(hypothesis.host_path).name}  "
        f"guest={Path(hypothesis.guest_path).name}  "
        f"(rank score {hypothesis.rank_score:.3f}, lower is better)",
        f"    grid {hypothesis.shared_grid_bpm:.1f} BPM  "
        f"(host x{hypothesis.host_ratio:.3f}, guest x{hypothesis.guest_ratio:.3f})  "
        f"pitch {hypothesis.pitch_shift_semitones:+d} st",
    ]
    lines += [f"    evidence: {e}" for e in hypothesis.evidence]
    lines += [f"    uncertainty: {u}" for u in hypothesis.uncertainty]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Propose mashup construction hypotheses for two local audio files — "
            "machine-generated, no manual pins. Requires the tempo-librosa extra."
        )
    )
    parser.add_argument("track_a", type=Path)
    parser.add_argument("track_b", type=Path)
    parser.add_argument("--top", type=int, default=3, help="hypotheses to report")
    parser.add_argument("--json", type=Path, default=None, help="write full results as JSON")
    parser.add_argument(
        "--witness",
        type=Path,
        default=None,
        help="construction fixture to compare against (acceptance evidence)",
    )
    args = parser.parse_args(argv)

    features_a = extract_features(args.track_a)
    features_b = extract_features(args.track_b)
    hypotheses = propose_constructions(features_a, features_b, top=args.top)

    for i, hypothesis in enumerate(hypotheses, start=1):
        print(_render(hypothesis, i))
        print()

    if args.witness is not None and hypotheses:
        from mashpad.research.construction import load_construction

        construction = load_construction(args.witness)
        print(f"agreement of #1 with witnessed construction {construction.construction_id}:")
        report = witness_agreement(hypotheses[0], construction)
        for line in report or ("(no comparable resolved fields)",):
            print(f"  {line}")

    if args.json is not None:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([h.to_dict() for h in hypotheses], fh, indent=2)
        print(f"wrote {args.json}")
    return 0 if hypotheses else 1
