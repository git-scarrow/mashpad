"""Tests for the local audition workbench: session loading, atomic
autosave, incomplete-session refusal, key non-disclosure (app level and
over HTTP), finalization artifact separation, and refreshed report
generation. Sessions are synthetic (tiny stdlib-generated WAVs); no
librosa, no real audio, no network beyond 127.0.0.1 on an ephemeral
port."""

import http.client
import json
import struct
import threading
import wave
from pathlib import Path

import pytest

from mashpad.research.audition import RESPONSE_DIMENSIONS, blind_assignment, response_template
from mashpad.research.workbench import (
    LABELS_FILE,
    RANKING_FILE,
    AuditionWorkbench,
    IncompleteSessionError,
    serve,
)

OFFSETS = (-1, 0, 1)
SEED = 7


def _write_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(8000)
        fh.writeframes(struct.pack("<8000h", *([0] * 8000)))


def _make_session(root: Path, name: str = "session_x") -> Path:
    session = root / name
    (session / "clips").mkdir(parents=True)
    assignment = blind_assignment(OFFSETS, SEED)
    for blind_id, _ in assignment:
        _write_wav(session / "clips" / f"{blind_id}.wav")
    (session / "session.json").write_text(
        json.dumps({"session_id": name, "window_bars": 8, "pitch_shift_semitones": 2})
    )
    (session / "key.json").write_text(
        json.dumps(
            {
                "session_id": name,
                "assignment": {
                    blind_id: {"offset_bars": off, "guest_silent_padding": False}
                    for blind_id, off in assignment
                },
            }
        )
    )
    (session / "responses.json").write_text(
        json.dumps(response_template(tuple(b for b, _ in assignment)))
    )
    return session


def _filled(viable=True):
    return {
        "viable": viable,
        **{dim: 3 for dim in RESPONSE_DIMENSIONS},
        "confidence": "high",
        "notes": "",
    }


def _fill_all(app: AuditionWorkbench, name: str, viable_by_index=None):
    for i, blind_id in enumerate(app.clip_ids(name)):
        viable = viable_by_index[i] if viable_by_index else True
        app.save_response(name, blind_id, _filled(viable))


# --- session loading -------------------------------------------------------------


def test_session_loading_and_state_conceal_offsets(tmp_path):
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,))
    state = app.state("session_x")
    assert state["n_clips"] == 3
    assert state["n_complete"] == 0
    assert state["finalized"] is False
    assert sorted(state["clip_ids"]) == ["clip_a", "clip_b", "clip_c"]
    # the blind holds: nothing in the serialized state mentions offsets
    assert "offset" not in json.dumps(state).lower()
    summary = app.sessions_summary()
    assert "offset" not in json.dumps(summary).lower()


def test_loading_a_non_session_directory_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError, match="responses.json"):
        AuditionWorkbench(session_dirs=(tmp_path,))


# --- autosave ---------------------------------------------------------------------


def test_autosave_is_atomic_partial_and_merged(tmp_path):
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,))
    result = app.save_response("session_x", "clip_a", {"viable": True})
    assert result["problems"]  # partial entry: valid to save, not yet complete
    assert result["n_complete"] == 0
    on_disk = json.loads((session / "responses.json").read_text())
    assert on_disk["responses"]["clip_a"]["viable"] is True
    assert not (session / "responses.json.tmp").exists()  # atomic replace, no leftovers
    app.save_response("session_x", "clip_a", _filled())
    assert app.state("session_x")["n_complete"] == 1


def test_autosave_rejects_unknown_clips_and_fields(tmp_path):
    app = AuditionWorkbench(session_dirs=(_make_session(tmp_path),))
    with pytest.raises(KeyError, match="unknown clip"):
        app.save_response("session_x", "clip_z", {"viable": True})
    with pytest.raises(KeyError, match="unknown response fields"):
        app.save_response("session_x", "clip_a", {"offset_bars": 0})


# --- finalization -----------------------------------------------------------------


def test_finalize_refuses_incomplete_sessions(tmp_path):
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,))
    app.save_response("session_x", "clip_a", _filled())
    with pytest.raises(IncompleteSessionError):
        app.finalize("session_x")
    assert not (session / LABELS_FILE).exists()  # nothing decoded on refusal


def test_finalize_separates_sealed_and_decoded_artifacts(tmp_path):
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,))
    key_before = (session / "key.json").read_text()
    responses = json.loads((session / "responses.json").read_text())
    _fill_all(app, "session_x", viable_by_index=[True, False, True])
    results = app.finalize("session_x")
    # sealed artifacts untouched
    assert (session / "key.json").read_text() == key_before
    # decoded artifacts written separately
    labels = json.loads((session / LABELS_FILE).read_text())
    assert (session / RANKING_FILE).exists()
    assert sorted(r["offset_bars"] for r in labels) == sorted(OFFSETS)
    assert sum(1 for r in labels if r["viable"] is True) == 2  # multiple viable allowed
    assert all(r["method"] == "blinded_audition:session_x" for r in labels)
    assert results["records"] == labels
    # responses are frozen afterwards
    with pytest.raises(IncompleteSessionError, match="frozen"):
        app.save_response("session_x", "clip_a", {"viable": False})
    assert responses["responses"]  # template had entries (sanity)


def test_finalized_ranking_uses_session_labels_and_probe_features(tmp_path):
    features = {"flat_features": {str(off): {"probe_feature": float(off)} for off in OFFSETS}}
    artifact = tmp_path / "trajectories.json"
    artifact.write_text(json.dumps(features))
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,), trajectories=artifact)
    _fill_all(app, "session_x", viable_by_index=[True, False, "unsure"])
    ranking = app.finalize("session_x")["ranking"]
    assert ranking["label_source"] == "blinded audition (this session only)"
    assert ranking["n_successes"] == 1
    assert ranking["n_negatives"] == 1  # the 'unsure' clip is excluded, not a negative
    assert any(f["feature"] == "probe_feature" for f in ranking["features"])


def test_finalize_without_feature_artifacts_grounds_labels_and_abstains(tmp_path):
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,))
    _fill_all(app, "session_x")
    ranking = app.finalize("session_x")["ranking"]
    assert "ranking skipped" in ranking["abstention_report"]


# --- HTTP layer (ephemeral port, loopback only) ------------------------------------


@pytest.fixture
def server(tmp_path):
    session = _make_session(tmp_path)
    app = AuditionWorkbench(session_dirs=(session,))
    srv = serve(app, "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, app, session
    srv.shutdown()


def _request(srv, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    conn.request(method, path, json.dumps(body) if body else None)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


def test_http_key_json_is_never_served(server):
    srv, _, _ = server
    for path in ("/key.json", "/audio/session_x/key.json", "/api/state?session=../key.json"):
        status, data = _request(srv, "GET", path)
        assert status in (403, 404), path
        assert b"assignment" not in data
    # and the page + state contain no offsets
    status, page = _request(srv, "GET", "/")
    assert status == 200
    status, state = _request(srv, "GET", "/api/state?session=session_x")
    assert status == 200
    assert "offset" not in json.loads(state).keys().__str__().lower()


def test_http_audio_serves_ranges_for_phone_browsers(server):
    srv, _, _ = server
    status, full = _request(srv, "GET", "/audio/session_x/clip_a.wav")
    assert status == 200 and len(full) > 1000
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=5)
    conn.request("GET", "/audio/session_x/clip_a.wav", headers={"Range": "bytes=0-99"})
    resp = conn.getresponse()
    assert resp.status == 206
    assert resp.getheader("Content-Range") == f"bytes 0-99/{len(full)}"
    assert len(resp.read()) == 100
    conn.close()


def test_http_autosave_and_incomplete_finalize(server):
    srv, app, session = server
    status, data = _request(
        srv,
        "POST",
        "/api/response",
        {"session": "session_x", "blind_id": "clip_a", "entry": _filled()},
    )
    assert status == 200
    assert json.loads(data)["n_complete"] == 1
    on_disk = json.loads((session / "responses.json").read_text())
    assert on_disk["responses"]["clip_a"]["viable"] is True
    status, data = _request(srv, "POST", "/api/finalize", {"session": "session_x"})
    assert status == 409  # refused: two clips unanswered
    assert not (session / LABELS_FILE).exists()


def test_http_finalize_after_completion(server):
    srv, app, session = server
    _fill_all(app, "session_x")
    status, data = _request(srv, "POST", "/api/finalize", {"session": "session_x"})
    assert status == 200
    payload = json.loads(data)
    assert len(payload["records"]) == 3
    assert (session / LABELS_FILE).exists()
