"""Run JavaScript in Photoshop through its COM interface (Windows): a separate process, so a Photoshop that hangs
can be timed out and this call killed (apps/_windows.py runs it).

    python win_ps_call.py [script.jsx]       (no file: the script is read from stdin)

Prints what the script returned; on an error, prints it to stderr and exits 1. Text is UTF-8 both ways.
"""

import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as fh:
            code = fh.read()
    else:
        sys.stdin.reconfigure(encoding="utf-8")
        code = sys.stdin.read()
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        print("pywin32 is not installed (pip install pywin32)", file=sys.stderr)
        return 1
    pythoncom.CoInitialize()
    try:
        try:
            app = win32com.client.GetActiveObject("Photoshop.Application")     # the Photoshop already running
        except Exception:
            app = win32com.client.Dispatch("Photoshop.Application")            # starts it
        result = app.DoJavaScript(code)
    except Exception as e:                                                       # pywintypes.com_error and friends
        info = getattr(e, "excepinfo", None)
        print((info[2] if info and info[2] else str(e)).strip(), file=sys.stderr)
        return 1
    finally:
        pythoncom.CoUninitialize()
    sys.stdout.write("" if result is None else str(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
