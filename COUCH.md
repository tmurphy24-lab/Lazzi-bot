# The Couch - Lazii-Bot Job Command Center

A local job-hunting cockpit built on GodsScion/Auto_job_applier_linkedIn.
Lazii-Bot (a chubby, scruffy couch-bot mascot) automates LinkedIn Easy Apply,
tracks every application, and answers to chat.

## Launch

- Double-click `desktop.bat` (or the "The Couch" desktop shortcut) - opens the
  control panel in a standalone desktop window.
- Manual: `.venv\Scripts\python app.py`, then open the printed 127.0.0.1 URL.

## Tabs

| Tab      | What it does |
|----------|--------------|
| Guide    | Welcome 2 The Couch - full walkthrough (start here) |
| Account  | LinkedIn credentials + AI provider/key (env vars recommended) |
| Profile  | Name, phone, address, equal-opportunity answers |
| Search   | Fine-grained search filters and blacklists |
| Games    | Game-card presets + quick settings for the hunt |
| Scout    | Multi-board job discovery (Indeed, ZipRecruiter, Glassdoor, ...) via JobSpy |
| Stats    | Application analytics: daily pace, totals, top companies |
| Run      | Start/stop the bot, live log, applied-jobs table |
| History  | Full applied-jobs page at /history |

## Lazii-Bot chat

Bottom-right bubble on every page. With AI enabled (Account tab) he can:

- Change any non-secret setting ("set location to Chicago", "remote only")
- Switch the active resume ("switch to my resume X")
- Start/stop/status the hunt ("start hunting", "stop", "how's it going?")
- Refuses to touch credentials - those live in Account/env vars only

## Scheduled agent

Windows Task Scheduler task `LinkedInJobBotDaily` runs daily 09:37, headless:

```
schtasks /Run /TN LinkedInJobBotDaily     # fire one now
schtasks /Delete /TN LinkedInJobBotDaily  # remove it
```

Reads credentials from env vars or a project-root `.env` (see
`.env.example`; `.env` is gitignored). Headless mode suppresses every
blocking popup (sponsor alert, pause dialogs, log-file alerts).

## Secrets policy

No real secrets in files. Use user-level env vars (`setx LINKEDIN_USERNAME ...`)
or a local gitignored `.env` created from `.env.example`. `user_config.json`
holds non-secret settings only (written by the control panel).

## Data files

- `all excels/all_applied_applications_history.csv` - every application
- `all excels/all_failed_applications_history.csv` - failures
- `logs/` - run logs (`scheduled_run_<date>.log` for scheduled runs)

## Dev notes

- venv at `.venv` (Python 3.14). Tests: `.venv\Scripts\python -m pytest tests/`
  (add `--ignore=tests/test_ai_connections.py` if logs/log.txt is locked).
- New endpoints in `app.py`: `/api/chat`, `/api/stats`, `/api/resumes`,
  `/api/scout`.
- JobSpy installed with `--no-deps` + modern numpy/pandas (Python 3.14 has no
  numpy 1.26 wheels); verified working.

## Git layout

Two remotes, two jobs:

- `origin` = upstream GodsScion/Auto_job_applier_linkedIn - source of updates.
- `lazzi` = this repo (tmurphy24-lab/Lazzi-bot) - where The Couch work lives.

Daily flow: work on the `lazzibot` branch (tracks `lazzi/main`), commit,
`git push`. Pull upstream updates with `git fetch origin` then
`git merge origin/main`. Upstream's MIT license is preserved as
`LICENSE.upstream`; this repo's own LICENSE sits at the root.
