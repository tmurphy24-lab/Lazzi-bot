'''
Tests for GET /api/scout's request validation and its behaviour when the
optional `jobspy` dependency is missing. No prior coverage existed for this
endpoint.

The missing-dependency case is a real regression test: python-jobspy was
never declared in requirements.txt, so a fresh install had it silently absent
and Scout failed opaquely. It now degrades to a clear 500 instead of an
unhandled ImportError - pinned here so a future refactor can't reintroduce a
crash on that path.

License: MIT  (https://opensource.org/license/mit)
'''

import sys


def test_missing_titles_is_rejected(client):
    resp = client.get("/api/scout?location=Chicago&boards=indeed")
    assert resp.status_code == 400


def test_missing_location_is_rejected(client):
    resp = client.get("/api/scout?titles=Engineer&boards=indeed")
    assert resp.status_code == 400


def test_no_valid_boards_is_rejected(client):
    resp = client.get("/api/scout?titles=Engineer&location=Chicago&boards=not_a_real_board")
    assert resp.status_code == 400


def test_non_numeric_hours_or_limit_is_rejected(client):
    resp = client.get("/api/scout?titles=Engineer&location=Chicago&boards=indeed&hours=abc")
    assert resp.status_code == 400


def test_unknown_boards_are_dropped_not_passed_through(monkeypatch, client):
    '''
    Regression: the panel's "ziprecruiter" must map to jobspy's "zip_recruiter",
    never reach scrape_jobs() unmapped, and a bogus board name must be silently
    dropped rather than crash the whole scrape.
    '''
    import app
    seen = {}

    def fake_scout_jobs(titles, location, boards, hours, limit):
        seen["boards"] = boards
        return [], {}

    monkeypatch.setattr(app, "_scout_jobs", fake_scout_jobs)
    resp = client.get(
        "/api/scout?titles=Engineer&location=Chicago"
        "&boards=indeed,ziprecruiter,not_a_real_board"
    )
    assert resp.status_code == 200
    assert seen["boards"] == ["indeed", "zip_recruiter"]


def test_missing_jobspy_dependency_degrades_to_clear_error_not_a_crash(client, monkeypatch):
    '''
    Regression for the undeclared-dependency bug: python-jobspy was importable
    only because it happened to already be installed in this dev venv, not
    because requirements.txt asked for it. A fresh install would hit
    `from jobspy import scrape_jobs` and get ImportError. That must surface as
    a normal JSON error, not an unhandled exception / 500 with a stack trace.
    '''
    monkeypatch.setitem(sys.modules, "jobspy", None)  # forces ImportError on import
    resp = client.get("/api/scout?titles=Engineer&location=Chicago&boards=indeed")
    assert resp.status_code == 500
    assert "scout failed" in resp.get_json()["error"]
