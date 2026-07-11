"""Joint-overlay registration features: measure what emerges when two
recordings actually sound together, per candidate registration.

Research objective (redirect, 2026-07-11 — see decision log): identify
measurable properties of the *synchronized combination* of two audio
streams that distinguish successful mashup registrations from
unsuccessful nearby registrations, across multiple song pairs. This
module is the minimal probe for that program. Ground rules it encodes:

- **No exclusions.** Every requested registration offset is evaluated,
  including the −1/−2/−3 loose-bar neighbors of a known-good one. The
  earlier phrase-class search gate was reverted as an overfit workaround
  (it was derived from the one witness pair's attested members).
- **Joint, not combined-independent.** Every feature here is computed
  from explicitly synchronized cross-source frame pairs (guest frames
  time-warped onto the host timeline through the bar correspondence the
  registration defines) — never by scoring each song separately and
  merging the scores afterward.
- **Witness-free.** No constant below encodes a Skyfall/In the End
  value. The witness pair is one evaluation case in the registration
  corpus (`docs/experiment-joint-registration-features.md`), nothing
  more.
- **Measurement, not judgment.** The probe reports feature values per
  registration. It draws no verdicts, feeds nothing into production
  scoring, and must not grow gates until leave-one-song-pair-out
  evaluation shows a feature generalizes.

Approximations declared: the guest's pitch shift is applied to chroma
only (band/LF envelopes are compared unshifted — a small-shift
approximation); synchronization is piecewise-linear between bar
downbeats, so sub-bar tempo drift within a bar is linearized; no audio
is rendered or mixed. Vocal intelligibility is NOT measured (requires
stem separation, which this repo deliberately does not have).

Pure core over `FrameSeries` + one thin librosa extractor
(`extract_frame_series`), same architecture and the same optional
`tempo-librosa` extra as `discovery.py`; librosa is imported lazily and
production never touches this module.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mashpad.research.discovery import (
    BEATS_PER_BAR,
    PHRASE_BARS,
    BarSeries,
    best_pitch_shifts,
    derive_bars,
    extract_features,
    metrical_interpretations,
    propose_shared_tempos,
    rotate_chroma,
)

# --- explicit, uncalibrated policy defaults ---------------------------------

LF_CUTOFF_HZ = 150.0  # "low frequency" band ceiling for interference measurement
N_BANDS = 16  # spectral band resolution for masking overlap
MAX_TRANSIENT_LAG_FRAMES = 4  # ~±93 ms at 22050 Hz / 512 hop: the flam/near-miss window
MIN_PROBE_BARS = 4  # below this the overlap is too short to characterize
DEFAULT_FEATURE_STRIDE = 4  # heavy per-frame features sampled every Nth sync frame

# Heuristic pitch-class dissonance weights by interval (semitones, symmetric:
# a pitch-class pair cannot distinguish an interval from its inversion).
# A crude stand-in for a psychoacoustic roughness model (Plomp–Levelt on
# actual partials), declared as such — values are hand-set, uncalibrated.
_INTERVAL_DISSONANCE = (0.0, 1.0, 0.65, 0.3, 0.25, 0.15, 0.8, 0.15, 0.25, 0.3, 0.65, 1.0)


# --- frame-level features (produced by extract_frame_series) -----------------


@dataclass(frozen=True, slots=True)
class FrameSeries:
    """Frame-granular features of one recording on a uniform hop.

    `onset` is the onset-strength envelope; `rms` is normalized to the
    track max; `lf` is raw low-band (<= LF_CUTOFF_HZ) magnitude;
    `bands` are per-frame band-energy profiles (N_BANDS mel bands);
    `chroma` rows are 12-dim, unit-normalized."""

    path: str
    hop_sec: float
    onset: tuple[float, ...]
    rms: tuple[float, ...]
    lf: tuple[float, ...]
    bands: tuple[tuple[float, ...], ...]
    chroma: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        n = len(self.onset)
        if not (len(self.rms) == len(self.lf) == len(self.bands) == len(self.chroma) == n):
            raise ValueError("frame-level feature lists must have equal length")


# --- synchronization ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SyncFrames:
    """Paired frame indices under one registration: host frame i sounds
    simultaneously with guest frame `guest_idx[k]` when `host_idx[k] == i`
    on the shared grid. `bar_index` is the 0-based guest bar each pair
    falls in."""

    host_idx: tuple[int, ...]
    guest_idx: tuple[int, ...]
    bar_index: tuple[int, ...]


def bar_correspondence(
    host_bars: BarSeries, guest_bars: BarSeries, offset_bars: int
) -> tuple[tuple[float, float, int], ...]:
    """(host_downbeat_sec, guest_downbeat_sec, guest_bar_index) knots for
    the registration that puts guest bar j at host bar j + offset_bars.
    Negative offsets (guest starting before the host anchor) clip to the
    overlapping bars — they are evaluated, never rejected out of hand."""
    knots = []
    for j in range(len(guest_bars.downbeat_times)):
        h = j + offset_bars
        if 0 <= h < len(host_bars.downbeat_times):
            knots.append((host_bars.downbeat_times[h], guest_bars.downbeat_times[j], j))
    return tuple(knots)


def _median_gap(times: tuple[float, ...]) -> float:
    gaps = sorted(b - a for a, b in zip(times, times[1:], strict=False))
    return gaps[len(gaps) // 2] if gaps else 0.0


def synchronize(
    host: FrameSeries,
    guest: FrameSeries,
    correspondence: tuple[tuple[float, float, int], ...],
) -> SyncFrames:
    """Pair guest frames with host frames by piecewise-linear time warp
    between corresponding bar downbeats (extended one median bar past the
    last knot so the final bar is not dropped)."""
    if len(correspondence) < 2:
        return SyncFrames((), (), ())
    knots = list(correspondence)
    host_end = knots[-1][0] + _median_gap(tuple(k[0] for k in knots))
    guest_end = knots[-1][1] + _median_gap(tuple(k[1] for k in knots))
    if host_end > knots[-1][0] and guest_end > knots[-1][1]:
        knots.append((host_end, guest_end, knots[-1][2]))

    host_idx: list[int] = []
    guest_idx: list[int] = []
    bar_index: list[int] = []
    seg = 0
    i = math.ceil(knots[0][0] / host.hop_sec)
    last = min(math.floor(knots[-1][0] / host.hop_sec), len(host.onset) - 1)
    while i <= last:
        t_h = i * host.hop_sec
        while seg + 2 < len(knots) and t_h >= knots[seg + 1][0]:
            seg += 1
        h0, g0, bar = knots[seg]
        h1, g1, _ = knots[seg + 1]
        frac = (t_h - h0) / (h1 - h0) if h1 > h0 else 0.0
        t_g = g0 + frac * (g1 - g0)
        gi = round(t_g / guest.hop_sec)
        if 0 <= gi < len(guest.onset):
            host_idx.append(i)
            guest_idx.append(gi)
            bar_index.append(bar if t_h < knots[seg + 1][0] else knots[seg + 1][2])
        i += 1
    return SyncFrames(tuple(host_idx), tuple(guest_idx), tuple(bar_index))


# --- statistics helpers -------------------------------------------------------


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx <= 0.0 or sy <= 0.0:
        return None  # a constant series has no correlation, not a zero one
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return cov / math.sqrt(sx * sy)


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm > 0 else 0.0


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(int(q * len(ordered)), len(ordered) - 1)]


# --- the joint features -------------------------------------------------------


def transient_features(
    host: FrameSeries, guest: FrameSeries, sync: SyncFrames
) -> tuple[float | None, float | None]:
    """(sync_corr, near_lag_excess): correlation of the two onset-strength
    envelopes at lag 0 on the shared timeline, and how much more correlated
    they become at a small nonzero lag (±1..MAX_TRANSIENT_LAG_FRAMES).
    Positive excess = transients systematically near-miss (flamming /
    doubled attacks) rather than land together; negative or ~0 = the lag-0
    registration is at least as good as its close neighbors."""
    g_on = [guest.onset[gi] for gi in sync.guest_idx]
    h_on = [host.onset[hi] for hi in sync.host_idx]
    corr0 = _pearson(h_on, g_on)
    if corr0 is None:
        return None, None
    best_off = None
    for lag in range(1, MAX_TRANSIENT_LAG_FRAMES + 1):
        for signed in (lag, -lag):
            pairs = [
                (host.onset[hi + signed], g)
                for hi, g in zip(sync.host_idx, g_on, strict=True)
                if 0 <= hi + signed < len(host.onset)
            ]
            r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
            if r is not None and (best_off is None or r > best_off):
                best_off = r
    return corr0, (best_off - corr0) if best_off is not None else None


def lf_interference(host: FrameSeries, guest: FrameSeries, sync: SyncFrames) -> float | None:
    """Mean simultaneous low-frequency loudness: each side's LF envelope
    is normalized to its own 95th percentile over the overlapped span,
    clipped to [0, 1], and the per-frame minimum is averaged. High values
    mean both sources occupy the bass at the same time (mud/interference
    pressure); low values mean the low end alternates or one side owns it."""
    h_lf = [host.lf[hi] for hi in sync.host_idx]
    g_lf = [guest.lf[gi] for gi in sync.guest_idx]
    if not h_lf:
        return None
    h_ref = _percentile(h_lf, 0.95) or 1.0
    g_ref = _percentile(g_lf, 0.95) or 1.0
    return sum(
        min(min(h / h_ref, 1.0), min(g / g_ref, 1.0)) for h, g in zip(h_lf, g_lf, strict=True)
    ) / len(h_lf)


def spectral_masking(
    host: FrameSeries,
    guest: FrameSeries,
    sync: SyncFrames,
    stride: int = DEFAULT_FEATURE_STRIDE,
) -> float | None:
    """Loudness-weighted mean cosine overlap of the two band-energy
    profiles at synchronized frames. High = the sources fight for the
    same spectral bands when both are loud; low = they occupy complementary
    regions. Reported as a measurement — whether overlap helps (blend) or
    hurts (masking) a given technique family is exactly what the corpus
    evaluation must decide, not this function."""
    num = 0.0
    den = 0.0
    for k in range(0, len(sync.host_idx), stride):
        hi, gi = sync.host_idx[k], sync.guest_idx[k]
        w = host.rms[hi] * guest.rms[gi]
        if w <= 0.0:
            continue
        num += w * _cosine(host.bands[hi], guest.bands[gi])
        den += w
    return num / den if den > 0 else None


def harmonic_roughness(
    host: FrameSeries,
    guest: FrameSeries,
    sync: SyncFrames,
    pitch_shift: int,
    stride: int = DEFAULT_FEATURE_STRIDE,
) -> float | None:
    """Loudness-weighted mean pitch-class dissonance between the two
    chroma distributions at synchronized frames, guest rotated by the
    registration's pitch shift. Kernel weights are the declared heuristic
    `_INTERVAL_DISSONANCE`, not a calibrated psychoacoustic model."""
    num = 0.0
    den = 0.0
    for k in range(0, len(sync.host_idx), stride):
        hi, gi = sync.host_idx[k], sync.guest_idx[k]
        w = host.rms[hi] * guest.rms[gi]
        if w <= 0.0:
            continue
        h = host.chroma[hi]
        g = rotate_chroma(guest.chroma[gi], pitch_shift)
        h_sum, g_sum = sum(h), sum(g)
        if h_sum <= 0.0 or g_sum <= 0.0:
            continue
        rough = sum(
            h[i] * g[j] * _INTERVAL_DISSONANCE[(i - j) % 12] for i in range(12) for j in range(12)
        ) / (h_sum * g_sum)
        num += w * rough
        den += w
    return num / den if den > 0 else None


def _bar_means(values: list[float], bars: tuple[int, ...]) -> list[float]:
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for v, b in zip(values, bars, strict=True):
        sums[b] = sums.get(b, 0.0) + v
        counts[b] = counts.get(b, 0) + 1
    return [sums[b] / counts[b] for b in sorted(sums)]


def bar_complementarity(
    host: FrameSeries, guest: FrameSeries, sync: SyncFrames
) -> tuple[float | None, float | None]:
    """(bar_energy_corr, bar_density_corr): Pearson correlation across
    aligned bars of the two sides' per-bar mean RMS and per-bar mean onset
    strength. Negative = complementary (one recedes where the other
    pushes); positive = they surge together. Direction of merit is a
    corpus question, not assumed here."""
    h_rms = _bar_means([host.rms[i] for i in sync.host_idx], sync.bar_index)
    g_rms = _bar_means([guest.rms[i] for i in sync.guest_idx], sync.bar_index)
    h_on = _bar_means([host.onset[i] for i in sync.host_idx], sync.bar_index)
    g_on = _bar_means([guest.onset[i] for i in sync.guest_idx], sync.bar_index)
    return _pearson(h_rms, g_rms), _pearson(h_on, g_on)


# --- the probe ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RegistrationProbe:
    """Joint-feature measurements for one registration. All values are
    measurements of the synchronized combination — no verdict, no rank."""

    offset_bars: int
    phrase_class_residue: int  # offset mod PHRASE_BARS — descriptive metadata only
    n_aligned_bars: int
    n_sync_frames: int
    transient_sync_corr: float | None
    transient_near_lag_excess: float | None
    lf_interference: float | None
    spectral_masking: float | None
    harmonic_roughness: float | None
    bar_energy_corr: float | None
    bar_density_corr: float | None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset_bars": self.offset_bars,
            "phrase_class_residue": self.phrase_class_residue,
            "n_aligned_bars": self.n_aligned_bars,
            "n_sync_frames": self.n_sync_frames,
            "transient_sync_corr": self.transient_sync_corr,
            "transient_near_lag_excess": self.transient_near_lag_excess,
            "lf_interference": self.lf_interference,
            "spectral_masking": self.spectral_masking,
            "harmonic_roughness": self.harmonic_roughness,
            "bar_energy_corr": self.bar_energy_corr,
            "bar_density_corr": self.bar_density_corr,
            "note": self.note,
        }


def probe_registration(
    host_frames: FrameSeries,
    guest_frames: FrameSeries,
    host_bars: BarSeries,
    guest_bars: BarSeries,
    offset_bars: int,
    pitch_shift: int,
    stride: int = DEFAULT_FEATURE_STRIDE,
) -> RegistrationProbe:
    """Measure the joint features of one registration. Registrations with
    too little overlap are reported with a note, never silently dropped."""
    knots = bar_correspondence(host_bars, guest_bars, offset_bars)
    residue = offset_bars % PHRASE_BARS
    if len(knots) < MIN_PROBE_BARS:
        return RegistrationProbe(
            offset_bars=offset_bars,
            phrase_class_residue=residue,
            n_aligned_bars=len(knots),
            n_sync_frames=0,
            transient_sync_corr=None,
            transient_near_lag_excess=None,
            lf_interference=None,
            spectral_masking=None,
            harmonic_roughness=None,
            bar_energy_corr=None,
            bar_density_corr=None,
            note=f"insufficient overlap ({len(knots)} bars < {MIN_PROBE_BARS}) — not measured",
        )
    sync = synchronize(host_frames, guest_frames, knots)
    corr0, excess = transient_features(host_frames, guest_frames, sync)
    energy_corr, density_corr = bar_complementarity(host_frames, guest_frames, sync)
    r = 4  # display rounding only
    return RegistrationProbe(
        offset_bars=offset_bars,
        phrase_class_residue=residue,
        n_aligned_bars=len(knots),
        n_sync_frames=len(sync.host_idx),
        transient_sync_corr=round(corr0, r) if corr0 is not None else None,
        transient_near_lag_excess=round(excess, r) if excess is not None else None,
        lf_interference=(
            round(lf, r)
            if (lf := lf_interference(host_frames, guest_frames, sync)) is not None
            else None
        ),
        spectral_masking=(
            round(sm, r)
            if (sm := spectral_masking(host_frames, guest_frames, sync, stride)) is not None
            else None
        ),
        harmonic_roughness=(
            round(hr, r)
            if (hr := harmonic_roughness(host_frames, guest_frames, sync, pitch_shift, stride))
            is not None
            else None
        ),
        bar_energy_corr=round(energy_corr, r) if energy_corr is not None else None,
        bar_density_corr=round(density_corr, r) if density_corr is not None else None,
    )


def probe_registrations(
    host_frames: FrameSeries,
    guest_frames: FrameSeries,
    host_bars: BarSeries,
    guest_bars: BarSeries,
    offsets: tuple[int, ...],
    pitch_shift: int,
    stride: int = DEFAULT_FEATURE_STRIDE,
) -> tuple[RegistrationProbe, ...]:
    """Probe every requested offset. One probe per offset, in the order
    given — nothing is filtered, ranked, or excluded."""
    return tuple(
        probe_registration(
            host_frames, guest_frames, host_bars, guest_bars, off, pitch_shift, stride
        )
        for off in offsets
    )


# --- extraction (librosa, lazy, optional extra) --------------------------------


def _load_librosa():
    try:
        import librosa
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ImportError(
            "the joint-feature probe requires librosa; install the optional "
            "extra: uv sync --extra tempo-librosa"
        ) from exc
    return librosa


def extract_frame_series(path: Path, *, sr: int = 22050) -> FrameSeries:
    """Decode one recording into frame-granular `FrameSeries`.

    Research-layer librosa use, same optional `tempo-librosa` extra and
    lazy-import discipline as `discovery.extract_features`."""
    librosa = _load_librosa()
    y, sr = librosa.load(str(path), sr=sr, mono=True)
    return frame_series_from_audio(y, sr, str(path))


def frame_series_from_audio(y: Any, sr: int, label: str) -> FrameSeries:
    """Frame features from an already-decoded mono signal (used for whole
    recordings and for stem/pseudo-stem signals alike)."""
    librosa = _load_librosa()
    hop = 512
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    stft = abs(librosa.stft(y, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr)
    lf = stft[freqs <= LF_CUTOFF_HZ].sum(axis=0)
    mel = librosa.feature.melspectrogram(y=y, sr=sr, hop_length=hop, n_mels=N_BANDS)
    chroma = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=hop)

    n = min(len(onset), len(rms), len(lf), mel.shape[1], chroma.shape[1])
    rms_max = float(rms[:n].max()) or 1.0
    chroma_rows = []
    for k in range(n):
        col = chroma[:, k]
        norm = float((col**2).sum() ** 0.5)
        chroma_rows.append(tuple(float(x / norm) if norm > 0 else float(x) for x in col))
    return FrameSeries(
        path=label,
        hop_sec=hop / sr,
        onset=tuple(float(x) for x in onset[:n]),
        rms=tuple(float(x) / rms_max for x in rms[:n]),
        lf=tuple(float(x) for x in lf[:n]),
        bands=tuple(tuple(float(x) for x in mel[:, k]) for k in range(n)),
        chroma=tuple(chroma_rows),
    )


# --- CLI ------------------------------------------------------------------------


def _parse_offsets(spec: str) -> tuple[int, ...]:
    """Accept 'a..b' (inclusive range) or a comma-separated list."""
    if ".." in spec:
        lo, hi = spec.split("..", 1)
        return tuple(range(int(lo), int(hi) + 1))
    return tuple(int(x) for x in spec.split(","))


def _fmt(value: float | None) -> str:
    return f"{value: .3f}" if value is not None else "     -"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure joint-overlay features for every candidate registration "
            "of guest against host — no offset is excluded."
        )
    )
    parser.add_argument("host", type=Path, help="host recording (structural foundation)")
    parser.add_argument("guest", type=Path, help="guest recording (conformed layer)")
    parser.add_argument(
        "--offsets",
        default="-3..26",
        help="offsets in host bars: 'a..b' inclusive or comma list (default -3..26)",
    )
    parser.add_argument(
        "--pitch-shift",
        default="auto",
        help="guest pitch shift in semitones, or 'auto' (mean-chroma rotation)",
    )
    parser.add_argument(
        "--mark",
        default="",
        help="comma list of offsets to flag in the table (display only, e.g. known witnesses)",
    )
    parser.add_argument("--stride", type=int, default=DEFAULT_FEATURE_STRIDE)
    parser.add_argument("--json", type=Path, default=None, help="write probes as JSON")
    args = parser.parse_args(argv)

    host_feat = extract_features(args.host)
    guest_feat = extract_features(args.guest)

    # Host metrical interpretation: same role-asymmetric selection pressure
    # discovery uses (pick the reading whose best shared grid costs least).
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

    probes = probe_registrations(
        host_frames, guest_frames, host_bars, guest_bars, offsets, pitch_shift, args.stride
    )

    print(f"host  = {args.host.name}: {interp.note}")
    print(f"guest = {args.guest.name}: tracked {guest_feat.tracked_bpm:.1f} BPM")
    print(f"guest pitch shift {pitch_shift:+d} st; feature stride {args.stride}")
    print(
        "every requested offset measured — none excluded; values are joint "
        "measurements, not verdicts\n"
    )
    header = (
        f"{'off':>4} {'cls':>3} {'bars':>4} {'t_corr':>7} {'t_lagx':>7} "
        f"{'lf_int':>7} {'mask':>7} {'rough':>7} {'e_corr':>7} {'d_corr':>7}"
    )
    print(header)
    for p in probes:
        mark = "  <-- marked" if p.offset_bars in marked else ""
        note = f"  ({p.note})" if p.note else ""
        print(
            f"{p.offset_bars:>4} {p.phrase_class_residue:>3} {p.n_aligned_bars:>4} "
            f"{_fmt(p.transient_sync_corr)} {_fmt(p.transient_near_lag_excess)} "
            f"{_fmt(p.lf_interference)} {_fmt(p.spectral_masking)} "
            f"{_fmt(p.harmonic_roughness)} {_fmt(p.bar_energy_corr)} "
            f"{_fmt(p.bar_density_corr)}{mark}{note}"
        )

    if args.json:
        payload = {
            "host": str(args.host),
            "guest": str(args.guest),
            "host_interpretation": interp.note,
            "guest_tracked_bpm": guest_feat.tracked_bpm,
            "pitch_shift_semitones": pitch_shift,
            "stride": args.stride,
            "probes": [p.to_dict() for p in probes],
        }
        args.json.write_text(json.dumps(payload, indent=2))
        print(f"\nwrote {args.json}")
    return 0
