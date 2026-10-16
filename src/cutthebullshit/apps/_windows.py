"""Windows backend of cutthebullshit.apps (not yet tested on a Windows machine).

    After Effects   AfterFX.exe -r <script.jsx>: hands the script to the running After Effects (starts it if needed).
                    The script is wrapped so it writes a marker file when it ends: AfterFX.exe -r doesn't wait.
    Photoshop       its COM interface (pywin32): Photoshop.Application.DoJavaScript, in a separate Python process
                    (win_ps_call.py) so a Photoshop that hangs can be timed out and the call killed.
    dialogs         pywinauto (UI Automation), in a separate process too (win_dialogs.py).
    restart         taskkill /F /T /IM <exe>, then start the .exe.
    keep awake      SetThreadExecutionState.

Every function takes the app's name as found by apps.find_app: "Adobe After Effects 2026" (looked up under
Program Files\\Adobe) or the full path of AfterFX.exe / Photoshop.exe (after_effects_app / photoshop_app in the
settings). Windows-only modules are imported inside the functions, so this file imports anywhere (for checks).
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
AE_PREFS = os.path.join(os.environ.get("APPDATA", ""), "Adobe", "After Effects") if os.environ.get("APPDATA") else None
NO_ANSWER_HINT = ("close any dialog open in the app; the app and this tool must run as the same user, both as "
                  "administrator or both not")
DIALOGS = ("dialog control", "can close app dialogs (pywinauto)",
           "pywinauto is missing: supervise can't close crash / alert dialogs (pip install pywinauto)")
EXE = {"ae": os.path.join("Support Files", "AfterFX.exe"), "photoshop": "Photoshop.exe"}
REGISTRY = {"Adobe After Effects": (r"SOFTWARE\Adobe\After Effects", "ae"),
            "Adobe Photoshop": (r"SOFTWARE\Adobe\Photoshop", "photoshop")}
NO_WINDOW = 0x08000000                       # CREATE_NO_WINDOW: helper processes don't flash a console
DETACHED = 0x00000008 | 0x00000200           # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: outlives this process
_found = {}                                  # app name -> .exe found by find_installed


def _program_files():
    roots = []
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        v = os.environ.get(key)
        if v and v not in roots:
            roots.append(v)
    return roots


def _registry_installs(family):
    """{name: exe} from the registry: Adobe writes each version's install folder under HKLM\\SOFTWARE\\Adobe\\<app>."""
    key_path, app = REGISTRY[family]
    out = {}
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sub:
                        for value in ("InstallPath", "ApplicationPath", "Path"):
                            try:
                                folder = winreg.QueryValueEx(sub, value)[0]
                            except OSError:
                                continue
                            exe = os.path.join(folder, os.path.basename(EXE[app]))
                            if os.path.isfile(exe):
                                top = os.path.dirname(folder.rstrip("\\/")) if app == "ae" else folder.rstrip("\\/")
                                out[os.path.basename(top)] = exe
                except OSError:
                    continue
    except (ImportError, OSError):
        pass
    return out


def find_installed(family):
    """Name of the newest installed "<family> <year>": Program Files\\Adobe\\<name>, else the registry."""
    app = REGISTRY[family][1]
    found = {}
    for root in _program_files():
        adobe = os.path.join(root, "Adobe")
        try:
            names = os.listdir(adobe)
        except OSError:
            continue
        for n in names:
            exe = os.path.join(adobe, n, EXE[app])
            if re.match(r"^%s \d{4}$" % re.escape(family), n) and os.path.isfile(exe):
                found[n] = exe
    if not found:
        found = {n: e for n, e in _registry_installs(family).items() if re.match(r"^%s \d{4}$" % re.escape(family), n)}
    if not found:
        return None
    _found.update(found)
    return max(found, key=lambda n: int(n.rsplit(" ", 1)[1]))


def _exe(name, app):
    """The .exe of an app name (or the name itself when the settings give the full path)."""
    if name.lower().endswith(".exe") and os.path.isfile(name):
        return name
    if name in _found:
        return _found[name]
    for root in _program_files():
        exe = os.path.join(root, "Adobe", name, EXE[app])
        if os.path.isfile(exe):
            return exe
    setting = "after_effects_app" if app == "ae" else "photoshop_app"
    raise SystemExit("can't find %s for %r: set %s in the settings to its full path"
                     % (os.path.basename(EXE[app]), name, setting))


def _utf8_env():
    return dict(os.environ, PYTHONIOENCODING="utf-8")


# ---------------------------------------------------------------- After Effects

WRAPPER = """// written by cutthebullshit: runs %(jsx)s, then writes %(done)s (AfterFX.exe -r doesn't wait for scripts)
var __ctb_error = "";
try {
    var __ctb_f = new File(%(jsx)s);
    __ctb_f.encoding = "UTF-8";
    __ctb_f.open("r");
    var __ctb_src = __ctb_f.read();
    __ctb_f.close();
    eval(__ctb_src);
} catch (__ctb_e) {
    __ctb_error = String(__ctb_e);       // an uncaught error would open a dialog that blocks After Effects
} finally {
    var __ctb_d = new File(%(done)s);
    __ctb_d.encoding = "UTF-8";
    __ctb_d.open("w");
    __ctb_d.write(__ctb_error ? "error: " + __ctb_error : "done");
    __ctb_d.close();
}
"""


def run_ae_script(name, jsx_path, timeout):
    exe = _exe(name, "ae")
    done, wrapper = jsx_path + ".done.txt", jsx_path + ".run.jsx"
    if os.path.exists(done):
        os.remove(done)
    with open(wrapper, "w", encoding="utf-8") as fh:
        fh.write(WRAPPER % {"jsx": json.dumps(jsx_path), "done": json.dumps(done)})
    # with After Effects running this process only hands the script over; otherwise it is After Effects itself
    subprocess.Popen([exe, "-r", wrapper], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=DETACHED, close_fds=True)
    end = time.time() + timeout
    while time.time() < end:
        if os.path.exists(done):
            time.sleep(0.2)                  # let the marker's writer close it
            return
        time.sleep(0.5)


# ---------------------------------------------------------------- Photoshop

def run_ps_javascript(name, code, path, timeout):
    _exe(name, "photoshop")                  # stop early with a clear message when it isn't installed
    cmd = [sys.executable, os.path.join(HERE, "win_ps_call.py")] + ([path] if path else [])
    try:
        r = subprocess.run(cmd, input=None if path else code, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=_utf8_env(), creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return False, "no answer in %d min" % max(1, timeout // 60)
    out, err = r.stdout.strip(), r.stderr.strip()
    return r.returncode == 0, out if r.returncode == 0 else (out + " " + err).strip()


# ---------------------------------------------------------------- restart, dialogs, sleep

def kill_app(name, app):
    subprocess.run(["taskkill", "/F", "/T", "/IM", os.path.basename(_exe(name, app))], capture_output=True,
                   creationflags=NO_WINDOW)


def launch_app(name, app):
    subprocess.Popen([_exe(name, app)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=DETACHED, close_fds=True)


def can_close_dialogs():
    return importlib.util.find_spec("pywinauto") is not None


def close_dialogs(name, app, force):
    if not can_close_dialogs():
        raise PermissionError("pywinauto is not installed")
    cmd = [sys.executable, os.path.join(HERE, "win_dialogs.py"), os.path.basename(_exe(name, app))] + (["force"] if force else [])
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120, env=_utf8_env(),
                           creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def keep_awake():
    import ctypes
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
    # holds while the calling (main) thread lives, i.e. until this process ends
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)


# ---------------------------------------------------------------- setup checks (cutthebullshit doctor)

def _long_paths():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1
    except (ImportError, OSError):
        return None


def platform_checks():
    out = []
    ok = importlib.util.find_spec("win32com") is not None
    out.append(("ok" if ok else "FAIL", "pywin32", "drives Photoshop (COM)" if ok else
                "missing: Photoshop can't be driven (pip install pywin32)"))
    lp = _long_paths()
    out.append(("ok" if lp else "WARN", "long paths", "enabled" if lp else
                "Windows limits paths to 260 characters: keep the work / output folders short (e.g. D:\\ctb), or turn "
                "on long paths (Group Policy > Enable Win32 long paths, or LongPathsEnabled = 1 in the registry)"))
    return out
