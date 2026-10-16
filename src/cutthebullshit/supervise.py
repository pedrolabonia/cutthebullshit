"""Unattended run: the whole workflow over many folders, with a watchdog, app restarts and retries.

Runs cutthebullshit run one RAW folder at a time (prep, cleanplate, passes, layers, preview, prores) in one RUN, then
After Effects over everything that got through. Made to be left alone:
  - hang:   no output for HANG_MIN minutes, or Photoshop not answering twice on a frame -> the job is killed, the app
            of the step it was in is restarted, and the folder is retried
  - crash:  before every attempt Photoshop must answer (After Effects before the AE steps); an app that doesn't is
            killed and relaunched
  - errors: every step resumes, so a retry continues where the last attempt stopped; after ATTEMPTS failed tries
            the folder builds what has clean plates (passes, layers, preview) and is marked partial / failed, and
            the run moves on
  - itself: progress is kept in <output>/RUN NN/_supervise.json - run it again with the same --run to resume
            (the launcher loops on it until it finishes).
  - nothing twice: the run is picked like cutthebullshit run does (the newest that already has every source), each folder
            is continued in the run that already has its frames, every step skips what is on disk, and After
            Effects runs once at the end
  - ETA:    counted from what is really left on disk per step (frames already done don't count), priced with the
            speeds learned in timings.json and corrected by how long this session's folders really took; every
            folder start and every 5 min a line "this folder ~X | whole run ~Y, finish ~Z", also in
            <output>/RUN NN/_supervise_eta.json
Summary of failed / partial folders: <output>/RUN NN/_supervise_summary.txt (and the end of the log).

    cutthebullshit supervise <scene / object / RAW folders> [--run NN] [--no-ae]
    cutthebullshit supervise --selftest      # restart Photoshop and After Effects once
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

from . import eta
from . import prep
from . import pipeline
from .aecomps import AE_APP, RESULT
from .cleanplate import PS_APP
from .config import need_app, OUTPUT_DIR, is_excluded, list_frames, load_json, resolve_run, run_name, run_roots, state_path as tool_file, short_name, photo_folders

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
PIPELINE = ["-m", "cutthebullshit.pipeline"]     # what every job runs (the same Python, the installed package)
ETA_EVERY = 300                  # s between the combined folder / whole-run ETA lines while a job runs
FOLDER_OVERHEAD = 20             # s per folder job besides frame work (recorte start, app checks)
HANG_MIN = 25                    # longest legit silence: one Photoshop attempt (cleanplate gives up after 16 min)
ATTEMPTS = 3
PS_NAME = PS_APP
STEP_APP = {"cleanplate": "photoshop", "aecomps": "ae"}


def log(msg):
    print("[supervise %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def fmt(sec):
    sec = int(max(0, sec))
    return "%dh%02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm%02ds" % (sec // 60, sec % 60)


# ---------------------------------------------------------------- apps

def osa(lines, timeout):
    cmd = ["osascript"]
    for l in lines:
        cmd += ["-e", l]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip() + r.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"


def ps_ok():
    rc, out = osa(["with timeout of 60 seconds", 'tell application "%s" to do javascript "\'ps-ok\'"' % PS_APP,
                   "end timeout"], 90)
    return rc == 0 and "ps-ok" in out


AE_PING = tool_file("_supervise_ae_ping.jsx")


def ae_ok():
    with open(AE_PING, "w") as fh:
        fh.write('var f = new File(%s); f.open("w"); f.write("ae-ok"); f.close();' % json.dumps(RESULT))
    if os.path.exists(RESULT):
        os.remove(RESULT)
    osa(["with timeout of 120 seconds", 'tell application "%s" to DoScriptFile "%s"' % (AE_APP, AE_PING),
         "end timeout"], 150)
    for _ in range(20):
        if os.path.exists(RESULT):
            return open(RESULT).read().strip() == "ae-ok"
        time.sleep(0.5)
    return False


def kill(pattern):
    subprocess.run(["pkill", "-9", "-f", pattern], capture_output=True)


PROCESS = {"photoshop": PS_NAME, "ae": "After Effects"}


def ui_access():
    """Can we click other apps' dialogs? (Accessibility permission for the app that started this.)"""
    rc, out = osa(['tell application "System Events" to tell process "Finder" to get count of windows'], 30)
    return rc == 0


def dismiss(app, force=False):
    """Close the modal dialogs of an app (crash recovery, autosave, scratch disk, alerts); logs what it clicked.
    force: if no dialog button was found, bring the app to the front and press Return."""
    try:
        r = subprocess.run(["osascript", os.path.join(HERE, "dismiss_dialogs.applescript"), PROCESS[app]]
                           + (["force"] if force else []), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False
    if r.returncode != 0:
        if "assistive access" in r.stderr:
            log("cannot close %s dialogs: no Accessibility permission" % app)
        return False
    if r.stdout.strip():
        log("closed %s dialog(s): %s" % (app, r.stdout.strip()))
        return True
    return False


def wait_until(check, minutes, app):
    t = time.time()
    time.sleep(20)
    while time.time() - t < minutes * 60:
        if check():
            return True
        dismiss(app, force=time.time() - t > 60)    # startup dialogs (crash recovery, scratch disk...) block scripting
        time.sleep(10)
    return False


def restart(app):
    log("restarting %s" % app)
    if app == "photoshop":
        kill("%s.app/Contents/MacOS" % PS_NAME)
        time.sleep(10)
        subprocess.run(["open", "-a", PS_NAME])
        ok = wait_until(ps_ok, 10, app)
        if ok:                         # recovered documents from a crash: close them
            osa(["with timeout of 120 seconds", 'tell application "%s" to do javascript '
                 '"while (app.documents.length) app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); \'done\'"' % PS_APP,
                 "end timeout"], 150)
    else:
        kill("%s.app/Contents/MacOS/After Effects" % AE_APP)
        time.sleep(10)
        subprocess.run(["open", "-a", AE_APP])
        ok = wait_until(ae_ok, 10, app)
    log("%s restart %s" % (app, "ok" if ok else "FAILED (will try again)"))
    return ok


CHECKS = {"photoshop": ps_ok, "ae": ae_ok}


def ensure(apps):
    for app in apps:
        for _ in range(3):
            if CHECKS[app]():
                break
            log("%s not answering" % app)
            if dismiss(app, force=True) and CHECKS[app]():      # a dialog was in the way
                break
            restart(app)


# ---------------------------------------------------------------- jobs

def show_eta(here, after, eta_file, where, step):
    total = here + after
    finish = time.strftime("%a %H:%M", time.localtime(time.time() + total))
    log("ETA  %s%s: ~%s left  |  whole run: ~%s left, finish ~%s" % (where, " (%s)" % step if step else "", fmt(here),
                                                                     fmt(total), finish))
    if eta_file:
        try:
            with open(eta_file + ".tmp", "w") as fh:
                json.dump({"updated": time.strftime("%Y-%m-%d %H:%M:%S"), "where": where, "step": step,
                           "this_job_left_s": round(here), "run_left_s": round(total), "finish": finish}, fh, indent=1)
            os.replace(eta_file + ".tmp", eta_file)
        except OSError:
            pass




def parse_fmt(txt):
    """'1h02m' / '3m20s' / '45s' (progress.fmt) -> seconds."""
    import re
    m = re.match(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", txt)
    if not m or not txt:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se


def run_job(args, label, after=None, eta_file=None, where=""):
    """Run python args (cutthebullshit run ...), stream its output, kill it if silent for HANG_MIN.
    after: estimated seconds of the whole run still to come once this job is done -> every ETA_EVERY seconds a
    combined line (this job's own remaining time, from recorte's progress, + that), also written to eta_file.
    Returns (result, last step): result is 'ok', 'fail' or 'hang'."""
    import re
    log("start %s" % label)
    left_rx = re.compile(r"remaining ~(\S+)")
    shown = {"t": 0.0}
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.dirname(HERE)] + ([os.environ["PYTHONPATH"]]
                                                                              if os.environ.get("PYTHONPATH") else [])))
    p = subprocess.Popen([PY, "-u"] + args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         start_new_session=True)
    st = {"last": time.time(), "step": None}

    def reader():
        for line in p.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            st["last"] = time.time()
            if line.startswith("######## ") and " took " not in line and "exited with" not in line:
                st["step"] = line.split()[1]
            m = left_rx.search(line) if after is not None else None
            if m and line.lstrip().startswith("["):
                here = parse_fmt(m.group(1))
                if here is not None and time.time() - shown["t"] >= ETA_EVERY:
                    shown["t"] = time.time()
                    show_eta(here, after, eta_file, where, st["step"])
            if "Photoshop retry 2/2" in line and "no answer" in line:   # timed out twice: stuck (dialog?)
                st["kill"] = "cleanplate"

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    while p.poll() is None:
        stuck = st.get("kill")
        if stuck or time.time() - st["last"] > HANG_MIN * 60:
            if stuck:
                st["step"] = stuck
                log("HANG: Photoshop didn't answer twice on the same frame - killing %s" % label)
            else:
                log("HANG: no output for %d min in step %s - killing %s" % (HANG_MIN, st["step"], label))
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.wait()
            th.join(5)
            return "hang", st["step"]
        time.sleep(5)
    th.join(5)
    return ("ok" if p.returncode == 0 else "fail"), st["step"]


def expand(sources):
    """Every photo folder below the sources (a source with photos in it is one itself), once each, sorted."""
    found = []
    for src in sources:
        found += photo_folders(src)
    return sorted(dict.fromkeys(found))


# per folder: everything up to the After Effects inputs; "salvage" = what still works on the frames that got a clean plate
FOLDER_STEPS, SALVAGE_STEPS = "prep,cleanplate,passes,layers,preview,prores", "passes,layers,preview,prores"
FOLDER_APPS, SALVAGE_APPS = ["photoshop"], []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="*")
    ap.add_argument("--run", help="target run number (default: like cutthebullshit run, the newest run that already has every "
                                  "source, else the latest; a restart finds the same one)")
    ap.add_argument("--bg", default=None, help="background of the PREVIEW renders and AE scene comps (see cutthebullshit run --bg)")
    ap.add_argument("--no-ae", action="store_true", help="stop after the per-folder steps (no After Effects)")
    ap.add_argument("--state", default=None, help="progress file (default <output>/RUN NN/_supervise.json; another one "
                                                  "= an independent job in the same run)")
    ap.add_argument("--new-run", action="store_true", help="start a new RUN and process everything again in it "
                                                            "(restarts then need --run with its number)")
    ap.add_argument("--selftest", action="store_true", help="restart Photoshop and After Effects once and check them")
    args = ap.parse_args(argv)
    need_app(PS_APP, "Photoshop")
    if not args.no_ae:
        need_app(AE_APP, "After Effects")

    if not ui_access():
        log("WARNING: no Accessibility permission - dialogs that block Photoshop / After Effects after a crash "
            "can't be closed automatically (System Settings > Privacy & Security > Accessibility > the app you run this from)")
    if args.selftest:
        res = {app: restart(app) for app in ("photoshop", "ae")}
        log("selftest: %s" % res)
        return 0 if all(res.values()) else 1
    if not args.sources:
        ap.error("sources are required")
    if args.run and args.new_run:
        ap.error("--run and --new-run don't go together")

    folders = expand(args.sources)
    run_no, why = pipeline.pick_run(folders, args.run, args.new_run)
    _, write_root = run_roots(run_no)
    os.makedirs(write_root, exist_ok=True)
    state_path = args.state or os.path.join(write_root, "_supervise.json")
    state = load_json(state_path) or {"run": run_name(run_no), "started": time.strftime("%Y-%m-%d %H:%M:%S"),
                                      "folders": {}, "final": {}}

    def save():
        with open(state_path + ".tmp", "w") as fh:
            json.dump(state, fh, indent=1)
        os.replace(state_path + ".tmp", state_path)

    run_args = ["--run", str(run_no)] + (["--bg", args.bg] if args.bg is not None else [])

    # ---- what is really left (frames already done are skipped by every step, in whatever run they are)
    frame_steps = [k for k in eta.FRAME_STEPS if k in FOLDER_STEPS.split(",")]
    spf = pipeline.speeds()
    homes = {f: pipeline.home_run(f, run_no, args.new_run) for f in folders}
    todo = {f: eta.pending(f, run_roots(homes[f])[0], frame_steps) for f in folders}
    total = sum(t["frames"] for t in todo.values())
    n_seq = sum(t["seqs"] for t in todo.values())
    elsewhere = sorted({homes[f] for f in folders} - {run_no})
    log("%s (%s): %d RAW folders, %d frames, %d sequences  (state %s)%s" % (
        run_name(run_no), why, len(folders), total, n_seq, state_path,
        "  - folders already in %s are continued there" % ", ".join(map(run_name, elsewhere)) if elsewhere else ""))
    log("to do: %s  (the rest is already done)" % ", ".join(
        "%s %d/%d fr" % (k, sum(t[k] for t in todo.values()), total) for k in frame_steps))

    def folder_est(f):
        """seconds still needed for a folder (0 once done), before the session correction"""
        rec = state["folders"].get(f, {})
        if rec.get("status", "todo") != "todo":
            return 0.0
        w = eta.seconds(todo[f], spf)
        return w + FOLDER_OVERHEAD if w else FOLDER_OVERHEAD / 4

    def final_est():
        fin = state.get("final", {})
        t = 0.0 if fin.get("aecomps") == "done" or args.no_ae else n_seq * spf["aecomps"] + 60
        return t

    # session correction: how much longer folders really took than estimated (retries, restarts, slow frames)
    corr = {"est": 0.0, "real": 0.0}

    def factor():
        if corr["est"] < 300:
            return 1.0
        return min(3.0, max(0.5, corr["real"] / corr["est"]))

    eta_file = os.path.splitext(state_path)[0] + "_eta.json"

    def left_after(folder):
        """whole-run seconds still to come after this folder"""
        k = factor()
        return k * sum(folder_est(f) for f in folders if f != folder) + final_est()

    # ---- per folder
    for i, folder in enumerate(folders, 1):
        rec = state["folders"].setdefault(folder, {"status": "todo", "attempts": 0, "notes": []})
        if rec["status"] != "todo":
            continue
        here = folder_est(folder) * factor()
        total_left = here + left_after(folder)
        t_ = todo[folder]
        log("==== folder %d/%d  %s  (%d frames; to do %s)  |  this folder ~%s  |  whole run ~%s, finish ~%s%s" % (
            i, len(folders), short_name(folder), t_["frames"],
            ", ".join("%s %d" % (k, t_[k]) for k in frame_steps if t_[k]) or "nothing", fmt(here), fmt(total_left),
            time.strftime("%a %H:%M", time.localtime(time.time() + total_left)),
            "  [%s]" % run_name(homes[folder]) if homes[folder] != run_no else ""))
        show_eta(here, left_after(folder), eta_file, "folder %d/%d" % (i, len(folders)), None)
        est0, t0 = folder_est(folder), time.time()
        while rec["attempts"] < ATTEMPTS and rec["status"] == "todo":
            rec["attempts"] += 1
            save()
            ensure(FOLDER_APPS)
            res, step = run_job(PIPELINE + [folder] + run_args + ["--steps", FOLDER_STEPS],
                                "%s attempt %d/%d" % (os.path.basename(os.path.dirname(folder)), rec["attempts"], ATTEMPTS),
                                after=left_after(folder), eta_file=eta_file, where="folder %d/%d" % (i, len(folders)))
            if res == "ok":
                rec["status"] = "done"
            else:
                rec["notes"].append("attempt %d: %s in %s" % (rec["attempts"], res, step))
                log("attempt %d %s (step %s)" % (rec["attempts"], res, step))
                if res == "hang" and step in STEP_APP:
                    restart(STEP_APP[step])
        if rec["status"] == "todo":
            # last resort: build whatever got a clean plate (passes, layers, preview), then move on
            ensure(SALVAGE_APPS)
            res, step = run_job(PIPELINE + [folder] + run_args + ["--steps", SALVAGE_STEPS], "%s what exists" % SALVAGE_STEPS)
            rec["status"] = "partial" if res == "ok" else "failed"
            rec["notes"].append("gave up after %d attempts: %s" % (ATTEMPTS, rec["status"]))
            log("folder %s -> %s" % (folder, rec["status"].upper()))
        save()
        if est0 > FOLDER_OVERHEAD:                   # real work was expected: learn how far off the estimate was
            corr["est"] += est0
            corr["real"] += time.time() - t0

    # ---- one more try for folders that ended partial / failed (the cause may have been temporary)
    if not state.get("second_pass"):
        for folder in [f for f in folders if state["folders"][f]["status"] in ("partial", "failed")]:
            rec = state["folders"][folder]
            log("==== second pass: %s (%s)" % (short_name(folder), rec["status"]))
            ensure(FOLDER_APPS)
            res, step = run_job(PIPELINE + [folder] + run_args + ["--steps", FOLDER_STEPS],
                                "%s second pass" % os.path.basename(os.path.dirname(folder)))
            if res == "ok":
                rec["status"] = "done"
                rec["notes"].append("second pass: ok")
            else:
                rec["notes"].append("second pass: %s in %s" % (res, step))
                if res == "hang" and step in STEP_APP:
                    restart(STEP_APP[step])
                ensure(SALVAGE_APPS)
                res, step = run_job(PIPELINE + [folder] + run_args + ["--steps", SALVAGE_STEPS], "%s what exists" % SALVAGE_STEPS)
                if res == "ok" and rec["status"] == "failed":
                    rec["status"] = "partial"
            save()
        state["second_pass"] = True
        save()

    # ---- After Effects over every folder that got through, once
    ok_folders = [f for f in folders if state["folders"][f]["status"] in ("done", "partial")]
    fin = state["final"]

    def final_step(name, args_, label):
        for attempt in range(1, ATTEMPTS + 1):
            ensure(["ae"])
            after = final_est() - (n_seq * spf["aecomps"] + 60)
            res, step = run_job(args_, "%s attempt %d" % (label, attempt), after=max(0.0, after), eta_file=eta_file,
                                where=name)
            if res == "ok":
                fin[name] = "done"
                save()
                return True
            fin.setdefault("notes", []).append("%s attempt %d: %s in %s" % (name, attempt, res, step))
            save()
            restart("ae")
        fin[name] = "failed"
        save()
        return False

    if args.no_ae:
        log("--no-ae: After Effects not run")
    elif ok_folders and fin.get("aecomps") != "done":
        final_step("aecomps", PIPELINE + ok_folders + run_args + ["--steps", "aecomps"], "After Effects precomps")

    # ---- summary
    st = state["folders"]
    bad = [(f, st[f]) for f in folders if st[f]["status"] != "done"]
    lines = ["%s  finished %s" % (run_name(run_no), time.strftime("%Y-%m-%d %H:%M:%S")),
             "folders: %d done, %d partial, %d failed (of %d)" % (
                 sum(st[f]["status"] == "done" for f in folders), sum(st[f]["status"] == "partial" for f in folders),
                 sum(st[f]["status"] == "failed" for f in folders), len(folders)),
             "after effects: %s" % fin.get("aecomps"),
             "AE project: %s" % os.path.join(write_root, "recorte_precomps.aep")]
    for f, r in bad:
        lines.append("  %-8s %s\n           %s" % (r["status"].upper(), f, "; ".join(r["notes"])))
    for n in fin.get("notes", []):
        lines.append("  final: " + n)
    with open(os.path.splitext(state_path)[0] + "_summary.txt", "w") as fh:       # next to the progress file
        fh.write("\n".join(lines) + "\n")
    log("DONE\n" + "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
