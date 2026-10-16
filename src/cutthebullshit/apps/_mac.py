"""macOS backend of cutthebullshit.apps: AppleScript (osascript), pkill / open -a, System Events, caffeinate.

Every function takes the app's name as found by apps.find_app ("Adobe After Effects 2026") and the app key
("ae" / "photoshop") where it matters; apps/__init__.py is the interface the rest of the pipeline calls."""

import os
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
AE_PREFS = os.path.expanduser("~/Library/Preferences/Adobe/After Effects")
NO_ANSWER_HINT = ("allow your terminal to control it (System Settings > Privacy & Security > Automation), "
                  "and close any dialog open in the app")
DIALOGS = ("Accessibility", "can close app dialogs",
           "supervise can't close crash / alert dialogs (System Settings > Privacy & Security > Accessibility)")


def find_installed(family):
    """Name of the newest installed "<family> <year>" (Adobe installs them as /Applications/<name>/<name>.app)."""
    found = []
    for d in ("/Applications", os.path.expanduser("~/Applications")):
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            m = re.match(r"^%s (\d{4})(\.app)?$" % re.escape(family), n)
            app = n[:-4] if n.endswith(".app") else n
            if m and (os.path.isdir(os.path.join(d, n, app + ".app")) or n.endswith(".app")):
                found.append((int(m.group(1)), app))
    return max(found)[1] if found else None


def osa(lines, timeout):
    """(returncode, stdout, stderr) of an AppleScript given as lines; returncode -1 on timeout."""
    cmd = ["osascript"]
    for line in lines:
        cmd += ["-e", line]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"


def _quote(text):
    return '"%s"' % text.replace("\\", "\\\\").replace('"', '\\"')


def run_ae_script(name, jsx_path, timeout):
    # AppleScript gives up after 2 min by default while After Effects keeps working: raise its timeout to ours
    osa(["with timeout of %d seconds" % timeout, "tell application %s to DoScriptFile %s" % (_quote(name), _quote(jsx_path)),
         "end timeout"], timeout + 60)


def run_ps_javascript(name, code, path, timeout):
    if path:
        js = '(read POSIX file %s as «class utf8»)' % _quote(path)
    else:
        js = _quote(code)
    rc, out, err = osa(["with timeout of %d seconds" % timeout, "tell application %s to do javascript %s" % (_quote(name), js),
                        "end timeout"], timeout + 60)
    if rc == -1:
        return False, "no answer in %d min" % max(1, timeout // 60)
    return rc == 0, out if rc == 0 else (out + " " + err).strip()


def kill_app(name, app):
    pattern = "%s.app/Contents/MacOS/After Effects" % name if app == "ae" else "%s.app/Contents/MacOS" % name
    subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)


def launch_app(name, app):
    subprocess.run(["open", "-a", name], capture_output=True)


def can_close_dialogs():
    """Accessibility permission for the app this runs from (needed to click other apps' buttons)."""
    rc, _, _ = osa(['tell application "System Events" to tell process "Finder" to get count of windows'], 30)
    return rc == 0


def close_dialogs(name, app, force):
    process = "After Effects" if app == "ae" else name
    try:
        r = subprocess.run(["osascript", os.path.join(HERE, "dismiss_dialogs.applescript"), process]
                           + (["force"] if force else []), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        if "assistive access" in r.stderr:
            raise PermissionError("no Accessibility permission")
        return ""
    return r.stdout.strip()


def keep_awake():
    # caffeinate ends by itself when this process does (-w)
    subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def platform_checks():
    return []
