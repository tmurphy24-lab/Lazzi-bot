'''
Desktop app launcher for the LinkedIn Auto Job Applier.

Starts the local control panel (app.py's Flask server) on 127.0.0.1 and opens
it in a standalone Edge app-mode window with a dedicated profile, so it looks
and behaves like a normal desktop application: no tabs, no address bar, its
own taskbar identity. Closing the window stops the app.

Run it with the venv's pythonw.exe (see desktop.bat) for a windowless launch.
'''

import os
import socket
import subprocess
import sys
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

EDGE_CANDIDATES = (
    os.path.join(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
                 r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                 r"Microsoft\Edge\Application\msedge.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Edge\Application\msedge.exe"),
)

PROFILE_DIR = os.path.join(PROJECT_ROOT, ".edge-profile")


def resolve_port(preferred):
    '''Return preferred if free, else a random free localhost port.'''
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
        except OSError:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]
        return preferred


def wait_for_server(port, timeout=20):
    '''Block until the local server accepts connections (or timeout).'''
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
            check.settimeout(1)
            if check.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def find_edge():
    for candidate in EDGE_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def main():
    from app import app as flask_app  # imports the control panel (no server yet)

    port = resolve_port(5000)
    url = "http://127.0.0.1:%d" % port

    server = threading.Thread(
        target=lambda: flask_app.run(host="127.0.0.1", port=port, debug=False),
        daemon=True,
    )
    server.start()

    if not wait_for_server(port):
        print("Control panel failed to start on %s" % url, file=sys.stderr)
        sys.exit(1)

    edge = find_edge()
    if edge is None:
        # No Edge available - fall back to the default browser.
        import webbrowser
        webbrowser.open(url)
        print("Desktop window unavailable (Edge not found); opened default browser at %s" % url)
        print("Press Ctrl+C in a console to stop, or close this via Task Manager.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            sys.exit(0)

    os.makedirs(PROFILE_DIR, exist_ok=True)
    window = subprocess.Popen([
        edge,
        "--app=" + url,
        "--user-data-dir=" + PROFILE_DIR,
        "--window-size=1280,900",
        "--no-first-run",
        "--no-default-browser-check",
    ])

    # Keep serving until the desktop window is closed.
    window.wait()


if __name__ == "__main__":
    main()
