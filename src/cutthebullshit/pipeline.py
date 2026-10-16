"""Full cut-out workflow for organized object folders (<photos>/<scene>/<object>/.../RAW).

Every run has its own folders in the work folder (work_dir/RUN NN/<scene>/<object>/...) and the output folder
(output_dir/RUN NN/{LAYERS/<scene>/<object>/..., LAYOUTS/..., PREVIEWS/, PRORES/..., recorte_precomps.aep}); both are
yours to choose (settings, or `cutthebullshit --work DIR --output DIR run ...`).
For each source RAW folder, in order:
  1. prep        develop + denoise each RAW once -> half-res 16-bit sRGB <seq>_beauty PNG, the photo all the way to AE
                 (<work>/RUN NN/<path below the mirror root>/; older runs have linear EXRs instead, still used as they are)
  2. cleanplate  Photoshop: Select Subject + shadow/glow, Content-Aware Fill -> _plate (16-bit PNG) and _subject
  3. passes      8-bit sRGB PNGs next to the frames: _shadow (Multiply), _bounce (Screen); the plate is deleted after
  3b. layers     OpenCV: LAYERS/<shot> object / MULTIPLY_ / SCREEN_, LAYOUTS/<shot> LAYOUT_ (one RGBA for layout over
                 any background), PREVIEWS/PREVIEW_ jpg (the AE scene comp over --bg); then
                 preview: PREVIEW_<seq>.mp4 of every stop-motion; prores: a ProRes 4444 movie of every stop-motion
  4. aecomps     After Effects, one precomp per sequence (CONTROL null + OBJECT = beauty through
                 the Select Subject matte, SCREEN bounce light, MULTIPLY shadow) in <output>/RUN NN/recorte_precomps.aep,
                 a stop-motion as one precomp of image sequences at --fps, plus a 24 fps comp per scene over the bg
The AE footage stays in the work folder; Collect Files on the project gathers everything to hand it over.
Prints a time estimate per step at the start (from timings.json, updated after every run) and the remaining
time after each step.

Nothing already done is processed again. The target run (project, log) is --run, else the newest run
that already has every source, else the latest; each source is then worked on in the newest run that already has
any of its frames (an older run included), else the target, and every step skips frames whose outputs are up to
date. --new-run starts a new RUN and processes everything again there; --force redoes frames in the run used.
Needs Photoshop and After Effects open.

    cutthebullshit run "<photos>/OBJECTS/S01 Kitchen/teapot-anim/RAW" [...]
    cutthebullshit run "<photos>/OBJECTS/S01 Kitchen"        # every RAW folder of a scene

Folders named CUT OUT (any case) are never processed.
Stop-motion = a parent folder ends in -anim/_anim (one sequence per folder/version, with an .mp4 preview);
every other photo is a still (its own item and precomp).
    cutthebullshit run <folders> --steps passes,aecomps          # rebuild the AE precomps
"""

import argparse
import json
import os
import sys
import time

from . import aecomps
from . import layers
from . import passes
from . import cleanplate
from . import eta
from . import frames as fr
from . import prep
from . import preview
from . import progress
from . import prores
from .config import is_excluded, layers_dir, list_frames, load_json, mirror_dir, resolve_run, run_name, run_roots, runs, state_path, split_run, photo_folders

STEPS = ("prep", "cleanplate", "passes", "layers", "preview", "prores", "aecomps")
DEFAULT_STEPS = STEPS
ALIASES = {"beauty": "passes"}            # the step's name before 2026-10-16
TIMINGS = state_path("timings.json")    # seconds per frame of every step, learned on this machine
# seconds per frame (aecomps: per sequence) measured on this Mac; refined from timings.json after every run
DEFAULT_SPF = {"prep": 4.5, "cleanplate": 13.0, "passes": 5.5, "layers": 2.0, "preview": 0.2, "prores": 0.3, "aecomps": 8.0}


def fmt(sec):
    sec = int(round(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return ("%dh%02dm" % (h, m)) if h else ("%dm%02ds" % (m, s)) if m else ("%ds" % s)


def speeds():
    t = load_json(TIMINGS)
    return {k: t.get(k, {}).get("spf", v) for k, v in DEFAULT_SPF.items()}


def learn(step, seconds, units):
    """Update the step's seconds-per-unit with this measurement (running average, recent runs weigh more)."""
    if units <= 0 or seconds <= 0:
        return
    t = load_json(TIMINGS)
    cur = t.get(step, {"spf": DEFAULT_SPF[step], "n": 0})
    if seconds / units < 0.25 * cur["spf"]:
        return                                  # mostly skipped (resumed run): not a speed measurement
    w = 0.5 if cur["n"] else 1.0
    cur["spf"] = round(cur["spf"] * (1 - w) + (seconds / units) * w, 3)
    cur["n"] += 1
    t[step] = cur
    with open(TIMINGS, "w") as fh:
        json.dump(t, fh, indent=1, sort_keys=True)


def prepped(read_root, src):
    """True if every frame of a source RAW folder is already developed in this run's work folder (PNG, or an EXR)."""
    frames = list_frames(src)                 # numbered the way prep numbers them
    if not frames:
        return False
    rd = mirror_dir(read_root, frames[0])
    return all(os.path.exists(fr.frame_path(rd, s, "%04d" % n)) for s, n in (prep.sequence_name(f, i) for i, f in enumerate(frames, 1)))


def started(read_root, src):
    """True if at least one frame of a source RAW folder is developed in this run's work folder."""
    frames = list_frames(src)
    if not frames:
        return False
    rd = mirror_dir(read_root, frames[0])
    return any(os.path.exists(fr.frame_path(rd, s, "%04d" % n)) for s, n in (prep.sequence_name(f, i) for i, f in enumerate(frames, 1)))


def home_run(src, target, new_run=False):
    """The run a source is processed in: the newest run that already has any of its frames (so nothing done is
    processed twice, even when it was done in an older run than the target), else the target run.
    With --new-run everything goes to the new run."""
    if new_run:
        return target
    for n in reversed(runs()):
        if n <= target and started(run_roots(n)[0], src):
            return n
    return target


def pick_run(sources, run=None, new_run=False):
    """(target run number, why): the run whose folders / project / log this is. Never a new run unless asked."""
    if new_run:
        return resolve_run("new"), "new run (--new-run)"
    if run:
        return resolve_run(run), "--run"
    existing = runs()
    if not existing:
        return resolve_run("new"), "first run"
    for n in reversed(existing):
        if all(prepped(run_roots(n)[0], s) for s in sources):
            return n, "already has every source"
    return existing[-1], "latest run (not every source is prepped in any run yet)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="RAW folders of the photo tree, or scene / object folders "
                                               "(every RAW folder below them)")
    ap.add_argument("--steps", default=",".join(DEFAULT_STEPS),
                    help="comma-separated subset of %s (default %%(default)s)" % ",".join(STEPS))
    ap.add_argument("--run", default=None, help="run number to use (default: the newest run that already has every "
                                                "source, else the latest)")
    ap.add_argument("--bg", default=None, help="background of the PREVIEW renders and the AE scene comps: an image, a colour "
                                               "(#rrggbb, white, grey, 0.5, 200,190,170) or none (default: the settings' background)")
    ap.add_argument("--new-run", action="store_true", help="start a new RUN (processes everything again in it)")
    ap.add_argument("--grow", type=int, default=60, help="clean-plate selection margin in px (default %(default)s)")
    ap.add_argument("--fps", type=float, default=12, help="precomp / preview frame rate (default %(default)s)")
    ap.add_argument("--denoise", choices=("off", "raw", "strong"), default="raw", help="prep denoise (default %(default)s)")
    ap.add_argument("--look", choices=("camera", "linear"), default="camera",
                    help="prep: camera = match the camera JPEG preview embedded in each RAW (default); linear = plain + adjustments")
    ap.add_argument("--exposure", type=float, default=None, help="prep: extra stops (linear look default 1.4)")
    ap.add_argument("--midtones", type=float, default=None, help="prep: midtone lift (linear look default %s)" % prep.MIDTONES)
    ap.add_argument("--contrast", type=float, default=None, help="prep: gentle S-curve (linear look default %s)" % prep.CONTRAST)
    ap.add_argument("--force", action="store_true", help="redo frames (prep, clean plates, passes, layers) that already exist in the run")
    args = ap.parse_args(argv)
    steps = [ALIASES.get(s.strip(), s.strip()) for s in args.steps.split(",") if s.strip()]
    bad = [s for s in steps if s not in STEPS]
    if bad:
        ap.error("unknown step(s): %s" % ", ".join(bad))

    if args.run and args.new_run:
        ap.error("--run and --new-run don't go together")
    if args.bg is not None:
        from .config import parse_bg
        try:
            parse_bg(args.bg)                         # a typo fails now, not after hours of processing
        except ValueError as e:
            ap.error(str(e))

    # a scene / object folder expands to every photo folder below it (excluded folders skipped)
    sources = []
    for src in args.sources:
        found = photo_folders(src)
        if found != [src]:
            print("   %s -> %d photo folder(s)" % (src, len(found)))
        sources += found

    run_no, why = pick_run(sources, args.run, args.new_run)
    read_root, write_root = run_roots(run_no)
    print("== %s   (%s; %s, %s)" % (run_name(run_no), why, read_root, write_root), flush=True)

    pairs, n_frames, n_seqs, homes = [], 0, 0, {}
    todo = {k: 0 for k in eta.FRAME_STEPS}
    for src in sources:
        frames = list_frames(src)
        if not frames:
            print("no frames in %s" % src)
            continue
        home = home_run(src, run_no, args.new_run)
        homes.setdefault(home, []).append(src)
        home_read = run_roots(home)[0]
        if home != run_no:
            print("   %s: already in %s, continued there" % (os.path.relpath(src, os.path.dirname(os.path.dirname(src))),
                                                             run_name(home)))
        rd = mirror_dir(home_read, frames[0])
        pairs.append((src, rd, layers_dir(rd)))
        p = eta.pending(src, home_read, [k for k in eta.FRAME_STEPS if k in steps])
        n_frames += len(frames)
        n_seqs += len({prep.sequence_name(f, i)[0] for i, f in enumerate(frames, 1)})
        for k in todo:
            todo[k] += p.get(k, 0) if not args.force else len(frames)
    if not pairs:
        return 1

    # time estimate, from what each step will really process (frames already done in this run are skipped)
    spf = speeds()
    units = {k: (n_seqs if k in ("aecomps", "prores") else n_frames) for k in STEPS}
    pend = {k: todo.get(k, units[k]) for k in STEPS}
    est = {k: spf[k] * pend[k] for k in steps}
    t0 = time.time()
    print("   %d object folder(s), %d frame(s), %d sequence(s)" % (len(pairs), n_frames, n_seqs))
    print("   %-11s %14s %10s" % ("step", "to do", "estimate"))
    for k in steps:
        unit = "seq" if k in ("aecomps", "prores") else "fr"
        print("   %-11s %14s %10s" % (k, ("%d/%d %s" % (pend[k], units[k], unit)) if k in todo else "%d %s" % (units[k], unit),
                                     fmt(est[k])))
    total = sum(est.values())
    progress.begin({k: (units[k], spf[k], pend[k]) for k in steps})
    print("   %-11s %14s %10s   -> finish ~%s (frames already done are skipped and not counted)"
          % ("total", "", fmt(total), time.strftime("%H:%M", time.localtime(t0 + total))), flush=True)

    # run record
    log_path = os.path.join(write_root, "_run.json")
    log = load_json(log_path) or {"run": run_name(run_no), "created": time.strftime("%Y-%m-%d %H:%M:%S"), "invocations": []}
    log["invocations"].append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": steps, "sources": sources,
                               "grow": args.grow, "fps": args.fps, "new_run": args.new_run, "bg": args.bg, "denoise": args.denoise, "look": args.look, "exposure": args.exposure, "midtones": args.midtones, "contrast": args.contrast, "force": args.force})
    os.makedirs(write_root, exist_ok=True)
    with open(log_path, "w") as fh:
        json.dump(log, fh, indent=1)

    done = []

    def run(name, fn, argv_, step=None):
        print("\n######## %s" % name, flush=True)
        if step:
            progress.step_start(step)
        t = time.time()
        rc = fn(argv_)
        if rc:
            print("######## %s exited with %s - stopping" % (name, rc), flush=True)
            sys.exit(rc)
        return time.time() - t

    def step_done(step, seconds):
        progress.step_end(step)
        learn(step, seconds, pend[step])
        done.append(step)
        left = sum(est[k] for k in steps if k not in done)
        print("######## %s took %s (estimate %s)  -  remaining ~%s, finish ~%s" % (
            step, fmt(seconds), fmt(est[step]), fmt(left), time.strftime("%H:%M", time.localtime(time.time() + left))),
            flush=True)

    if "prep" in steps:
        secs = 0.0
        for home, srcs in sorted(homes.items()):        # each source in its own run (see home_run)
            secs += run("prep %s" % run_name(home), prep.main, srcs + ["--run", str(home), "--denoise", args.denoise, "--look", args.look]
                        + sum((["--" + k, str(v)] for k, v in (("exposure", args.exposure), ("midtones", args.midtones),
                                                               ("contrast", args.contrast)) if v is not None), [])
                        + (["--force"] if args.force else []), "prep")
        step_done("prep", secs)
    if "cleanplate" in steps:
        secs = 0.0
        for _, rd, _ in pairs:
            secs += run("cleanplate %s" % os.path.relpath(rd, read_root), cleanplate.main,
                        [rd, "--grow", str(args.grow)] + (["--force"] if args.force else []), "cleanplate")
        step_done("cleanplate", secs)
    if "passes" in steps:
        step_done("passes", run("passes", passes.main, [rd for _, rd, _ in pairs] + (["--force"] if args.force else []), "passes"))
    if "layers" in steps:
        step_done("layers", run("layers", layers.main, [rd for _, rd, _ in pairs] + (["--force"] if args.force else [])
                                + (["--bg", args.bg] if args.bg is not None else []), "layers"))
    if "preview" in steps:
        step_done("preview", run("preview", preview.main, [wd for _, _, wd in pairs] + ["--fps", str(args.fps)], "preview"))
    if "prores" in steps:
        # per run (an object may be continued in an older run), only the objects of this invocation
        by_run = {}
        for _, _, wd in pairs:
            rn, shot = split_run(wd)
            by_run.setdefault(rn, []).append("/".join(shot))
        secs = 0.0
        for rn, shots in sorted(by_run.items()):
            secs += run("prores %s" % rn, prores.main, ["--run", rn.split()[1]] + shots, "prores")
        step_done("prores", secs)
    if "aecomps" in steps:
        step_done("aecomps", run("aecomps", aecomps.main, [rd for _, rd, _ in pairs] + ["--fps", str(args.fps), "--save",
                                 os.path.join(write_root, aecomps.PROJECT_NAME)]
                                 + (["--bg", args.bg] if args.bg is not None else []), "aecomps"))
    print("\n== done in %s: %s" % (fmt(time.time() - t0), write_root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
