'''
Tests for the bot subprocess lifecycle (app.py: /api/run, /api/stop,
/api/status). No prior coverage existed for this path - the most consequential
one in the app, since it spawns and kills a real process.

_bot_command() is monkeypatched to a short-lived Python process instead of the
real Selenium bot, so these run headless and fast without touching Chrome or
LinkedIn.

License: MIT  (https://opensource.org/license/mit)
'''

import sys
import time

import pytest


def _use_fake_bot(monkeypatch, tmp_path, sleep_seconds=2):
    '''Point _bot_command at a tiny script instead of runAiBot.py.'''
    import app
    script = tmp_path / "fake_bot.py"
    script.write_text(
        "import time, sys\n"
        "print('fake bot running', flush=True)\n"
        f"time.sleep({sleep_seconds})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(app, "_bot_command", lambda: [sys.executable, str(script)])
    monkeypatch.setattr(app, "LOG_PATH", str(tmp_path / "run.log"))
    monkeypatch.setattr(app, "PID_PATH", str(tmp_path / "run.pid"))


@pytest.fixture(autouse=True)
def _cleanup_bot_state():
    '''However a test ends, never leave a subprocess running for the next one.'''
    yield
    import app
    with app._bot_lock:
        if app._bot_proc is not None:
            app._terminate(app._bot_proc)
            app._bot_proc = None


def test_start_reports_running_with_pid(client, tmp_path, monkeypatch):
    _use_fake_bot(monkeypatch, tmp_path)
    resp = client.post("/api/run").get_json()
    assert resp["running"] is True
    assert isinstance(resp["pid"], int)

    status = client.get("/api/status").get_json()
    assert status["running"] is True
    assert status["pid"] == resp["pid"]


def test_double_start_is_a_noop_not_a_second_process(client, tmp_path, monkeypatch):
    _use_fake_bot(monkeypatch, tmp_path, sleep_seconds=3)
    first = client.post("/api/run").get_json()
    second = client.post("/api/run").get_json()
    assert second["running"] is True
    assert second["pid"] == first["pid"]
    assert "already running" in second.get("message", "")


def test_stop_terminates_and_status_reflects_it(client, tmp_path, monkeypatch):
    _use_fake_bot(monkeypatch, tmp_path, sleep_seconds=5)
    client.post("/api/run")
    assert client.get("/api/status").get_json()["running"] is True

    stop_resp = client.post("/api/stop").get_json()
    assert stop_resp == {"running": False, "stopped": True}
    assert client.get("/api/status").get_json()["running"] is False


def test_stop_when_not_running_reports_false(client, tmp_path, monkeypatch):
    _use_fake_bot(monkeypatch, tmp_path)
    resp = client.post("/api/stop").get_json()
    assert resp == {"running": False, "stopped": False}


def test_status_reflects_process_exiting_on_its_own(client, tmp_path, monkeypatch):
    '''
    A process that finishes naturally (not via /api/stop) must still be
    detected as not-running on the next status check.

    Polls instead of a fixed sleep: a single subprocess's exit latency on
    Windows varies enough (process creation, AV scanning) that a flat
    "sleep longer than the script's own sleep" margin flakes under load.
    '''
    _use_fake_bot(monkeypatch, tmp_path, sleep_seconds=1)
    client.post("/api/run")

    deadline = time.monotonic() + 10
    running = True
    while time.monotonic() < deadline:
        running = client.get("/api/status").get_json()["running"]
        if not running:
            break
        time.sleep(0.2)
    assert running is False


def test_start_failure_is_reported_not_raised(client, tmp_path, monkeypatch):
    '''A command that can't even launch (bad executable) must 500-free error.'''
    import app
    monkeypatch.setattr(app, "_bot_command", lambda: [str(tmp_path / "does-not-exist.exe")])
    monkeypatch.setattr(app, "LOG_PATH", str(tmp_path / "run.log"))
    monkeypatch.setattr(app, "PID_PATH", str(tmp_path / "run.pid"))

    resp = client.post("/api/run")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["running"] is False
    assert "error" in body
