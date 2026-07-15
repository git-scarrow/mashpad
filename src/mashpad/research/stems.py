"""Experimental stem-aware joint measurements — research instrumentation
only. Never a production dependency, never a gate.

Two sources of stems, kept honestly distinct:

- **External stems** (`load_stem_frames`): user-provided files named
  `vocals.wav` / `drums.wav` / `bass.wav` / `other.wav` in a local
  directory (e.g. separated by a tool run *outside* this repo). This
  keeps real source separation out of the dependency tree entirely —
  the repo's no-DSP-dependency guardrail stands; stems are data, not a
  dependency.
- **Pseudo-stems** (`pseudo_stems`): a crude in-repo approximation using
  only librosa (already the sanctioned optional extra): HPSS gives
  `percussive` (drums-ish) and `harmonic`; low-passing the harmonic part
  gives `bass`. There is deliberately NO vocal pseudo-stem — a bad vocal
  mask would quietly corrupt the one measurement (vocal masking) stems
  exist to make honest. Keys are prefixed `pseudo_` so a pseudo-stem can
  never masquerade as a real one in stored results.

Measurements reuse the joint-feature machinery on per-stem `FrameSeries`
under the same synchronized registration mapping: vocal masking, bass
interference, transient reinforcement/flam, and competing foreground
activity. All outputs carry `stem_source` provenance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mashpad.research.discovery import BarSeries
from mashpad.research.joint_features import (
    FrameSeries,
    bar_correspondence,
    lf_interference,
    spectral_masking,
    synchronize,
    transient_features,
)

STEM_ROLES = ("vocals", "drums", "bass", "other")
PSEUDO_BASS_CUTOFF_HZ = 200.0


def load_stem_frames(stem_dir: Path) -> dict[str, FrameSeries]:
    """Frame features for whichever external stems exist in `stem_dir`
    (files named `<role>.wav`, roles from STEM_ROLES). Missing stems are
    simply absent — measurements that need them abstain."""
    from mashpad.research.joint_features import extract_frame_series

    stems = {}
    for role in STEM_ROLES:
        path = stem_dir / f"{role}.wav"
        if path.exists():
            stems[role] = extract_frame_series(path)
    return stems


def pseudo_stems(path: Path, *, sr: int = 22050) -> dict[str, FrameSeries]:
    """Crude librosa-only decomposition: `pseudo_percussive`,
    `pseudo_harmonic`, `pseudo_bass`. No vocal pseudo-stem, by design."""
    from mashpad.research.joint_features import _load_librosa, frame_series_from_audio

    librosa = _load_librosa()
    import numpy as np

    y, sr = librosa.load(str(path), sr=sr, mono=True)
    harmonic, percussive = librosa.effects.hpss(y)
    stft = librosa.stft(harmonic)
    freqs = librosa.fft_frequencies(sr=sr)
    stft[freqs > PSEUDO_BASS_CUTOFF_HZ, :] = 0.0
    bass = np.asarray(librosa.istft(stft, length=len(harmonic)))
    label = str(path)
    return {
        "pseudo_harmonic": frame_series_from_audio(harmonic, sr, f"{label}#pseudo_harmonic"),
        "pseudo_percussive": frame_series_from_audio(percussive, sr, f"{label}#pseudo_percussive"),
        "pseudo_bass": frame_series_from_audio(bass, sr, f"{label}#pseudo_bass"),
    }


def _pick(stems: dict[str, FrameSeries], *roles: str) -> tuple[str, FrameSeries] | None:
    for role in roles:
        if role in stems:
            return role, stems[role]
    return None


def stem_joint_measures(
    host_stems: dict[str, FrameSeries],
    guest_stems: dict[str, FrameSeries],
    host_bars: BarSeries,
    guest_bars: BarSeries,
    offset_bars: int,
) -> dict[str, Any]:
    """Stem-aware joint measurements for one registration. Every value
    names the stems it was computed from (`*_source`); measurements whose
    stems are missing abstain with None rather than degrade silently."""
    knots = bar_correspondence(host_bars, guest_bars, offset_bars)
    out: dict[str, Any] = {
        "offset_bars": offset_bars,
        "vocal_masking": None,
        "vocal_masking_source": None,
        "bass_interference": None,
        "bass_interference_source": None,
        "transient_sync_corr": None,
        "transient_near_lag_excess": None,
        "transient_source": None,
        "foreground_competition": None,
        "foreground_competition_source": None,
    }
    if len(knots) < 2:
        out["note"] = "insufficient overlap — not measured"
        return out

    def _sync(host_fs: FrameSeries, guest_fs: FrameSeries):
        return synchronize(host_fs, guest_fs, knots)

    # Vocal masking: guest vocal vs the host material it must cut through.
    # Requires a REAL guest vocal stem (no pseudo fallback, by design).
    guest_vocals = _pick(guest_stems, "vocals")
    host_bed = _pick(host_stems, "other", "harmonic", "pseudo_harmonic")
    if guest_vocals and host_bed:
        bed_role, bed = host_bed
        voc_role, vocals = guest_vocals
        out["vocal_masking"] = spectral_masking(bed, vocals, _sync(bed, vocals))
        out["vocal_masking_source"] = f"host:{bed_role} x guest:{voc_role}"

    host_bass = _pick(host_stems, "bass", "pseudo_bass")
    guest_bass = _pick(guest_stems, "bass", "pseudo_bass")
    if host_bass and guest_bass:
        (h_role, h_fs), (g_role, g_fs) = host_bass, guest_bass
        out["bass_interference"] = lf_interference(h_fs, g_fs, _sync(h_fs, g_fs))
        out["bass_interference_source"] = f"host:{h_role} x guest:{g_role}"

    host_drums = _pick(host_stems, "drums", "pseudo_percussive")
    guest_drums = _pick(guest_stems, "drums", "pseudo_percussive")
    if host_drums and guest_drums:
        (h_role, h_fs), (g_role, g_fs) = host_drums, guest_drums
        corr, excess = transient_features(h_fs, g_fs, _sync(h_fs, g_fs))
        out["transient_sync_corr"] = corr
        out["transient_near_lag_excess"] = excess
        out["transient_source"] = f"host:{h_role} x guest:{g_role}"

    # Competing foreground: both sides' lead material loud simultaneously.
    host_fg = _pick(host_stems, "vocals")
    guest_fg = _pick(guest_stems, "vocals")
    if host_fg and guest_fg:
        (h_role, h_fs), (g_role, g_fs) = host_fg, guest_fg
        out["foreground_competition"] = _both_loud(h_fs, g_fs, _sync(h_fs, g_fs))
        out["foreground_competition_source"] = f"host:{h_role} x guest:{g_role}"

    return out


def _both_loud(host: FrameSeries, guest: FrameSeries, sync) -> float | None:
    """Mean simultaneous loudness of two stems (each normalized to its own
    95th percentile over the overlap) — the foreground-competition core."""
    h = [host.rms[i] for i in sync.host_idx]
    g = [guest.rms[i] for i in sync.guest_idx]
    if not h:
        return None
    h_ref = sorted(h)[int(0.95 * (len(h) - 1))] or 1.0
    g_ref = sorted(g)[int(0.95 * (len(g) - 1))] or 1.0
    return sum(
        min(min(a / h_ref, 1.0), min(b / g_ref, 1.0)) for a, b in zip(h, g, strict=True)
    ) / len(h)


# --- CLI ------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    from mashpad.research.discovery import (
        BEATS_PER_BAR,
        derive_bars,
        extract_features,
        metrical_interpretations,
        propose_shared_tempos,
    )
    from mashpad.research.joint_features import _parse_offsets

    parser = argparse.ArgumentParser(
        description=(
            "Experimental stem-aware joint measurements — research "
            "instrumentation only, never a production dependency or gate"
        )
    )
    parser.add_argument("host", type=Path)
    parser.add_argument("guest", type=Path)
    parser.add_argument("--offsets", default="-3..26")
    parser.add_argument(
        "--host-stems", type=Path, default=None, help="dir of external <role>.wav stems"
    )
    parser.add_argument(
        "--guest-stems", type=Path, default=None, help="dir of external <role>.wav stems"
    )
    parser.add_argument(
        "--pseudo",
        action="store_true",
        help="add librosa HPSS pseudo-stems (crude; no vocal pseudo-stem exists)",
    )
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

    host_stems: dict[str, FrameSeries] = {}
    guest_stems: dict[str, FrameSeries] = {}
    if args.host_stems:
        host_stems.update(load_stem_frames(args.host_stems))
    if args.guest_stems:
        guest_stems.update(load_stem_frames(args.guest_stems))
    if args.pseudo:
        host_stems.update(pseudo_stems(args.host))
        guest_stems.update(pseudo_stems(args.guest))
    print(f"host stems:  {sorted(host_stems) or 'none'}")
    print(f"guest stems: {sorted(guest_stems) or 'none'}")

    results = []
    for offset in _parse_offsets(args.offsets):
        out = stem_joint_measures(host_stems, guest_stems, host_bars, guest_bars, offset)
        results.append(out)

    def _f(v):
        return f"{v: .3f}" if isinstance(v, float) else "     -"

    print(
        f"\n{'off':>4} {'voc.mask':>9} {'bass.int':>9} {'tr.corr':>8} {'tr.lagx':>8} {'fg.comp':>8}"
    )
    for r in results:
        print(
            f"{r['offset_bars']:>4} {_f(r['vocal_masking']):>9} "
            f"{_f(r['bass_interference']):>9} {_f(r['transient_sync_corr']):>8} "
            f"{_f(r['transient_near_lag_excess']):>8} {_f(r['foreground_competition']):>8}"
        )
    sources = (
        {k: v for k, v in results[0].items() if k.endswith("_source") and v} if results else {}
    )
    for name, src in sources.items():
        print(f"  {name}: {src}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {"host": str(args.host), "guest": str(args.guest), "measures": results}, indent=2
            )
        )
        print(f"wrote {args.json}")
    return 0
