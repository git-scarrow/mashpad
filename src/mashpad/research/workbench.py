"""Local audition workbench: a minimal web UI over the blinded
audition-session format, so conducting a session means listening and
tapping — not browsing clip files and hand-editing responses.json.

Design constraints (all deliberate):

- **Local-only, dependency-light.** Python stdlib `http.server` only —
  no Flask, no accounts, no auth, no cloud persistence, no production
  deployment. Bind 127.0.0.1 by default; `--lan` binds 0.0.0.0 so a
  phone on the local network can run the session.
- **The blind holds.** The server never reads `key.json` before
  finalization, refuses to serve it (or any path outside the session's
  clips), and no API payload contains an offset until the session is
  finalized. The UI shows blinded clip IDs and completion counts only.
- **Autosave is atomic.** Every response change is POSTed and written
  via temp-file + `os.replace` under a lock, so a killed process never
  leaves a corrupt `responses.json`.
- **Finalization is gated and separated.** Finalize refuses while any
  clip's response is incomplete (the same validation `unseal` enforces).
  On success it writes the decoded records to `labels.json` and the
  refreshed strict ranking report to `ranking_refreshed.json` — the
  sealed artifacts (`key.json`, `responses.json`) stay untouched — and
  only then does the UI display the by-offset comparison.
- **Labels stay human-grounded.** The refreshed ranking treats
  viable=true as `success`, viable=false as `near_offset_negative`
  (both annotated via the blinded session), and viable="unsure" as
  unresolved (excluded). Updating the committed corpus fixture remains
  a manual, reviewed step.

Research layer only: nothing here touches production scoring, ranking,
search gates, or feature definitions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mashpad.research.audition import (
    RESPONSE_DIMENSIONS,
    unseal,
    validate_response,
)
from mashpad.research.evaluation import (
    LabeledCandidate,
    features_from_artifacts,
    within_pair_report,
)

CLIP_ID_RE = re.compile(r"^clip_[a-z]$")
SEALED_FILES = ("key.json",)  # never served, never read pre-finalization
LABELS_FILE = "labels.json"
RANKING_FILE = "ranking_refreshed.json"


class IncompleteSessionError(Exception):
    """Finalization refused: required responses are missing/invalid."""


class UnknownSessionError(Exception):
    pass


@dataclass
class AuditionWorkbench:
    """The workbench core: session state, atomic autosave, gated
    finalization. HTTP handling is a thin layer over this so every
    behavior is testable without sockets."""

    session_dirs: tuple[Path, ...]
    trajectories: Path | None = None
    span: Path | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.sessions: dict[str, Path] = {}
        for d in self.session_dirs:
            d = Path(d)
            if not (d / "responses.json").exists():
                raise FileNotFoundError(f"{d}: not an audition session (no responses.json)")
            self.sessions[d.name] = d

    # -- session access ---------------------------------------------------------

    def _dir(self, name: str) -> Path:
        if name not in self.sessions:
            raise UnknownSessionError(name)
        return self.sessions[name]

    def _responses(self, name: str) -> dict[str, Any]:
        return json.loads((self._dir(name) / "responses.json").read_text())

    def clip_ids(self, name: str) -> tuple[str, ...]:
        return tuple(self._responses(name)["responses"].keys())

    def _complete_ids(self, name: str) -> tuple[str, ...]:
        return tuple(
            blind_id
            for blind_id, entry in self._responses(name)["responses"].items()
            if not validate_response(entry)
        )

    def is_finalized(self, name: str) -> bool:
        return (self._dir(name) / LABELS_FILE).exists()

    def sessions_summary(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "n_clips": len(self.clip_ids(name)),
                "n_complete": len(self._complete_ids(name)),
                "finalized": self.is_finalized(name),
            }
            for name in sorted(self.sessions)
        ]

    def state(self, name: str) -> dict[str, Any]:
        """Everything the UI needs — and no offsets until finalized."""
        payload = self._responses(name)
        session_meta = json.loads((self._dir(name) / "session.json").read_text())
        state = {
            "name": name,
            "instructions": payload.get("instructions", ""),
            "clip_ids": list(payload["responses"].keys()),
            "responses": payload["responses"],
            "complete_ids": list(self._complete_ids(name)),
            "n_clips": len(payload["responses"]),
            "n_complete": len(self._complete_ids(name)),
            "finalized": self.is_finalized(name),
            "window_bars": session_meta.get("window_bars"),
            "pitch_shift_semitones": session_meta.get("pitch_shift_semitones"),
            "dimensions": list(RESPONSE_DIMENSIONS),
        }
        if state["finalized"]:
            state["results"] = self.results(name)
        return state

    # -- autosave ---------------------------------------------------------------

    @staticmethod
    def _atomic_write(path: Path, payload: Any) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(tmp, path)

    def save_response(self, name: str, blind_id: str, entry: dict[str, Any]) -> dict[str, Any]:
        """Merge one clip's (possibly partial) response and persist
        atomically. Partial entries are saved — completeness is enforced
        at finalization, not while listening."""
        if self.is_finalized(name):
            raise IncompleteSessionError("session already finalized — responses are frozen")
        with self._lock:
            payload = self._responses(name)
            if blind_id not in payload["responses"]:
                raise KeyError(f"unknown clip {blind_id!r}")
            allowed = {"viable", "confidence", "notes", *RESPONSE_DIMENSIONS}
            unknown = set(entry) - allowed
            if unknown:
                raise KeyError(f"unknown response fields: {sorted(unknown)}")
            payload["responses"][blind_id].update(entry)
            self._atomic_write(self._dir(name) / "responses.json", payload)
            saved = payload["responses"][blind_id]
        return {
            "saved": saved,
            "problems": validate_response(saved),
            "n_complete": len(self._complete_ids(name)),
        }

    # -- finalization -----------------------------------------------------------

    def finalize(self, name: str) -> dict[str, Any]:
        """Unseal via the existing audition logic. Refuses while any clip
        is incomplete. Sealed artifacts stay in place; decoded artifacts
        are written separately."""
        with self._lock:
            if self.is_finalized(name):
                return self.results(name)
            payload = self._responses(name)
            problems = {
                blind_id: validate_response(entry)
                for blind_id, entry in payload["responses"].items()
            }
            incomplete = {b: p for b, p in problems.items() if p}
            if incomplete:
                raise IncompleteSessionError(
                    "; ".join(f"{b}: {'; '.join(p)}" for b, p in sorted(incomplete.items()))
                )
            key = json.loads((self._dir(name) / "key.json").read_text())
            records = unseal(key, payload)
            ranking = self._ranking_report(records)
            self._atomic_write(self._dir(name) / LABELS_FILE, list(records))
            self._atomic_write(self._dir(name) / RANKING_FILE, ranking)
        return self.results(name)

    def _ranking_report(self, records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
        """Refreshed strict ranking from the just-grounded labels:
        viable -> success, not viable -> near_offset_negative (annotated
        via blinded audition), unsure -> excluded. Needs probe feature
        artifacts; abstains with a note when they are missing."""
        features = features_from_artifacts(self.trajectories, self.span)
        if not features:
            return {
                "abstention_report": (
                    "no probe feature artifacts configured "
                    "(--trajectories/--span) — labels grounded, ranking skipped"
                ),
                "features": [],
            }
        candidates = []
        for rec in records:
            if rec["viable"] == "unsure":
                continue  # unresolved, not a negative
            if rec["offset_bars"] not in features:
                continue
            candidates.append(
                LabeledCandidate(
                    offset_bars=rec["offset_bars"],
                    label="success" if rec["viable"] is True else "near_offset_negative",
                    state="annotated",
                    features=features[rec["offset_bars"]],
                )
            )
        report = within_pair_report(tuple(candidates))
        report["label_source"] = "blinded audition (this session only)"
        return report

    def results(self, name: str) -> dict[str, Any]:
        directory = self._dir(name)
        if not (directory / LABELS_FILE).exists():
            raise IncompleteSessionError("session not finalized")
        return {
            "records": json.loads((directory / LABELS_FILE).read_text()),
            "ranking": json.loads((directory / RANKING_FILE).read_text()),
        }

    # -- audio ------------------------------------------------------------------

    def clip_path(self, name: str, clip_id: str) -> Path:
        """Resolve a clip strictly by validated ID — no path components
        from the client ever touch the filesystem."""
        if not CLIP_ID_RE.match(clip_id):
            raise KeyError(f"invalid clip id {clip_id!r}")
        if clip_id not in self.clip_ids(name):
            raise KeyError(f"unknown clip {clip_id!r}")
        return self._dir(name) / "clips" / f"{clip_id}.wav"


# --- HTTP layer -----------------------------------------------------------------


def _make_handler(app: AuditionWorkbench) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            pass

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _refuse_sealed(self) -> bool:
            lowered = self.path.lower()
            if any(sealed in lowered for sealed in SEALED_FILES) or ".." in lowered:
                self._json(HTTPStatus.FORBIDDEN, {"error": "sealed artifact — not served"})
                return True
            return False

        def do_GET(self) -> None:  # noqa: N802 (http.server API)
            if self._refuse_sealed():
                return
            path, _, query = self.path.partition("?")
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            try:
                if path == "/":
                    body = PAGE.encode()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/sessions":
                    self._json(HTTPStatus.OK, {"sessions": app.sessions_summary()})
                elif path == "/api/state":
                    self._json(HTTPStatus.OK, app.state(params["session"]))
                elif path.startswith("/audio/"):
                    _, _, name, filename = path.split("/", 3)
                    self._serve_audio(name, filename.removesuffix(".wav"))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (UnknownSessionError, KeyError) as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except IncompleteSessionError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})

        def _serve_audio(self, name: str, clip_id: str) -> None:
            data = app.clip_path(name, clip_id).read_bytes()
            start, end = 0, len(data) - 1
            ranged = self.headers.get("Range")
            if ranged and ranged.startswith("bytes="):
                spec = ranged[len("bytes=") :].split("-")
                if spec[0]:
                    start = int(spec[0])
                if len(spec) > 1 and spec[1]:
                    end = min(int(spec[1]), end)
            chunk = data[start : end + 1]
            status = HTTPStatus.PARTIAL_CONTENT if ranged else HTTPStatus.OK
            self.send_response(status)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Accept-Ranges", "bytes")
            if ranged:
                self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)

        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            if self._refuse_sealed():
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
                return
            try:
                if self.path == "/api/response":
                    result = app.save_response(body["session"], body["blind_id"], body["entry"])
                    self._json(HTTPStatus.OK, result)
                elif self.path == "/api/finalize":
                    self._json(HTTPStatus.OK, app.finalize(body["session"]))
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except IncompleteSessionError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": f"incomplete session: {exc}"})
            except (UnknownSessionError, KeyError) as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})

    return Handler


def serve(app: AuditionWorkbench, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _make_handler(app))
    return server


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 80))  # no packets sent; picks the LAN interface
            return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local blinded-audition workbench (research)")
    parser.add_argument("sessions", type=Path, nargs="+", help="audition session directories")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--lan",
        action="store_true",
        help="bind 0.0.0.0 so a phone on the local network can audition (still local-only)",
    )
    parser.add_argument(
        "--trajectories", type=Path, default=None, help="trajectory probe JSON for the ranking"
    )
    parser.add_argument("--span", type=Path, default=None, help="span probe JSON for the ranking")
    args = parser.parse_args(argv)

    app = AuditionWorkbench(
        session_dirs=tuple(args.sessions), trajectories=args.trajectories, span=args.span
    )
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    server = serve(app, host, args.port)
    print(f"audition workbench: {len(app.sessions)} session(s): {', '.join(sorted(app.sessions))}")
    print(f"  local:  http://127.0.0.1:{args.port}/")
    if args.lan:
        print(f"  phone:  http://{_lan_ip()}:{args.port}/  (same Wi-Fi)")
    print("key.json stays sealed; finalize from the UI when every clip is answered")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
    return 0


# --- the UI (single embedded page; no external assets) ---------------------------

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>Audition Workbench</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; font-family: -apple-system, system-ui, sans-serif; }
  body { margin: 0 auto; max-width: 640px; padding: 12px; }
  h1 { font-size: 1.1rem; } h2 { font-size: 1rem; }
  button { font-size: 1rem; padding: 10px 14px; margin: 3px; border-radius: 8px;
           border: 1px solid #8884; background: #8881; cursor: pointer; min-width: 44px; }
  button.on { background: #2a7; color: #fff; border-color: #2a7; }
  button.warn.on { background: #c55; border-color: #c55; }
  button.unsure.on { background: #b90; border-color: #b90; }
  button:disabled { opacity: .4; cursor: default; }
  .row { margin: 10px 0; }
  .label { font-size: .85rem; opacity: .8; margin-bottom: 2px; }
  .transport button { font-size: 1.2rem; }
  #progress { height: 8px; background: #8883; border-radius: 4px; overflow: hidden; }
  #progressbar { height: 100%; background: #2a7; width: 0; transition: width .2s; }
  textarea { width: 100%; min-height: 56px; font-size: 1rem; border-radius: 8px;
             border: 1px solid #8884; padding: 8px; background: transparent; color: inherit; }
  table { border-collapse: collapse; width: 100%; font-size: .82rem; }
  th, td { border: 1px solid #8884; padding: 4px 6px; text-align: center; }
  .muted { opacity: .65; font-size: .8rem; }
  .save { font-size: .75rem; opacity: .6; height: 1em; }
  .clipnav { display: flex; align-items: center; justify-content: space-between; }
  .keys { font-size: .72rem; opacity: .55; margin-top: 14px; }
  #finalize { width: 100%; font-weight: 600; }
  .card { border: 1px solid #8883; border-radius: 10px; padding: 10px 12px; margin: 8px 0; }
</style>
</head>
<body>
<h1>Blinded audition workbench</h1>
<div id="app">loading…</div>
<script>
"use strict";
let S = null;          // current session state
let idx = 0;           // current clip index
let audio = new Audio(), prevAudio = new Audio();
let comparing = false;
let saveTimer = null;

const $ = (h) => { const d = document.createElement("div"); d.innerHTML = h; return d.firstElementChild; };
const api = async (path, body) => {
  const r = await fetch(path, body ? {method:"POST", body: JSON.stringify(body)} : undefined);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
};

async function showSessions() {
  const {sessions} = await api("/api/sessions");
  const el = document.getElementById("app");
  el.innerHTML = "<h2>Sessions</h2>";
  for (const s of sessions) {
    const b = $(`<button style="width:100%;text-align:left">${s.name}
      &nbsp;<span class="muted">${s.finalized ? "finalized" : s.n_complete + "/" + s.n_clips + " answered"}</span></button>`);
    b.onclick = () => openSession(s.name);
    el.appendChild(b);
  }
  el.appendChild($(`<p class="muted">Listen blind. Judge each clip on its own; several clips may be viable. Do not open key.json.</p>`));
}

async function openSession(name) {
  S = await api("/api/state?session=" + encodeURIComponent(name));
  idx = Math.min(S.complete_ids.length, S.n_clips - 1);
  if (S.finalized) { renderResults(); } else { renderClip(); }
}

function entry() { return S.responses[S.clip_ids[idx]]; }

function loadAudio() {
  comparing = false;
  audio.src = "/audio/" + encodeURIComponent(S.name) + "/" + S.clip_ids[idx] + ".wav";
  prevAudio.src = idx > 0 ? "/audio/" + encodeURIComponent(S.name) + "/" + S.clip_ids[idx-1] + ".wav" : "";
}

function ratingRow(dim, label) {
  const v = entry()[dim];
  let h = `<div class="row"><div class="label">${label}</div>`;
  for (let i = 1; i <= 5; i++)
    h += `<button data-dim="${dim}" data-val="${i}" class="${v === i ? "on" : ""}">${i}</button>`;
  return h + "</div>";
}

function renderClip() {
  loadAudio();
  const e = entry(), el = document.getElementById("app");
  el.innerHTML = `
    <div class="row"><div id="progress"><div id="progressbar" style="width:${100*S.n_complete/S.n_clips}%"></div></div>
      <div class="muted">${S.n_complete}/${S.n_clips} answered — ${S.name}</div></div>
    <div class="clipnav">
      <button id="prev" ${idx===0?"disabled":""}>&#8592;</button>
      <h2>${S.clip_ids[idx].replace("_"," ")} <span class="muted">(${idx+1}/${S.n_clips})</span></h2>
      <button id="next" ${idx===S.n_clips-1?"disabled":""}>&#8594;</button>
    </div>
    <div class="row transport">
      <button id="play">&#9654;</button>
      <button id="replay">&#8634;</button>
      <button id="compare" ${idx===0?"disabled":""}>A/B prev</button>
    </div>
    <div class="row"><div class="label">viable?</div>
      <button data-viable="true"  class="${e.viable===true?"on":""}">yes</button>
      <button data-viable="false" class="warn ${e.viable===false?"on":""}">no</button>
      <button data-viable="unsure" class="unsure ${e.viable==="unsure"?"on":""}">unsure</button>
    </div>
    ${ratingRow("rhythmic_coherence","rhythmic coherence (1 bad – 5 good)")}
    ${ratingRow("harmonic_coherence","harmonic coherence")}
    ${ratingRow("phrase_section_coherence","phrase/section coherence")}
    ${ratingRow("masking_density_conflict","masking/density (1 severe conflict – 5 clean)")}
    <div class="row"><div class="label">confidence</div>
      <button data-conf="low" class="${e.confidence==="low"?"on":""}">low</button>
      <button data-conf="medium" class="${e.confidence==="medium"?"on":""}">medium</button>
      <button data-conf="high" class="${e.confidence==="high"?"on":""}">high</button>
    </div>
    <div class="row"><div class="label">notes</div><textarea id="notes">${e.notes||""}</textarea></div>
    <div class="save" id="save"></div>
    <button id="finalize" ${S.n_complete===S.n_clips?"":"disabled"}>
      finalize session${S.n_complete===S.n_clips?"":" ("+(S.n_clips-S.n_complete)+" clip(s) unanswered)"}</button>
    <div class="keys">keys: space play/pause · r replay · &#8592;/&#8594; prev/next · c A/B prev · y/n/u viable</div>
    <p class="muted"><a href="#" id="back">all sessions</a></p>`;

  el.querySelector("#play").onclick = togglePlay;
  el.querySelector("#replay").onclick = () => { audio.currentTime = 0; audio.play(); };
  el.querySelector("#prev").onclick = () => { idx--; renderClip(); };
  el.querySelector("#next").onclick = () => { idx++; renderClip(); };
  el.querySelector("#compare").onclick = toggleCompare;
  el.querySelector("#back").onclick = (ev) => { ev.preventDefault(); showSessions(); };
  el.querySelectorAll("[data-viable]").forEach(b => b.onclick = () => {
    const v = b.dataset.viable === "true" ? true : b.dataset.viable === "false" ? false : "unsure";
    save({viable: v});
  });
  el.querySelectorAll("[data-dim]").forEach(b => b.onclick = () =>
    save({[b.dataset.dim]: parseInt(b.dataset.val)}));
  el.querySelectorAll("[data-conf]").forEach(b => b.onclick = () => save({confidence: b.dataset.conf}));
  el.querySelector("#notes").oninput = (ev) => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => save({notes: ev.target.value}), 500);
  };
  el.querySelector("#finalize").onclick = finalize;
}

function togglePlay() {
  const a = comparing ? prevAudio : audio;
  if (a.paused) a.play(); else a.pause();
}

function toggleCompare() {
  if (idx === 0) return;
  const from = comparing ? prevAudio : audio, to = comparing ? audio : prevAudio;
  const pos = from.currentTime; from.pause();
  to.currentTime = Math.min(pos, to.duration || pos);
  to.play();
  comparing = !comparing;
  document.getElementById("compare").classList.toggle("on", comparing);
}

async function save(patch) {
  Object.assign(entry(), patch);
  const before = S.clip_ids[idx];
  try {
    const r = await api("/api/response", {session: S.name, blind_id: before, entry: patch});
    S.responses[before] = r.saved;
    S.n_complete = r.n_complete;
    if (S.clip_ids[idx] === before) renderClip();
    document.getElementById("save").textContent = "saved";
  } catch (e) {
    document.getElementById("save").textContent = "SAVE FAILED: " + e.message;
  }
}

async function finalize() {
  if (!confirm("Finalize? Responses freeze and the offset mapping is revealed.")) return;
  try {
    const results = await api("/api/finalize", {session: S.name});
    S.finalized = true; S.results = results;
    renderResults();
  } catch (e) { alert(e.message); }
}

function renderResults() {
  const el = document.getElementById("app");
  const recs = S.results.records;
  let rows = recs.map(r => `<tr><td><b>${r.offset_bars}</b></td>
    <td>${r.viable===true?"yes":r.viable===false?"no":"unsure"}</td>
    <td>${r.rhythmic_coherence ?? "–"}</td><td>${r.harmonic_coherence ?? "–"}</td>
    <td>${r.phrase_section_coherence ?? "–"}</td><td>${r.masking_density_conflict ?? "–"}</td>
    <td>${r.confidence}</td><td style="text-align:left">${r.notes||""}</td></tr>`).join("");
  const rk = S.results.ranking || {};
  let ranking = "";
  if (rk.abstention_report) {
    ranking = `<p class="muted">${rk.abstention_report}</p>`;
  } else if (rk.features && rk.features.length) {
    const top = [...rk.features].sort((a,b)=>(b.pairwise_accuracy??-1)-(a.pairwise_accuracy??-1)).slice(0,10);
    ranking = `<table><tr><th>feature</th><th>dir</th><th>pairwise</th><th>ranks</th></tr>` +
      top.map(f=>`<tr><td style="text-align:left">${f.feature}</td><td>${f.direction}</td>
        <td>${f.pairwise_accuracy==null?"–":f.pairwise_accuracy.toFixed(2)}</td>
        <td>${f.success_ranks.join(",")}</td></tr>`).join("") + "</table>" +
      `<p class="muted">${rk.single_pair_warning||""}</p>`;
  }
  el.innerHTML = `<h2>${S.name} — finalized</h2>
    <div class="card"><h2>Judgments by actual offset</h2>
    <table><tr><th>offset</th><th>viable</th><th>rhy</th><th>harm</th><th>phrase</th><th>mask</th><th>conf</th><th>notes</th></tr>
    ${rows}</table></div>
    <div class="card"><h2>Refreshed strict ranking (this session's labels)</h2>${ranking}</div>
    <p class="muted"><a href="#" id="back">all sessions</a> — corpus fixture update stays a manual, reviewed step.</p>`;
  el.querySelector("#back").onclick = (ev) => { ev.preventDefault(); showSessions(); };
}

document.addEventListener("keydown", (ev) => {
  if (!S || S.finalized || ev.target.tagName === "TEXTAREA") return;
  if (ev.code === "Space") { ev.preventDefault(); togglePlay(); }
  else if (ev.key === "r") { audio.currentTime = 0; audio.play(); }
  else if (ev.key === "ArrowLeft" && idx > 0) { idx--; renderClip(); }
  else if (ev.key === "ArrowRight" && idx < S.n_clips - 1) { idx++; renderClip(); }
  else if (ev.key === "c") toggleCompare();
  else if (ev.key === "y") save({viable: true});
  else if (ev.key === "n") save({viable: false});
  else if (ev.key === "u") save({viable: "unsure"});
});

showSessions();
</script>
</body>
</html>
"""
