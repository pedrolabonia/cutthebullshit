"""Photoshop and After Effects from Python: find them, run a script in them, check they answer, restart them,
close their dialogs, keep the machine awake; plus the few OS calls that differ between macOS and Windows.

This is the only place that knows how the apps are driven on this platform: _mac.py (AppleScript) on macOS,
_windows.py (AfterFX.exe -r, Photoshop's COM interface, pywinauto) on Windows, _unsupported.py everywhere else.
Apps are named by key: "photoshop" or "ae".
"""

import glob
import json
import os
import re
import signal
import subprocess
import sys
import time

from ..config import SETTINGS, state_path

if sys.platform == "darwin":
    from . import _mac as _backend
elif sys.platform == "win32":
    from . import _windows as _backend
else:
    from . import _unsupported as _backend

SUPPORTED = sys.platform in ("darwin", "win32")
WHAT = {"photoshop": "Photoshop", "ae": "After Effects"}
SETTING = {"photoshop": "photoshop_app", "ae": "after_effects_app"}
FAMILY = {"photoshop": "Adobe Photoshop", "ae": "Adobe After Effects"}
NO_ANSWER_HINT = _backend.NO_ANSWER_HINT      # what to check when an app doesn't answer a script
DIALOGS = _backend.DIALOGS                    # (what, ok text, warning) for the "can close dialogs" check


def find_app(app):
    """The app's name: photoshop_app / after_effects_app in the settings, else the newest installed one; None if none."""
    return SETTINGS.get(SETTING[app]) or _backend.find_installed(FAMILY[app])


NAMES = {app: find_app(app) for app in WHAT}
PHOTOSHOP, AFTER_EFFECTS = NAMES["photoshop"], NAMES["ae"]


def from_settings(app):
    return bool(SETTINGS.get(SETTING[app]))


def need_app(app):
    """The app's name, or stop with what to do when it isn't installed."""
    if not SUPPORTED:
        raise SystemExit(_backend.WHY)
    if not NAMES[app]:
        raise SystemExit("%s not found; set %s in the settings" % (WHAT[app], SETTING[app]))
    return NAMES[app]


def run_ae_script(jsx_path, timeout=3600):
    """Run a .jsx file (UTF-8) in After Effects and wait until it has finished (up to timeout s). Scripts hand their
    results back in a file; the caller reads it (it can land a moment after this returns)."""
    _backend.run_ae_script(need_app("ae"), jsx_path, timeout)


def run_ps_javascript(code=None, path=None, timeout=900):
    """Run JavaScript in Photoshop, as a string or a .jsx file (UTF-8): (ok, what the script returned, or the error)."""
    return _backend.run_ps_javascript(need_app("photoshop"), code, path, timeout)


def ps_alive():
    ok, out = run_ps_javascript("'ps-ok'", timeout=60)
    return ok and "ps-ok" in out


AE_PING, AE_PING_RESULT = state_path("_ae_ping.jsx"), state_path("ae_ping.txt")


def ae_alive():
    with open(AE_PING, "w", encoding="utf-8") as fh:
        fh.write('var f = new File(%s); f.open("w"); f.write("ae-ok"); f.close();' % json.dumps(AE_PING_RESULT))
    if os.path.exists(AE_PING_RESULT):
        os.remove(AE_PING_RESULT)
    run_ae_script(AE_PING, timeout=120)
    for _ in range(20):
        if os.path.exists(AE_PING_RESULT):
            with open(AE_PING_RESULT, encoding="utf-8", errors="replace") as fh:
                return fh.read().strip() == "ae-ok"
        time.sleep(0.5)
    return False


ALIVE = {"photoshop": ps_alive, "ae": ae_alive}


def app_alive(app):
    """Does the app answer a script?"""
    return ALIVE[app]()


def kill_app(app):
    _backend.kill_app(need_app(app), app)


def launch_app(app):
    _backend.launch_app(need_app(app), app)


def can_close_dialogs():
    """Can this process click other apps' dialogs (macOS: Accessibility permission; Windows: pywinauto installed)?"""
    return _backend.can_close_dialogs()


def close_dialogs(app, force=False):
    """Close the app's modal dialogs (crash recovery, autosave, scratch disk, alerts): what was clicked, "" if nothing.
    force: if no dialog button was found, bring the app to the front and press Return.
    Raises PermissionError when this process isn't allowed to click other apps' dialogs."""
    return _backend.close_dialogs(need_app(app), app, force)


def keep_awake():
    """Keep the machine from sleeping until this process ends."""
    _backend.keep_awake()


def ae_scripting_allowed():
    """After Effects' "Allow Scripts to Write Files and Access Network", from the newest version's prefs file:
    True / False / None (unknown)."""
    root = _backend.AE_PREFS
    if not root:
        return None

    def ver(p):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(p))] or [0]
    for d in sorted(glob.glob(os.path.join(root, "*")), key=ver, reverse=True):
        for f in glob.glob(os.path.join(d, "*Prefs.txt")):
            with open(f, encoding="utf-8", errors="replace") as fh:
                m = re.search(r'"Pref_SCRIPTING_FILE_NETWORK_SECURITY" = "?(\d+)', fh.read())
            if m:
                return m.group(1) == "1"
    return None


def platform_checks():
    """Extra setup checks for this platform: [(level, what, detail)] with level ok / WARN / FAIL (cutthebullshit doctor)."""
    return _backend.platform_checks()


# ---------------------------------------------------------------- processes (the pipeline's own jobs)

def process_group():
    """Popen arguments that start a job in its own process group, so kill_tree takes its workers down with it."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(pid):
    """Kill a job started with process_group() and every process it started."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
