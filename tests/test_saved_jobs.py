'''
Tests for the /api/saved pipeline board (app.py). No prior coverage existed
for this endpoint; added while stress-testing app.py end to end.

All tests isolate saved_jobs.json to tmp_path so the user's real board is
never touched.

License: MIT  (https://opensource.org/license/mit)
'''

import json


def _isolate(monkeypatch, tmp_path):
    import app
    path = str(tmp_path / "saved_jobs.json")
    monkeypatch.setattr(app, "SAVED_PATH", path)
    return path


def test_post_with_no_job_data_is_rejected(client, tmp_path, monkeypatch):
    '''
    Root-cause regression: an empty body used to produce a saved record with
    every field blank, because _saved_key(['', '', '']) -> '||', which is
    truthy. A job with no title, company, location or URL is not a job.
    '''
    path = _isolate(monkeypatch, tmp_path)

    resp = client.post("/api/saved")
    assert resp.status_code == 400

    resp = client.post("/api/saved", json={})
    assert resp.status_code == 400

    import os
    assert not os.path.exists(path)


def test_save_dedupes_by_url(client, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = {"title": "Engineer", "company": "Acme", "job_url": "https://x/1"}

    first = client.post("/api/saved", json={"jobs": [job]}).get_json()
    assert first == {"added": 1, "skipped": 0, "total": 1}

    second = client.post("/api/saved", json={"jobs": [job]}).get_json()
    assert second == {"added": 0, "skipped": 1, "total": 1}


def test_save_dedupes_by_title_company_location_when_no_url(client, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = {"title": "Engineer", "company": "Acme", "location": "Remote"}

    client.post("/api/saved", json={"jobs": [job]})
    second = client.post("/api/saved", json={"jobs": [job]}).get_json()
    assert second["added"] == 0
    assert second["skipped"] == 1


def test_patch_moves_stage_and_rejects_unknown_stage(client, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = {"title": "Engineer", "company": "Acme", "job_url": "https://x/2"}
    client.post("/api/saved", json={"jobs": [job]})

    resp = client.patch("/api/saved", json={"id": "https://x/2", "stage": "interview"})
    assert resp.status_code == 200
    assert resp.get_json()["stage"] == "interview"

    bad = client.patch("/api/saved", json={"id": "https://x/2", "stage": "hired"})
    assert bad.status_code == 400

    missing = client.patch("/api/saved", json={"id": "does-not-exist", "stage": "applied"})
    assert missing.status_code == 404


def test_delete_removes_job(client, tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    job = {"title": "Engineer", "company": "Acme", "job_url": "https://x/3"}
    client.post("/api/saved", json={"jobs": [job]})

    resp = client.delete("/api/saved", json={"id": "https://x/3"})
    assert resp.status_code == 200
    assert client.get("/api/saved").get_json()["counts"]["saved"] == 0

    again = client.delete("/api/saved", json={"id": "https://x/3"})
    assert again.status_code == 404


def test_get_reports_applied_keys_from_history(client, tmp_path, monkeypatch):
    '''Scout's duplicate flag reads applied_keys from the applied-jobs CSV.'''
    import app
    _isolate(monkeypatch, tmp_path)
    excels = tmp_path / "all excels"
    excels.mkdir()
    monkeypatch.setattr(app, "PATH", str(excels))

    csv_path = excels / app._APPLIED_CSV
    csv_path.write_text(
        "Title,Company,External Job link,Date Applied\n"
        "Senior Engineer,Acme,Easy Applied,2026-01-01 10:00:00\n",
        encoding="utf-8",
    )

    body = client.get("/api/saved").get_json()
    assert body["applied_keys"] == ["senior engineer|acme"]
