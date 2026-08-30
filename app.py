'''
Author:     Sai Vignesh Golla
License:    MIT License
            https://opensource.org/license/mit
GitHub:     https://github.com/GodsScion/Auto_job_applier_linkedIn

Local "control panel" web app. It lets a non-technical person configure and run
the tool from a browser instead of editing Python files and using a terminal.

IMPORTANT - how configuration works:
  * This app reads/writes ONLY `user_config.json` at the project root.
  * It NEVER edits the config/*.py files.
  * The config/*.py modules load user_config.json over their built-in defaults
    (see config/_overrides.py), so saving here changes the tool's behaviour
    while leaving the classic "edit the .py files" workflow intact. With no
    user_config.json present the tool behaves exactly as it always has.

SECURITY: this app handles LinkedIn credentials, so it binds to 127.0.0.1 only
(never 0.0.0.0) and runs with debug OFF. Do not change these.
'''

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import csv
import re
from datetime import datetime, timedelta
import os
import sys
import json
import copy
import signal
import subprocess
import threading
import importlib

import config_schema
from config import _overrides

app = Flask(__name__)
CORS(app)

# Project root is the folder this file lives in.
ROOT = os.path.dirname(os.path.abspath(__file__))
USER_CONFIG_PATH = _overrides.USER_CONFIG_PATH
LOG_PATH = os.path.join(ROOT, ".bot_run.log")
PID_PATH = os.path.join(ROOT, ".bot_run.pid")

PATH = 'all excels/'


# ===========================================================================
# Default config values (the pristine config/*.py defaults, ignoring any
# user_config.json). Captured once at startup so /api/config can always show
# "default overlaid with the user's current saved values".
# ===========================================================================
def _load_defaults() -> dict:
    '''
    Import each config module with overrides temporarily disabled, so we read
    the untouched Python defaults regardless of whether user_config.json exists
    right now. Returns {config_module: {key: default_value}}.
    '''
    original_loader = _overrides.load_user_config
    _overrides.load_user_config = lambda: {}
    try:
        import config.secrets as _secrets
        import config.personals as _personals
        import config.questions as _questions
        import config.search as _search
        import config.settings as _settings
        modules = {
            "secrets": _secrets,
            "personals": _personals,
            "questions": _questions,
            "search": _search,
            "settings": _settings,
        }
        # Reload in case they were already imported (with real overrides) earlier.
        for module in modules.values():
            importlib.reload(module)
        defaults = {}
        for field in config_schema.iter_fields():
            module_name = field["config_module"]
            key = field["key"]
            module = modules.get(module_name)
            defaults.setdefault(module_name, {})[key] = getattr(module, key, None)
        return defaults
    finally:
        _overrides.load_user_config = original_loader


DEFAULTS = _load_defaults()


# ===========================================================================
# Config API helpers
# ===========================================================================
def _effective_config() -> dict:
    '''
    Return {config_module: {key: value}} of the pristine defaults overlaid with
    the CURRENT contents of user_config.json (re-read from disk on every call).
    Only keys defined in config_schema are included.
    '''
    effective = copy.deepcopy(DEFAULTS)
    user = _overrides.load_user_config()
    for field in config_schema.iter_fields():
        module_name = field["config_module"]
        key = field["key"]
        section = user.get(module_name)
        if isinstance(section, dict) and key in section:
            effective[module_name][key] = section[key]
    return effective


def _coerce(field_type: str, value):
    '''
    Coerce an incoming JSON value into the type declared for the field in the
    schema. Raises ValueError on invalid numbers so the caller can reject them.
    '''
    if field_type in ("text", "password", "textarea", "select"):
        return "" if value is None else str(value)

    if field_type == "number":
        if isinstance(value, bool):
            raise ValueError("expected a number, got a boolean")
        if isinstance(value, (int, float)):
            number = value
        else:
            text = str(value).strip()
            if text == "":
                raise ValueError("expected a number, got an empty value")
            number = float(text)
        # Keep whole numbers as ints (the config defaults are ints).
        if isinstance(number, float) and number.is_integer():
            return int(number)
        return number

    if field_type == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    if field_type == "list":
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip() != ""]
        text = str(value).strip()
        if text == "":
            return []
        return [item.strip() for item in text.split(",") if item.strip() != ""]

    # Unknown type: pass through untouched.
    return value


# ===========================================================================
# Bot subprocess management (run / stop / status / logs)
# ===========================================================================
_bot_proc = None
_bot_lock = threading.Lock()


def _bot_command():
    '''The command used to launch the bot. Isolated so tests can monkeypatch it.'''
    return [sys.executable, os.path.join(ROOT, "runAiBot.py")]


def _is_running() -> bool:
    '''True if the tracked bot subprocess exists and has not exited.'''
    global _bot_proc
    if _bot_proc is None:
        return False
    if _bot_proc.poll() is None:
        return True
    # Process has exited; clean up tracking + PID file.
    _bot_proc = None
    _remove_pid_file()
    return False


def _remove_pid_file():
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def _terminate(proc) -> None:
    '''Terminate the subprocess and, where feasible, its child processes.'''
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Kill the whole process tree on Windows.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            # We launched with start_new_session=True, so the child is its own
            # process-group leader; signal the whole group.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass
    # Give it a moment, then force-kill if still alive.
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except Exception:
            pass


@app.route('/')
def home():
    """Serve the control panel single-page app."""
    return render_template('control_panel.html')


@app.route('/history')
def history():
    """Serve the applied-jobs history page."""
    return render_template('index.html')


# The applied-jobs history CSV the bot writes, and how its columns map to the JSON
# keys the history page consumes.
_HISTORY_CSV = 'all_applied_applications_history.csv'
_HISTORY_FIELDS = {
    'Job ID': 'Job_ID',
    'Title': 'Title',
    'Company': 'Company',
    'HR Name': 'HR_Name',
    'HR Link': 'HR_Link',
    'Job Link': 'Job_Link',
    'External Job link': 'External_Job_link',
    'Date Applied': 'Date_Applied',
}


@app.route('/applied-jobs', methods=['GET'])
def get_applied_jobs():
    """Return the applied-jobs history as JSON for the history page."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": "No applications history found yet."}), 404
    try:
        jobs = []
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                jobs.append({key: row.get(col, '') for col, key in _HISTORY_FIELDS.items()})
        return jsonify(jobs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/applied-jobs/<job_id>', methods=['PUT'])
def mark_job_applied(job_id):
    """Stamp one job's 'Date Applied' (matched by Job ID) with the current time."""
    csv_path = os.path.join(PATH, _HISTORY_CSV)
    if not os.path.exists(csv_path):
        return jsonify({"error": f"History file not found at {csv_path}"}), 404
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames
            rows = list(reader)
        matched = False
        for row in rows:
            if row.get('Job ID') == job_id:
                row['Date Applied'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                matched = True
        if not matched:
            return jsonify({"error": f"Job ID {job_id} not found"}), 404
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return jsonify({"message": "Date Applied updated."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ===========================================================================
# Control-panel API
# ===========================================================================
@app.route('/api/schema', methods=['GET'])
def api_schema():
    '''Returns the field schema the UI renders its forms from.'''
    return jsonify(config_schema.SCHEMA)


@app.route('/api/config', methods=['GET'])
def api_get_config():
    '''
    Returns the effective config: pristine defaults overlaid with the current
    user_config.json, grouped by config module (secrets, personals, questions,
    search, settings).
    '''
    return jsonify(_effective_config())


def _apply_config_patch(payload):
    '''
    Validate {section: {key: value}} against the schema, coerce each value to
    its declared type, reject unknown modules/keys and merge into
    user_config.json (read-modify-write).

    Returns (current_config, error_response_or_None). Used by both the Save
    button (POST /api/config) and Lazii-Bot's chat action engine.
    '''
    valid = config_schema.valid_keys()
    unknown = []
    coerced = {}

    for section, values in payload.items():
        if not isinstance(values, dict):
            return {}, (jsonify({"error": f"Section '{section}' must be an object"}), 400)
        if section not in valid:
            unknown.append(section)
            continue
        for key, value in values.items():
            field = valid[section].get(key)
            if field is None:
                unknown.append(f"{section}.{key}")
                continue
            try:
                coerced.setdefault(section, {})[key] = _coerce(field["type"], value)
            except ValueError as err:
                return {}, (jsonify({"error": f"Invalid value for '{section}.{key}': {err}"}), 400)

    if unknown:
        return {}, (jsonify({"error": "Unknown settings rejected", "unknown": unknown}), 400)

    # Read-modify-write user_config.json.
    current = _overrides.load_user_config()
    for section, values in coerced.items():
        target = current.get(section)
        if not isinstance(target, dict):
            target = {}
        target.update(values)
        current[section] = target

    try:
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(current, file, indent=2, ensure_ascii=False)
    except OSError as err:
        return {}, (jsonify({"error": f"Could not save settings: {err}"}), 500)

    return current, None


@app.route('/api/config', methods=['POST'])
def api_save_config():
    '''
    Accepts {config_module: {key: value}}, validates against the schema, coerces
    each value to its declared type, rejects unknown modules/keys, merges into
    user_config.json (read-modify-write) and returns the full saved config.
    '''
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Expected a JSON object of {section: {key: value}}"}), 400
    current, err = _apply_config_patch(payload)
    if err is not None:
        return err[0], err[1]
    return jsonify(current)


# ===========================================================================
# Lazii-Bot: resume list + chat endpoint backed by the local AI layer
# ===========================================================================
_RESUME_DIR = "all resumes"
_RESUME_EXTS = (".pdf", ".docx")

_APPLIED_CSV = 'all_applied_applications_history.csv'
_FAILED_CSV = 'all_failed_applications_history.csv'
_APPLIED_DATE_FMT = '%Y-%m-%d %H:%M:%S'


def _read_history_rows(name):
    '''Rows of one of the bot's history CSVs (empty list if missing/unreadable).'''
    path = os.path.join(PATH, name)
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as file:
            return list(csv.DictReader(file))
    except OSError:
        return []


def _compute_stats():
    '''Application analytics from the applied/failed history CSVs.'''
    from collections import Counter
    day_counts, companies = Counter(), Counter()
    total = 0
    for row in _read_history_rows(_APPLIED_CSV):
        link = (row.get('External Job link') or '').strip()
        date_applied = (row.get('Date Applied') or '').strip()
        counted = link == 'Easy Applied' or (date_applied and date_applied != 'Pending')
        if not counted:
            continue
        total += 1
        company = (row.get('Company') or '').strip()
        if company:
            companies[company] += 1
        try:
            day = datetime.strptime(date_applied, _APPLIED_DATE_FMT).date()
            day_counts[day.isoformat()] += 1
        except ValueError:
            pass
    return {
        "total_applied": total,
        "total_failed": len(_read_history_rows(_FAILED_CSV)),
        "day_counts": dict(sorted(day_counts.items())),
        "top_companies": companies.most_common(8),
    }


@app.route('/api/stats', methods=['GET'])
def api_stats():
    '''Application analytics for the Stats tab and Lazii-Bot's chat context.'''
    return jsonify(_compute_stats())


def _list_resumes():
    '''Resume files available under the "all resumes" folder (project root).'''
    folder = os.path.join(ROOT, _RESUME_DIR)
    if not os.path.isdir(folder):
        return []
    names = []
    for name in sorted(os.listdir(folder)):
        full = os.path.join(folder, name)
        if os.path.isfile(full) and name.lower().endswith(_RESUME_EXTS):
            names.append(f"{_RESUME_DIR}/{name}")
    return names


@app.route('/api/resumes', methods=['GET'])
def api_resumes():
    '''Resumes on disk plus the currently selected default_resume_path.'''
    return jsonify({
        "files": _list_resumes(),
        "current": _effective_config().get("questions", {}).get("default_resume_path", ""),
    })


_LAZII_FALLBACKS = [
    "*pats the couch* Mphf... my brain is unplugged. Flip 'Use AI' in the Account tab and give me a key (or point me at Ollama), then I can change settings for you while you lounge.",
    "Zzz... oh, hey. Right now I'm running on snacks alone. Turn on 'Use AI' in the Account tab and I'll handle settings, resumes and runs from this chat.",
    "*stretches* Comfy couch, empty head. Give me an AI key (Account tab) and I'll earn my spot on these cushions.",
]


def _lazii_field_catalog():
    '''Schema fields the chat is allowed to change (never the secrets section).'''
    catalog = []
    for field in config_schema.iter_fields():
        if field["config_module"] == "secrets":
            continue
        entry = {"section": field["config_module"], "key": field["key"],
                 "type": field["type"], "label": field["label"]}
        if field.get("options"):
            entry["options"] = field["options"]
        catalog.append(entry)
    return catalog


def _lazii_respond(message: str) -> dict:
    '''
    Send the user's message to the configured LLM with Lazii-Bot's persona and
    a strict JSON action contract; apply any settings actions it returns.
    '''
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from modules.ai import connections
    except Exception as err:  # AI stack not importable
        return {"say": "My AI parts are missing (" + str(err) + "). Still on the couch though.", "ai": False}

    # Server-side calls must never pop blocking GUI dialogs.
    try:
        connections._alerts_enabled = False
    except Exception:
        pass

    effective = _effective_config()
    masked = {}
    for section, values in effective.items():
        masked[section] = {
            k: ("***" if section == "secrets" and k in ("password", "llm_api_key") else v)
            for k, v in values.items()
        }
    resumes = _list_resumes()
    stats = _compute_stats()
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    last7 = sum(v for k, v in stats["day_counts"].items() if k >= week_ago)
    hunt_running = _bot_running()

    system = (
        "You are Lazii-Bot, a chubby, scruffy, playful couch-potato robot who hunts jobs for "
        "your owner from The Couch (the control panel). You are lazy-cool but competent: short "
        "punchy replies, light robot-sloth humor, never more than 3 sentences in 'say'.\n\n"
        "You can change the bot's settings for the user by returning actions. Reply with ONLY a "
        "JSON object (no markdown fences, no extra text) shaped like:\n"
        '{"say": "<your reply>", "actions": [{"section": "<module>", "key": "<setting>", "value": <value>}]}\n\n'
        "Rules:\n"
        "1. Allowed sections/keys/types are listed in FIELDS. 'list' values are JSON arrays of "
        "strings, 'number' values are numbers, 'bool' values are true/false. Respect 'options'.\n"
        "2. NEVER touch the 'secrets' section (credentials and API keys). If asked, refuse and "
        "point the user to the Account tab.\n"
        "3. To switch the resume use section 'questions', key 'default_resume_path', value one of "
        "the RESUMES paths exactly.\n"
        "4. SPECIAL ACTIONS that bypass settings: section 'run' with key 'start' or 'stop' starts "
        "or stops the hunt; key 'status' asks for the current run state. Use only when asked.\n"
        "5. Only send actions the user actually asked for. If you did not change anything, send an "
        "empty actions array.\n"
        "6. If a request is vague, make a sensible change anyway and say what you did.\n\n"
        "FIELDS (section.key - type, options where applicable):\n"
        + json.dumps(_lazii_field_catalog(), ensure_ascii=False)
        + "\n\nCURRENT SETTINGS (masked):\n"
        + json.dumps(masked, ensure_ascii=False)
        + "\n\nRESUMES available for default_resume_path:\n"
        + json.dumps(resumes, ensure_ascii=False)
        + "\n\nBOT STATUS: the hunt is currently " + ("RUNNING" if hunt_running else "STOPPED") + ".\n"
        + "STATS: total applications " + str(stats["total_applied"])
        + ", failed " + str(stats["total_failed"])
        + ", last 7 days " + str(last7)
        + ", top companies " + json.dumps(stats["top_companies"][:3]) + ".\n"
    )

    try:
        client = connections.create_ai_client()
        if client is None:
            return {"say": "AI is switched off. Flip 'Use AI' in the Account tab to wake me up.", "ai": False}
        response = client.model.invoke([SystemMessage(content=system), HumanMessage(content=message)])
        raw = response.content if hasattr(response, "content") else str(response)
        if isinstance(raw, list):
            raw = "".join(str(part) for part in raw)
    except Exception as err:
        return {"say": "*coughs up a spring* Brain hiccup: " + str(err)[:200], "ai": True}

    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        return {"say": raw[:600], "ai": True, "applied": [], "errors": []}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"say": raw[:600], "ai": True, "applied": [], "errors": ["could not parse my own JSON - ask me again"]}

    say = str(parsed.get("say") or "Done. *slides back onto the couch*")
    applied, errors, events = [], [], []
    payload = {}
    for action in (parsed.get("actions") or []):
        if not isinstance(action, dict):
            continue
        section = str(action.get("section", "")).strip()
        key = str(action.get("key", "")).strip()
        if section == "secrets":
            errors.append("refused: credentials live only in the Account tab")
            continue
        if section == "run":
            cmd = key.lower()
            if cmd == "start":
                result = _start_bot()
                if result.get("running"):
                    applied.append({"section": "run", "key": "start", "value": True})
                    events.append("the hunt is ON")
                else:
                    errors.append("could not start: " + str(result.get("error") or result.get("message") or "?"))
            elif cmd == "stop":
                _stop_bot()
                applied.append({"section": "run", "key": "stop", "value": True})
                events.append("the hunt is stopped")
            elif cmd == "status":
                events.append("hunt status: " + ("running" if _bot_running() else "stopped"))
            continue
        if not section or not key:
            continue
        payload.setdefault(section, {})[key] = action.get("value")

    if payload:
        current, err = _apply_config_patch(payload)
        if err is not None:
            errors.append(str(err[0].get_json().get("error", "invalid setting")))
        else:
            for section, values in payload.items():
                for key, value in values.items():
                    applied.append({"section": section, "key": key, "value": current.get(section, {}).get(key, value)})

    return {"say": say, "ai": True, "applied": applied, "errors": errors, "events": events}


@app.route('/api/chat', methods=['POST'])
def api_chat():
    '''Talk to Lazii-Bot. May change settings via the AI action engine.'''
    payload = request.get_json(silent=True)
    message = str(payload.get("message") or "").strip() if isinstance(payload, dict) else ""
    if not message:
        return jsonify({"error": "Empty message"}), 400
    if len(message) > 2000:
        return jsonify({"error": "Message too long"}), 400
    try:
        return jsonify(_lazii_respond(message))
    except Exception as err:  # never let a chat turn take the panel down
        return jsonify({"say": "*rolls off the couch* That broke me a little. Try rephrasing?", "errors": [str(err)[:200]]})


# ===========================================================================
# Scout: multi-board job discovery via JobSpy (Indeed, Glassdoor, ZipRecruiter)
# ===========================================================================
_SCOUT_BOARDS = {"linkedin", "indeed", "glassdoor", "ziprecruiter", "google", "bayt", "naukri"}


def _scout_jobs(titles, location, boards, hours, limit):
    '''
    Run JobSpy scrapes for up to 3 search terms and return cleaned records.
    Raises on failure so the caller can turn it into an API error.
    '''
    import pandas as pd
    from jobspy import scrape_jobs

    frames = []
    for term in [t.strip() for t in titles.split(',') if t.strip()][:3]:
        try:
            frames.append(scrape_jobs(
                site_name=boards,
                search_term=term,
                location=location,
                results_wanted=limit,
                hours_old=hours,
                country_indeed='USA',
            ))
        except Exception as err:  # one flaky board/term shouldn't kill the scout
            print(f"scout: term '{term}' failed: {err}", file=sys.stderr)
    if not frames:
        return []
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=['title', 'company'])
    return combined.head(limit * 2).to_dict(orient='records')


@app.route('/api/scout', methods=['GET'])
def api_scout():
    '''
    Discover jobs across multiple boards (no LinkedIn login needed).
    The scrape runs in a worker thread with a hard timeout so the panel never
    hangs longer than promised.
    '''
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    titles = request.args.get('titles', '').strip()
    location = request.args.get('location', '').strip()
    boards = [b.strip().lower() for b in request.args.get('boards', 'indeed,ziprecruiter').split(',')
              if b.strip().lower() in _SCOUT_BOARDS]
    try:
        hours = max(1, min(int(request.args.get('hours', '72')), 336))
        limit = max(1, min(int(request.args.get('limit', '40')), 100))
    except ValueError:
        return jsonify({"error": "hours and limit must be numbers"}), 400
    if not titles:
        return jsonify({"error": "titles required (comma separated)"}), 400
    if not location:
        return jsonify({"error": "location required"}), 400
    if not boards:
        return jsonify({"error": "no valid boards requested"}), 400

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            records = pool.submit(_scout_jobs, titles, location, boards, hours, limit).result(timeout=180)
        except FutureTimeout:
            return jsonify({"error": "scout timed out - try fewer boards or titles"}), 504
        except Exception as err:
            return jsonify({"error": "scout failed: " + str(err)[:250]}), 500

    jobs = []
    for record in records:
        clean = {}
        for k, v in record.items():
            if v is None or (isinstance(v, float) and v != v):  # None / NaN
                v = None
            if hasattr(v, 'isoformat'):
                v = v.isoformat()
            clean[k] = v
        jobs.append(clean)
    return jsonify(jobs)


def _bot_running():
    '''True if the bot subprocess is currently alive (refreshes tracking).'''
    with _bot_lock:
        return _is_running()


def _start_bot():
    '''Start the bot subprocess if it isn't already running. Returns a JSON-able dict.'''
    global _bot_proc
    with _bot_lock:
        if _is_running():
            return {"running": True, "pid": _bot_proc.pid,
                    "message": "The tool is already running."}
        try:
            # Truncate the log at the start of each run.
            log_file = open(LOG_PATH, "w", encoding="utf-8")
            popen_kwargs = {
                "cwd": ROOT,
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                popen_kwargs["start_new_session"] = True
            _bot_proc = subprocess.Popen(_bot_command(), **popen_kwargs)
        except Exception as err:
            return {"running": False, "error": str(err)}
        try:
            with open(PID_PATH, "w", encoding="utf-8") as pid_file:
                pid_file.write(str(_bot_proc.pid))
        except OSError:
            pass
        return {"running": True, "pid": _bot_proc.pid}


def _stop_bot():
    '''Stop the running bot subprocess (and its children where possible).'''
    global _bot_proc
    with _bot_lock:
        was_running = _bot_proc is not None
        if _bot_proc is not None:
            _terminate(_bot_proc)
            _bot_proc = None
        _remove_pid_file()
        return {"running": False, "stopped": was_running}


@app.route('/api/run', methods=['POST'])
def api_run():
    '''Starts the bot as a subprocess if it isn't already running.'''
    return jsonify(_start_bot())


@app.route('/api/stop', methods=['POST'])
def api_stop():
    '''Stops the running bot subprocess (and its children where possible).'''
    return jsonify(_stop_bot())


@app.route('/api/status', methods=['GET'])
def api_status():
    '''Reports whether the bot subprocess is currently running.'''
    with _bot_lock:
        running = _is_running()
        pid = _bot_proc.pid if (running and _bot_proc is not None) else None
        return jsonify({"running": running, "pid": pid})


@app.route('/api/logs', methods=['GET'])
def api_logs():
    '''
    Returns the run log starting from byte offset ?offset=N, plus the byte
    offset to read from next time. The UI polls this while the bot runs.
    '''
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0
    if not os.path.exists(LOG_PATH):
        return jsonify({"content": "", "next_offset": 0})
    try:
        with open(LOG_PATH, "rb") as log_file:
            log_file.seek(0, os.SEEK_END)
            size = log_file.tell()
            if offset > size:
                # Log was truncated (a new run started); start over.
                offset = 0
            log_file.seek(offset)
            data = log_file.read()
        content = data.decode("utf-8", errors="replace")
        return jsonify({"content": content, "next_offset": offset + len(data)})
    except OSError as err:
        return jsonify({"content": "", "next_offset": offset, "error": str(err)})


def _resolve_port(preferred: int = 5000) -> int:
    '''
    Pick a port to serve on. Honors the PORT environment variable (the launcher
    scripts set it). Otherwise tries `preferred`, and if that's taken - e.g. port
    5000 is used by AirPlay Receiver on macOS - asks the OS for any free port so
    the panel always starts instead of crashing with "address already in use".
    '''
    import socket
    requested = os.environ.get("PORT", "").strip()
    if requested.isdigit():
        return int(requested)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


if __name__ == '__main__':
    # SECURITY: localhost only, debug OFF. This app handles credentials.
    port = _resolve_port(5000)
    url = "http://127.0.0.1:%d" % port
    print(
        "\n  Control panel ready at:  %s\n"
        "  Keep this window open while you use the tool; close it to stop.\n" % url,
        flush=True,
    )
    # The launcher scripts set PANEL_OPEN_BROWSER=1 so the browser opens itself,
    # to the right port, cross-platform. Running `python app.py` by hand won't.
    if os.environ.get("PANEL_OPEN_BROWSER", "").strip() not in ("", "0", "false", "False"):
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
