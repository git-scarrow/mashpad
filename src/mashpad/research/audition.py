"""Blinded audition workflow for candidate registrations: render
identical comparison windows for every tested offset, conceal which clip
is which, collect structured listening judgments, and unseal them into
grounded labels.

This is how registration labels become **evaluation truth**: the labels
come from a human listening blind, not from the known construction, and
not from any analyzer. Ground rules encoded here:

- **Identical comparison windows.** Every clip in a session renders the
  same host bar window; only the registration offset changes which guest
  material sounds against it. Loudness normalization is identical across
  clips (per-side RMS matching, then a common peak target).
- **Blind and randomized.** Clip IDs are assigned by a seeded random
  permutation; nothing in a clip's filename or the response template
  reveals its offset. The mapping lives in a separate `key.json` the
  listener must not open until responses are saved. Multiple clips may
  be judged viable — the workflow never presumes one winner or that
  neighbors are negatives.
- **Structured responses.** Per clip: overall viability
  (yes/no/unsure), 1–5 ratings for rhythmic, harmonic, and
  phrase/section coherence and masking/density conflict, a
  low/medium/high confidence, and free notes.
- **Complete provenance.** `session.json` records sources (path +
  sha256), the exact transformation (grid mapping, stretch rates, pitch
  shift, window bars and seconds), normalization targets, seed, and
  tool versions. Unsealed labels carry the session id as their method.
- **No committed audio.** Rendered clips are copyrighted derived audio
  and live under `fixtures/local/` (gitignored). Only the workflow,
  schema, and (source-free) label records may be committed.

Pure core (planning, blinding, response validation, unsealing) +
lazy librosa/soundfile rendering, research layer only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mashpad.research.discovery import (
    BEATS_PER_BAR,
    BarSeries,
    best_pitch_shifts,
    derive_bars,
    extract_features,
    metrical_interpretations,
    propose_shared_tempos,
)

RESPONSE_DIMENSIONS = (
    "rhythmic_coherence",
    "harmonic_coherence",
    "phrase_section_coherence",
    "masking_density_conflict",
)
VIABILITY_VALUES = (True, False, "unsure")
CONFIDENCE_VALUES = ("low", "medium", "high")
RATING_MIN, RATING_MAX = 1, 5

MIX_RMS_DBFS = -20.0  # per-side RMS target before mixing (equal loudness)
PEAK_TARGET = 0.89  # common post-mix peak so no clip is louder than another


# --- blinding (pure) -----------------------------------------------------------


def blind_assignment(offsets: tuple[int, ...], seed: int) -> tuple[tuple[str, int], ...]:
    """Assign concealed clip IDs to offsets by a seeded random
    permutation. IDs are positional (`clip_a`, `clip_b`, ...) so listing
    the clips directory reveals nothing about offset order."""
    if len(set(offsets)) != len(offsets):
        raise ValueError("duplicate offsets in one session would unblind by count")
    shuffled = list(offsets)
    random.Random(seed).shuffle(shuffled)
    return tuple((f"clip_{chr(ord('a') + i)}", off) for i, off in enumerate(shuffled))


def response_template(blind_ids: tuple[str, ...]) -> dict[str, Any]:
    """The file the listener fills in. Contains only blind IDs — no
    offsets, no transformation hints."""
    return {
        "instructions": (
            "Listen blind: do NOT open key.json until this file is saved. "
            "Judge each clip on its own; multiple clips may be viable. "
            "viable: true / false / 'unsure'. Ratings 1 (bad) .. 5 (good), "
            "except masking_density_conflict: 1 (severe conflict) .. 5 (clean). "
            "confidence: low / medium / high."
        ),
        "responses": {
            blind_id: {
                "viable": None,
                **{dim: None for dim in RESPONSE_DIMENSIONS},
                "confidence": None,
                "notes": "",
            }
            for blind_id in blind_ids
        },
    }


def validate_response(entry: dict[str, Any]) -> list[str]:
    """Problems with one clip's response (empty list = valid)."""
    problems = []
    if entry.get("viable") not in VIABILITY_VALUES:
        problems.append(f"viable must be one of {VIABILITY_VALUES}, got {entry.get('viable')!r}")
    for dim in RESPONSE_DIMENSIONS:
        value = entry.get(dim)
        if value is not None and not (isinstance(value, int) and RATING_MIN <= value <= RATING_MAX):
            problems.append(f"{dim} must be an int {RATING_MIN}..{RATING_MAX} or null")
    if entry.get("confidence") not in CONFIDENCE_VALUES:
        problems.append(f"confidence must be one of {CONFIDENCE_VALUES}")
    return problems


def unseal(key: dict[str, Any], responses: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Join saved responses with the sealed key into resolved label
    records, offset order. Raises on missing/invalid responses so a
    half-filled session cannot silently become truth. The records state
    listening judgments; mapping them into the corpus taxonomy (e.g. a
    viable neighbor is a *success*, not a negative) is a human-reviewed
    edit of the corpus fixture, deliberately not automated."""
    answered = responses.get("responses", {})
    records = []
    for blind_id, meta in key["assignment"].items():
        entry = answered.get(blind_id)
        if entry is None:
            raise ValueError(f"no response for {blind_id}")
        problems = validate_response(entry)
        if problems:
            raise ValueError(f"{blind_id}: " + "; ".join(problems))
        records.append(
            {
                "offset_bars": meta["offset_bars"],
                "blind_id": blind_id,
                "viable": entry["viable"],
                **{dim: entry.get(dim) for dim in RESPONSE_DIMENSIONS},
                "confidence": entry["confidence"],
                "notes": entry.get("notes", ""),
                "method": f"blinded_audition:{key['session_id']}",
                "guest_silent_padding": meta.get("guest_silent_padding", False),
            }
        )
    return tuple(sorted(records, key=lambda r: r["offset_bars"]))


# --- rendering (librosa + soundfile, lazy, optional extra) ----------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class RenderPlan:
    """Everything needed to render one session, resolved before any audio
    work so it can be recorded as provenance."""

    session_id: str
    host_path: Path
    guest_path: Path
    offsets: tuple[int, ...]
    window_start_host_bar: int  # 0-based host bar the window opens at
    window_bars: int
    pitch_shift: int
    seed: int
    host_interpretation_note: str
    guest_tracked_bpm: float


def _window_times(bars: BarSeries, start: int, count: int) -> tuple[float, float]:
    times = bars.downbeat_times
    end_index = start + count
    if end_index < len(times):
        return times[start], times[end_index]
    gaps = sorted(b - a for a, b in zip(times, times[1:], strict=False))
    median = gaps[len(gaps) // 2] if gaps else 0.0
    return times[start], times[-1] + median * (end_index - (len(times) - 1))


def render_session(
    plan: RenderPlan, host_bars: BarSeries, guest_bars: BarSeries, out_dir: Path
) -> Path:
    """Render one blinded session to `out_dir/<session_id>/`. Returns the
    session directory. Clips are derived copyrighted audio — the caller
    must point `out_dir` somewhere gitignored (fixtures/local/...)."""
    try:
        import librosa
        import numpy as np
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ImportError(
            "rendering requires librosa+soundfile; install the optional "
            "extra: uv sync --extra tempo-librosa"
        ) from exc

    session_dir = out_dir / plan.session_id
    clips_dir = session_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    sr = 44100  # full-bandwidth render; 22.05k audibly dulls the comparison
    host_y, _ = librosa.load(str(plan.host_path), sr=sr, mono=True)
    guest_y, _ = librosa.load(str(plan.guest_path), sr=sr, mono=True)

    def _conform(seg: Any, target_dur: float, semitones: int) -> Any:
        """Stretch to `target_dur` and shift by `semitones` in ONE
        phase-vocoder pass plus one resample. Chaining time_stretch and
        pitch_shift (which is internally another stretch) runs the phase
        vocoder twice and audibly smears a full mix at large ratios — the
        v1 renders did exactly that and listeners heard it as distortion.
        Here: PV once to duration*factor, then a clean resample that
        raises pitch by `factor` while dividing duration by it."""
        factor = 2.0 ** (semitones / 12.0)
        rate = (len(seg) / sr) / (target_dur * factor)
        stretched = librosa.effects.time_stretch(seg, rate=rate)
        if semitones == 0:
            return stretched
        return librosa.resample(
            stretched, orig_sr=int(sr * factor), target_sr=sr, res_type="soxr_hq"
        )

    h_start, h_end = _window_times(host_bars, plan.window_start_host_bar, plan.window_bars)
    host_seg = host_y[int(h_start * sr) : int(h_end * sr)]
    host_dur = len(host_seg) / sr

    def _rms_normalize(y: np.ndarray) -> np.ndarray:
        rms = float(np.sqrt(np.mean(y**2))) if len(y) else 0.0
        if rms <= 0:
            return y
        target = 10 ** (MIX_RMS_DBFS / 20)
        return y * (target / rms)

    host_norm = _rms_normalize(host_seg)

    assignment = blind_assignment(plan.offsets, plan.seed)
    key_assignment: dict[str, Any] = {}
    for blind_id, offset in assignment:
        guest_start_bar = plan.window_start_host_bar - offset
        g_avail = len(guest_bars.downbeat_times)
        clipped_start = max(0, guest_start_bar)
        clipped_count = max(0, min(guest_start_bar + plan.window_bars, g_avail) - clipped_start)
        padding = clipped_count < plan.window_bars
        if clipped_count > 0:
            g_start, g_end = _window_times(guest_bars, clipped_start, clipped_count)
            guest_seg = guest_y[int(g_start * sr) : int(g_end * sr)]
            guest_target_dur = host_dur * (clipped_count / plan.window_bars)
            if guest_target_dur > 0:
                guest_seg = _conform(guest_seg, guest_target_dur, plan.pitch_shift)
            guest_seg = _rms_normalize(guest_seg)
        else:
            guest_seg = np.zeros(0, dtype=host_norm.dtype)
            g_start = g_end = None

        # Place the (possibly clipped) guest material where its bars land
        # inside the host window; silence elsewhere.
        mix = host_norm.copy()
        lead_bars = clipped_start - guest_start_bar
        insert_at = int(len(host_norm) * (lead_bars / plan.window_bars))
        end = min(insert_at + len(guest_seg), len(mix))
        if end > insert_at:
            mix[insert_at:end] = mix[insert_at:end] + guest_seg[: end - insert_at]
        peak = float(np.max(np.abs(mix))) or 1.0
        mix = mix * (PEAK_TARGET / peak)
        sf.write(str(clips_dir / f"{blind_id}.wav"), mix, sr)

        key_assignment[blind_id] = {
            "offset_bars": offset,
            "guest_window_start_bar": guest_start_bar,
            "guest_bars_rendered": clipped_count,
            "guest_silent_padding": padding,
            "guest_window_sec": [g_start, g_end],
        }

    # Unblinded host-only reference (offset-neutral, safe to hear first).
    peak = float(np.max(np.abs(host_norm))) or 1.0
    sf.write(str(session_dir / "host_only.wav"), host_norm * (PEAK_TARGET / peak), sr)

    session = {
        "schema": "mashpad.audition_session.v1",
        "session_id": plan.session_id,
        "host": {"path": str(plan.host_path), "sha256": _sha256(plan.host_path)},
        "guest": {"path": str(plan.guest_path), "sha256": _sha256(plan.guest_path)},
        "host_interpretation": plan.host_interpretation_note,
        "guest_tracked_bpm": plan.guest_tracked_bpm,
        "pitch_shift_semitones": plan.pitch_shift,
        "window_start_host_bar": plan.window_start_host_bar,
        "window_bars": plan.window_bars,
        "window_host_sec": [h_start, h_end],
        "normalization": {"per_side_rms_dbfs": MIX_RMS_DBFS, "mix_peak": PEAK_TARGET},
        "sample_rate": sr,
        "transform": (
            "guest conformed in one phase-vocoder stretch + one soxr_hq resample "
            "(v2; v1 chained two PV passes at 22.05k and audibly smeared the guest)"
        ),
        "render_quality_note": (
            "a ~30% phase-vocoder slowdown of a full mix still smears transients "
            "vs DJ-grade elastique stretching — judge the registration, and note "
            "artifact severity under masking/density + notes rather than failing "
            "a clip for codec quality alone"
        ),
        "seed": plan.seed,
        "n_clips": len(assignment),
        "offsets_tested_unordered": sorted(plan.offsets),
        "tool_versions": {"librosa": librosa.__version__},
        "note": (
            "clip -> offset mapping is sealed in key.json; do not open it "
            "until responses.json is saved"
        ),
    }
    (session_dir / "session.json").write_text(json.dumps(session, indent=2))
    (session_dir / "key.json").write_text(
        json.dumps({"session_id": plan.session_id, "assignment": key_assignment}, indent=2)
    )
    (session_dir / "responses.json").write_text(
        json.dumps(response_template(tuple(b for b, _ in assignment)), indent=2)
    )
    return session_dir


# --- CLI ------------------------------------------------------------------------


def _parse_offsets(spec: str) -> tuple[int, ...]:
    if ".." in spec:
        lo, hi = spec.split("..", 1)
        return tuple(range(int(lo), int(hi) + 1))
    return tuple(int(x) for x in spec.split(","))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Blinded registration audition workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render", help="render one blinded session")
    render.add_argument("host", type=Path)
    render.add_argument("guest", type=Path)
    render.add_argument("--session", required=True, help="session id (directory name)")
    render.add_argument("--offsets", required=True, help="'a..b' or comma list")
    render.add_argument("--window-start-bar", type=int, required=True, help="0-based host bar")
    render.add_argument("--window-bars", type=int, default=8)
    render.add_argument("--pitch-shift", default="auto")
    render.add_argument("--seed", type=int, required=True, help="blinding seed")
    render.add_argument(
        "--out",
        type=Path,
        required=True,
        help="output root (must be gitignored, e.g. fixtures/local/auditions)",
    )

    unseal_cmd = sub.add_parser("unseal", help="join responses with the sealed key")
    unseal_cmd.add_argument("session_dir", type=Path)
    unseal_cmd.add_argument(
        "--labels-out", type=Path, default=None, help="write resolved records as JSON"
    )

    args = parser.parse_args(argv)

    if args.command == "unseal":
        key = json.loads((args.session_dir / "key.json").read_text())
        responses = json.loads((args.session_dir / "responses.json").read_text())
        records = unseal(key, responses)
        for rec in records:
            print(
                f"offset {rec['offset_bars']:>3}  viable={rec['viable']!s:<6} "
                f"confidence={rec['confidence']:<6} notes={rec['notes'] or '-'}"
            )
        if args.labels_out:
            args.labels_out.write_text(json.dumps(list(records), indent=2))
            print(f"wrote {args.labels_out}")
        print(
            "\nreview before updating tests/fixtures/registration_corpus_v1.json: "
            "viable clips are additional successes, not confirmations of the "
            "known construction"
        )
        return 0

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

    plan = RenderPlan(
        session_id=args.session,
        host_path=args.host,
        guest_path=args.guest,
        offsets=_parse_offsets(args.offsets),
        window_start_host_bar=args.window_start_bar,
        window_bars=args.window_bars,
        pitch_shift=pitch_shift,
        seed=args.seed,
        host_interpretation_note=interp.note,
        guest_tracked_bpm=guest_feat.tracked_bpm,
    )
    session_dir = render_session(plan, host_bars, guest_bars, args.out)
    print(f"rendered {len(plan.offsets)} blinded clips -> {session_dir}")
    print("listen to clips/ in any order; fill responses.json; do NOT open key.json")
    print(f"then: audition unseal {session_dir}")
    return 0
