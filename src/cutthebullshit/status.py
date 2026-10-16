"""Status of a run against the source tree: what's missing per stage, for stop-motions, stills or both.

Stop-motions are folders named -anim / _anim (one sequence per folder); stills are every other photo (each its own
sequence, frame 1). For each RAW folder below the source folder it counts, at that folder's own path in the run:
  RAW       photos in the source folder (file names only: cloud online-only placeholders count)
  prep      developed frames                   work_dir/RUN NN/<path>/<seq>_beauty.####.png (older runs: .exr)
  plate     subject masks + clean plate        <seq>_subject.####.png and the plate (or, once passes deleted it,
                                               the passes)
  passes    shadow + bounce                    <seq>_shadow.####.png, <seq>_bounce.####.png
  layers    object + MULTIPLY_ + SCREEN_ PNGs  output_dir/RUN NN/LAYERS/<path>
  layout    LAYOUT_ PNGs                       output_dir/RUN NN/LAYOUTS/<path>
  preview   PREVIEW_ jpgs                      output_dir/RUN NN/PREVIEWS  (+ the mp4 for stop-motions)
  prores    stop-motions: movie newer than its frames   output_dir/RUN NN/PRORES/<path>/<seq>.mov
For incomplete folders it also counts the photos that are cloud online-only placeholders (0 bytes, e.g. Dropbox): those
must be made available offline before they can be processed. It also says when a stop-motion was made at an older path of the object.

    cutthebullshit status --run 1                       # stop-motions
    cutthebullshit status --run 1 --kind still [--all]  # stills (--all lists complete ones too)
"""

import argparse
import glob
import os
import sys

from . import frames as fr
from . import prep
from .config import (LAYERS, LAYOUTS, PREVIEWS, list_frames, mirror_dir, resolve_run, run_name, run_roots)
from .supervise import expand

from .config import PHOTO_FOLDER, SOURCE_ROOT
STAGES = ("prep", "plate", "passes", "layers", "layout", "preview")


def count(folder, pattern):
    return len([p for p in glob.glob(os.path.join(folder, pattern)) if not os.path.basename(p).startswith("._")])


def ex(p):
    return os.path.exists(p)


def check(raw, frames, anim, read_root, write_root):
    rd = mirror_dir(read_root, frames[0])                           # <work>/RUN NN/<path>/RAW
    shot = os.path.relpath(os.path.dirname(rd) if PHOTO_FOLDER and os.path.basename(rd) == PHOTO_FOLDER else rd, read_root)
    L, LO, PR = (os.path.join(write_root, x, shot) for x in (LAYERS, LAYOUTS, "PRORES"))
    PV = os.path.join(write_root, PREVIEWS)
    items = [prep.sequence_name(f, i) for i, f in enumerate(frames, 1)]          # (seq, frame number) per photo
    c = {s: 0 for s in STAGES}
    for seq, n in items:
        t, n4 = "%s.%04d" % (seq, n), "%04d" % n
        passes = all(ex(os.path.join(rd, "%s_%s.%s.png" % (seq, k, n4))) for k in ("shadow", "bounce"))
        c["prep"] += ex(fr.frame_path(rd, seq, n4))
        c["plate"] += ex(fr.subject_path(rd, seq, n4)) and (ex(fr.plate_path(rd, seq, n4)) or passes)
        c["passes"] += passes
        c["layers"] += all(ex(os.path.join(L, p + t + ".png")) for p in ("", "MULTIPLY_", "SCREEN_"))
        c["layout"] += ex(os.path.join(LO, "LAYOUT_" + t + ".png"))
        c["preview"] += ex(os.path.join(PV, "PREVIEW_" + t + ".jpg"))
    n = len(items)
    seqs = sorted({s for s, _ in items})
    missing = [k for k in STAGES if c[k] < n]
    if anim:
        seq = seqs[0]
        if not ex(os.path.join(PV, "PREVIEW_%s.mp4" % seq)):
            missing.append("preview mp4")
        mov = os.path.join(PR, seq + ".mov")
        objs = glob.glob(os.path.join(L, "%s.[0-9][0-9][0-9][0-9].png" % seq))
        if not ex(mov):
            missing.append("prores")
        elif objs and os.path.getmtime(mov) < max(os.path.getmtime(p) for p in objs):
            missing.append("prores (out of date)")
    old = None
    if anim:                                    # made at an older path of the same object?
        parent = os.path.dirname(shot)
        while parent and not old:
            k = count(os.path.join(write_root, LAYERS, parent), "%s.[0-9][0-9][0-9][0-9].png" % seqs[0])
            old = "%s (%d frames)" % (parent, k) if k else None
            parent = os.path.dirname(parent)
    online_only = sum(os.stat(f).st_size == 0 for f in frames) if missing else 0
    return shot, n, c, missing, old, online_only


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", default=SOURCE_ROOT, help="the photo tree to check (default: source_root in the settings)")
    ap.add_argument("--run", default="latest")
    ap.add_argument("--kind", choices=("anim", "still", "all"), default="anim", help="stop-motions (default), stills or both")
    ap.add_argument("--all", action="store_true", help="also list the complete folders")
    args = ap.parse_args(argv)
    if not args.source:
        ap.error("give the photo folder to check, or set source_root in the settings")
    run_no = resolve_run(args.run)
    read_root, write_root = run_roots(run_no)
    complete, incomplete = [], []
    for raw in expand([args.source]):
        frames = list_frames(raw)
        if not frames:
            continue
        anim = prep.is_animation(frames[0])
        if (args.kind == "anim" and not anim) or (args.kind == "still" and anim):
            continue
        row = check(raw, frames, anim, read_root, write_root)
        (incomplete if row[3] else complete).append(row)

    what = {"anim": "stop-motions", "still": "stills", "all": "stop-motions and stills"}[args.kind]
    print("%s - %s of %s\n" % (run_name(run_no), what, args.source))
    print("INCOMPLETE (%d folders, %d photos; %d of them online-only placeholders)" % (
        len(incomplete), sum(r[1] for r in incomplete), sum(r[5] for r in incomplete)))
    print("  %-56s %4s %7s  %s   %s" % ("folder", "RAW", "online", " ".join("%7s" % s for s in STAGES), "missing"))
    for shot, n, c, missing, old, oo in incomplete:
        print("  %-56s %4d %7s  %s   %s" % (shot, n, oo or "", " ".join("%7d" % c[s] for s in STAGES), ", ".join(missing)))
        if old:
            print("  %-56s       made at the old path %s" % ("", old))
    print("\nCOMPLETE (%d folders, %d photos)%s" % (len(complete), sum(r[1] for r in complete), "" if args.all else "  (--all to list)"))
    if args.all:
        for shot, n, *_ in complete:
            print("  %-56s %4d" % (shot, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
