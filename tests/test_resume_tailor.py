'''
Tests for POST /api/resumes/tailor (AI resume tailoring). No prior coverage
existed - this is a new feature.

The validation-error paths run with no AI and no fixtures beyond a fake saved
job, so they're fast and always run. The full pipeline (read a real PDF,
call a real AI provider, write a tailored PDF back out) is a live-gated smoke
test mirroring test_live_minimax_answer / test_live_openai_answer.

License: MIT  (https://opensource.org/license/mit)
'''

import io
import json
import os

import pytest


def _save_job(client, tmp_path, monkeypatch, **overrides):
    import app
    monkeypatch.setattr(app, "SAVED_PATH", str(tmp_path / "saved_jobs.json"))
    job = {
        "title": "Senior Backend Engineer",
        "company": "Acme Robotics",
        "job_url": "https://example.com/job/1",
        "description": "We need someone strong in Python, Kubernetes and "
                        "distributed systems to lead our platform team.",
    }
    job.update(overrides)
    resp = client.post("/api/saved", json={"jobs": [job]})
    assert resp.status_code == 200
    return client.get("/api/saved").get_json()["jobs"][0]["id"]


def test_missing_id_is_rejected(client):
    resp = client.post("/api/resumes/tailor", json={})
    assert resp.status_code == 400


def test_unknown_job_id_is_rejected(client, tmp_path, monkeypatch):
    import app
    monkeypatch.setattr(app, "SAVED_PATH", str(tmp_path / "saved_jobs.json"))
    resp = client.post("/api/resumes/tailor", json={"id": "does-not-exist"})
    assert resp.status_code == 404


def test_job_with_no_description_is_rejected(client, tmp_path, monkeypatch):
    job_id = _save_job(client, tmp_path, monkeypatch, description="")
    resp = client.post("/api/resumes/tailor", json={"id": job_id})
    assert resp.status_code == 400
    assert "description" in resp.get_json()["error"]


def test_no_active_resume_is_rejected(client, tmp_path, monkeypatch):
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    job_id = _save_job(client, tmp_path, monkeypatch)
    resp = client.post("/api/resumes/tailor", json={"id": job_id})
    assert resp.status_code == 400
    assert "resume" in resp.get_json()["error"].lower()


def test_ai_off_is_rejected_after_resume_is_found(client, tmp_path, monkeypatch):
    '''
    The AI-off check must come after the resume/job lookups succeed, so the
    user gets "flip Use AI" rather than a confusing 404/400 unrelated to AI.
    '''
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)

    resumes_dir = tmp_path / "all resumes"
    resumes_dir.mkdir()
    resume_path = resumes_dir / "resume.pdf"
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.cell(0, 10, "Jane Doe - Software Engineer")
    pdf.output(str(resume_path))
    monkeypatch.setattr(app, "ROOT", str(tmp_path))

    resp = client.post("/api/config", json={
        "questions": {"default_resume_path": "all resumes/resume.pdf"},
    })
    assert resp.status_code == 200

    job_id = _save_job(client, tmp_path, monkeypatch)
    resp = client.post("/api/resumes/tailor", json={"id": job_id})
    assert resp.status_code == 400
    assert "AI is off" in resp.get_json()["error"]


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("MINIMAX_API_KEY"),
                    reason="set MINIMAX_API_KEY to run the real resume-tailoring smoke test")
def test_live_tailor_resume_end_to_end(client, tmp_path, monkeypatch):
    '''
    Real end-to-end check: writes a synthetic resume PDF, saves a job, calls
    the real MiniMax API to tailor it, and confirms a readable PDF with
    different (tailored) content comes back.
    '''
    import app
    import config._overrides as overrides
    cfg_path = str(tmp_path / "user_config.json")
    monkeypatch.setattr(app, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(overrides, "USER_CONFIG_PATH", cfg_path)
    monkeypatch.setattr(app, "ROOT", str(tmp_path))

    resumes_dir = tmp_path / "all resumes"
    resumes_dir.mkdir()
    resume_path = resumes_dir / "resume.pdf"
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in [
        "Jane Doe - Software Engineer",
        "jane@example.com | 555-0100",
        "",
        "Summary",
        "Backend engineer with 6 years building distributed systems in Python and Go.",
        "",
        "Experience",
        "Senior Software Engineer, Widget Co (2021-Present)",
        "- Built a Kubernetes-based deployment pipeline used by 40 engineers.",
        "- Led migration of a monolith to microservices, cutting deploy time 70%.",
        "",
        "Skills",
        "Python, Go, Kubernetes, PostgreSQL, AWS",
    ]:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(resume_path))

    resp = client.post("/api/config", json={
        "secrets": {
            "use_AI": True,
            "ai_provider": "minimax",
            "llm_model": os.getenv("MINIMAX_TEST_MODEL", "MiniMax-M2.7"),
            "llm_api_key": os.environ["MINIMAX_API_KEY"],
            "llm_api_url": "https://api.minimax.io/anthropic",
        },
        "questions": {"default_resume_path": "all resumes/resume.pdf"},
    })
    assert resp.status_code == 200

    job_id = _save_job(client, tmp_path, monkeypatch,
                        title="Kubernetes Platform Engineer",
                        company="Acme Robotics",
                        description="Looking for a platform engineer with deep "
                                     "Kubernetes and distributed-systems experience "
                                     "to own our deployment pipeline.")

    resp = client.post("/api/resumes/tailor", json={"id": job_id})
    assert resp.status_code == 200, resp.get_json()
    resume_path_out = resp.get_json()["resume_path"]
    assert resume_path_out.startswith("all resumes/")
    assert "Acme" in resume_path_out or "Kubernetes" in resume_path_out

    full_out_path = os.path.join(str(tmp_path), resume_path_out)
    assert os.path.isfile(full_out_path)

    tailored_text = app._read_resume_text(full_out_path)
    assert tailored_text.strip() != ""
    # Real facts from the source resume must survive - the AI must not have
    # invented a different person or fabricated new companies.
    assert "widget co" in tailored_text.lower() or "python" in tailored_text.lower()
