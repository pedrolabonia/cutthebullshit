"""Check that this machine is ready to run the pipeline: settings, folders, Python packages, ffmpeg, Photoshop and
After Effects (installed, scripting allowed), and how many frames it will work on at once.

    cutthebullshit doctor            checks only, opens nothing
    cutthebullshit doctor --apps     also asks Photoshop and After Effects to answer a script (starts them if needed)

Exits 1 if anything the pipeline needs is missing (FAIL); WARN lines are worth a look but don't stop a run.
"""

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile

from . import apps
from . import config

LINES = []


def report(level, what, detail=""):
    LINES.append(level)
    print("  %-4s  %-28s %s" % (level, what, detail))


def check_folder(name, path, need_gb):
    if not path:
        report("FAIL", name, "not set")
        return
    probe = path
    while not os.path.isdir(probe) and os.path.dirname(probe) != probe:
        probe = os.path.dirname(probe)
    if not os.access(probe, os.W_OK):
        report("FAIL", name, "%s (can't write in %s)" % (path, probe))
        return
    try:
        with tempfile.NamedTemporaryFile(dir=probe):
            pass
    except OSError as e:
        report("FAIL", name, "%s (%s)" % (path, e))
        return
    free = shutil.disk_usage(probe).free / 1e9
    exists = "" if os.path.isdir(path) else ", will be created"
    report("ok" if free >= need_gb else "WARN", name,
           "%s (%.0f GB free%s%s)" % (path, free, exists, "" if free >= need_gb else "; a run can take %d GB+" % need_gb))


def check_packages():
    v = sys.version_info
    report("ok" if v >= (3, 11) else "FAIL", "Python", "%d.%d.%d  %s" % (v[0], v[1], v[2], sys.executable))
    for mod, why in (("numpy", ""), ("cv2", "opencv-python-headless"), ("rawpy", "RAW development"),
                     ("imageio_ffmpeg", "ffmpeg for previews / ProRes")):
        try:
            m = importlib.import_module(mod)
            report("ok", mod, getattr(m, "__version__", ""))
        except Exception as e:
            report("FAIL", mod, "missing (%s) - pip install -e . in the repo" % (why or e))
    try:
        import OpenEXR  # noqa: F401
        report("ok", "OpenEXR", "(only for runs made before the PNG switch)")
    except Exception:
        report("ok", "OpenEXR", "not installed - only needed for old EXR runs (pip install -e '.[exr]')")
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30)
        ok = r.returncode == 0 and "prores_ks" in r.stdout
        report("ok" if ok else "FAIL", "ffmpeg", exe if ok else "%s doesn't run or has no prores_ks" % exe)
    except Exception as e:
        report("FAIL", "ffmpeg", str(e))


def check_apps(ping):
    ps, ae = apps.PHOTOSHOP, apps.AFTER_EFFECTS
    src = lambda app: " (from settings)" if apps.from_settings(app) else ""
    report("ok" if ps else "FAIL", "Photoshop", (ps + src("photoshop")) if ps else
           "not found; set photoshop_app in the settings")
    report("ok" if ae else "FAIL", "After Effects", (ae + src("ae")) if ae else
           "not found; set after_effects_app (or leave out the aecomps step)")
    if ae:
        allowed = apps.ae_scripting_allowed()
        if allowed is None:
            report("WARN", "AE scripting", "couldn't read the prefs; make sure Settings > Scripting & Expressions > "
                   "Allow Scripts to Write Files and Access Network is on")
        else:
            report("ok" if allowed else "FAIL", "AE scripting", "files + network allowed" if allowed else
                   "turn on Settings > Scripting & Expressions > Allow Scripts to Write Files and Access Network")
    what, ok_text, warning = apps.DIALOGS
    can = apps.can_close_dialogs()
    report("ok" if can else "WARN", what, ok_text if can else warning)
    for level, what, detail in apps.platform_checks():
        report(level, what, detail)
    if ping:
        for app, name in (("photoshop", ps), ("ae", ae)):
            if name:
                ok = apps.app_alive(app)
                report("ok" if ok else "FAIL", "%s answers" % apps.WHAT[app], "" if ok else "no answer: " + apps.NO_ANSWER_HINT)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apps", action="store_true", help="also ask Photoshop and After Effects to answer (starts them)")
    args = ap.parse_args(argv)

    print("settings")
    report("ok" if config.SETTINGS_FILE else "WARN", "settings file",
           config.SETTINGS_FILE or "none found - using defaults (see cutthebullshit.example.toml)")
    check_folder("work folder", config.WORK_DIR, 50)
    check_folder("output folder", config.OUTPUT_DIR, 20)
    if config.SOURCE_ROOT:
        report("ok" if os.path.isdir(config.SOURCE_ROOT) else "WARN", "source_root", config.SOURCE_ROOT)
    try:
        kind, val = config.parse_bg(config.BG)
        report("ok", "background", "none (middle grey)" if kind == "none" else (val if kind == "image" else str(val)))
    except ValueError as e:
        report("FAIL", "background", str(e))
    report("ok", "photos", "folders named %r, %d extensions, crop %s, half size %s"
           % (config.PHOTO_FOLDER, len(config.PHOTO_EXT), config.CROP or "none", config.HALF_SIZE))

    print("python")
    check_packages()

    print("apps")
    if not apps.SUPPORTED:
        report("FAIL", "platform", "%s: driving Photoshop / After Effects works on macOS and Windows only" % sys.platform)
    else:
        check_apps(args.apps)

    print("workers (frames at once)")
    from .passes import PASSES_GB
    from .prep import PREP_GB
    from .layers import LAYERS_GB
    report("ok", "prep / passes / layers", "%d / %d / %d  (%d cores)" % (
        config.default_workers(PREP_GB), config.default_workers(PASSES_GB), config.default_workers(LAYERS_GB),
        os.cpu_count() or 0))

    bad = LINES.count("FAIL")
    print("\n%s" % ("ready" if not bad else "%d problem(s) to fix" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
