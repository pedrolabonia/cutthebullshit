"""Close the modal dialogs of one app (Windows): crash recovery, autosave, scratch disk warnings, error alerts, so it
can be scripted again. The Windows twin of dismiss_dialogs.applescript (apps/_windows.py runs it).

    python win_dialogs.py <process .exe name> [force]   ->  "window -> button" for each one closed, "; "-separated

Looks at the app's windows other than its main one (and dialogs inside the main one) and clicks the first safe
button it finds. With "force", if nothing was clicked it brings the app to the front and presses Enter (an app
that stopped answering almost always has a dialog up; Enter = its default button). Uses pywinauto (UI Automation).
"""

import csv
import subprocess
import sys

PREFS = ["OK", "Continue", "Don't Send", "Not Now", "Don't Recover", "Skip", "Ignore", "No", "Don't Save"]


def pids(exe):
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % exe, "/FO", "CSV", "/NH"], capture_output=True,
                       text=True, creationflags=0x08000000)
    out = []
    for row in csv.reader(r.stdout.splitlines()):
        if len(row) > 1 and row[0].lower() == exe.lower() and row[1].isdigit():
            out.append(int(row[1]))
    return out


def label(ctrl):
    try:
        text = ctrl.window_text()
    except Exception:
        return ""
    return text.replace("&", "").replace("’", "'").strip()


def area(w):
    try:
        r = w.rectangle()
        return max(0, r.width()) * max(0, r.height())
    except Exception:
        return 0


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    exe, force = sys.argv[1], len(sys.argv) > 2
    from pywinauto import Desktop
    from pywinauto.keyboard import send_keys
    desk = Desktop(backend="uia")
    wins = []
    for pid in pids(exe):
        try:
            wins += desk.windows(process=pid, visible_only=True)
        except Exception:
            pass
    if not wins:
        return 0
    main_win = max(wins, key=area)                       # dialogs are small; the main window is not
    targets = [w for w in wins if w is not main_win]
    for w in wins:
        try:
            targets += w.children(control_type="Window")  # dialogs that live inside a window
        except Exception:
            pass
    out = []
    for t in targets:
        try:
            buttons = t.descendants(control_type="Button")
        except Exception:
            continue
        names = [(label(b), b) for b in buttons]
        for pref in PREFS:
            hit = next((b for n, b in names if n == pref), None)
            if hit is None:
                continue
            try:
                try:
                    hit.invoke()
                except Exception:
                    hit.click_input()
                out.append("%s -> %s" % (label(t), pref))
            except Exception:
                pass
            break
    if force and not out:
        try:
            main_win.set_focus()
            send_keys("{ENTER}")
            out.append("(no dialog found) -> Enter")
        except Exception:
            pass
    print("; ".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
