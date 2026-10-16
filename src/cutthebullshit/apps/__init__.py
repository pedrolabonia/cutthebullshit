"""Photoshop and After Effects from Python: find them, run a script in them, check they answer, restart them,
close their dialogs, keep the machine awake.

This is the only place that knows how the apps are driven on this platform: _mac.py (AppleScript) is the backend on
macOS, _unsupported.py everywhere else for now. A Windows backend is one more module with the same functions.
Apps are named by key: "photoshop" or "ae".
"""

import json
import os
import sys
import time

from ..config import SETTINGS, state_path

if sys.platform == "darwin":
    from . import _mac as _backend
else:
    from . import _unsupported as _backend

SUPPORTED = sys.platform == "darwin"
WHAT = {"photoshop": "Photoshop", "ae": "After Effects"}
SETTING = {"photoshop": "photoshop_app", "ae": "after_effects_app"}
FAMILY = {"photoshop": "Adobe Photoshop", "ae": "Adobe After Effects"}


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
    """Run a .jsx file in After Effects and wait for it (up to timeout s). Scripts hand their results back in a file:
    the caller reads it (it can land a moment after this returns)."""
    _backend.run_ae_script(need_app("ae"), jsx_path, timeout)


def run_ps_javascript(code=None, path=None, timeout=900):
    """Run JavaScript in Photoshop, as a string or a .jsx file: (ok, what the script returned, or the error)."""
    return _backend.run_ps_javascript(need_app("photoshop"), code, path, timeout)


def ps_alive():
    ok, out = run_ps_javascript("'ps-ok'", timeout=60)
    return ok and "ps-ok" in out


AE_PING, AE_PING_RESULT = state_path("_ae_ping.jsx"), state_path("ae_ping.txt")


def ae_alive():
    with open(AE_PING, "w") as fh:
        fh.write('var f = new File(%s); f.open("w"); f.write("ae-ok"); f.close();' % json.dumps(AE_PING_RESULT))
    if os.path.exists(AE_PING_RESULT):
        os.remove(AE_PING_RESULT)
    run_ae_script(AE_PING, timeout=120)
    for _ in range(20):
        if os.path.exists(AE_PING_RESULT):
            return open(AE_PING_RESULT).read().strip() == "ae-ok"
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
    """Can this process click other apps' dialogs (macOS: Accessibility permission)?"""
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
    """After Effects' "Allow Scripts to Write Files and Access Network": True / False / None (unknown)."""
    return _backend.ae_scripting_allowed()
