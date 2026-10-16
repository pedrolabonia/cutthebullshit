"""Backend for platforms without Photoshop / After Effects control yet (everything but macOS).

The image steps (prep, passes, layers, preview, prores, qc) don't need the apps and still run; cleanplate, aecomps
and supervise stop with a clear message. A Windows backend goes next to _mac.py with the same functions
(AfterFX.exe -r for After Effects, Photoshop's COM interface, taskkill, pywinauto, SetThreadExecutionState)."""

import sys

WHY = "driving Photoshop / After Effects is macOS-only for now (this is %s)" % sys.platform


def _no(*_):
    raise SystemExit(WHY)


find_installed = lambda family: None
run_ae_script = run_ps_javascript = kill_app = launch_app = close_dialogs = _no
can_close_dialogs = lambda: False
keep_awake = lambda: None
platform_checks = lambda: []
AE_PREFS = None
NO_ANSWER_HINT = WHY
DIALOGS = ("dialogs", "", WHY)
