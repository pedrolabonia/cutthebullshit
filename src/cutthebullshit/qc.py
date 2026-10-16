"""QC: flag frames whose cut-out matte looks wrong, so you only look at the ones that need a fix.

For every frame of an object it reads the work folder's <seq>_beauty, <seq>_subject (the matte: Photoshop's Select
Subject) and the <seq>_shadow / <seq>_bounce passes, and flags
  missed   part of the object left outside the matte: outside the subject mask the passes should hold only shadow
           and light, which change the table's brightness, not its colour. A strongly coloured change there with a
           hard edge against the table is object (a corner, a string, a thin part Select Subject dropped). In the
           After Effects comp such a part either vanishes or shows up as a coloured smear in the shadow / light.
  jump     the matte's area spikes against the frames on both sides (Select Subject lost or added a chunk on one
           frame); an object that moves in or grows steadily is fine
Thin strips along the matte's edge (its soft falloff) are ignored. Writes in the object's LAYERS folder:
  _qc.csv                        one row per frame
  _qc_sheet.jpg                  PREVIEW thumbnails, missed parts in magenta, flagged frames labelled in red
  _qc/<seq>.####_missedN.jpg     a zoom on every flagged spot (photo | marked | cut-out over a checkerboard)
Fix a flagged frame with the matte controls on its precomp in After Effects (grow), or by redoing its mask:
`cutthebullshit cleanplate --force --frames N <work folder>`, then passes / layers again.

    cutthebullshit qc                         every object in the newest run
    cutthebullshit qc --run 2
    cutthebullshit qc "<output>/RUN 02/LAYERS/S07 End Scene/diary-anim"     (or its work folder)
"""

import argparse
import csv
import glob
import os
import sys
from multiprocessing import Pool

import cv2
import numpy as np

from . import frames as fr
from .config import (LAYERS, default_workers, layers_dir, one_thread, previews_dir, read_dir, remove_file,
                     resolve_run, run_roots, split_run, shot_key)

# thresholds on the log change photo / table, linear light, per channel (the same scale the difference key used)
NOISE = 0.075       # mean change below this is noise
CHROMA = 0.6        # channels changing this differently = a colour change (shadow / light change all channels alike)
OBJ = -0.1          # brightest channel at least this (a shadow darkens every channel)
DEEP = 1.0          # ...unless the change is this deep (~2.7x): then darker in every channel is fine (a dark print,
                    # a black part); a hard contact shadow gets that deep too, but darkens the channels alike
MIN_BLOB = 250      # px (~0.002% of a 4752x3168 frame): smaller spots are ignored
SHARP = 0.6         # a missed part's border with the table is a hard edge (log-luminance gradient, p90);
                    # glow / tinted shadow fades out softly
JUMP = 0.08         # matte area change vs neighbouring frames that gets flagged
QC_GB = 1.5         # peak RAM of one frame here
THUMB = (594, 396)
MAGENTA = (255, 0, 255)


def blobs(mask, min_area):
    """Connected blobs of mask after dropping thin strips: [(x, y, w, h, area)], biggest first, and the cleaned mask."""
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m)
    out = [tuple(int(v) for v in st[i]) for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= min_area]
    return sorted(out, key=lambda b: -b[4]), m > 0


def table_change(b, shadow, bounce):
    """Per-channel log change photo / clean plate in linear light, from the photo and its passes (the plate itself is
    deleted once the passes are written): plate x shadow, screened with bounce = photo (display values, blurred
    the way the passes were made)."""
    bs = cv2.GaussianBlur(b, (0, 0), 4.0)
    eps = 1.0 / 255
    p = np.where(shadow < 1.0, bs / np.maximum(shadow, eps),
                 np.where(bounce > 0.0, 1.0 - (1.0 - bs) / np.maximum(1.0 - bounce, eps), bs))
    lin = lambda x: fr.from_srgb(np.clip(x, 0.0, 1.0))
    return np.log(np.maximum(lin(bs), 1e-4)) - np.log(np.maximum(lin(p), 1e-4))


def check_frame(b, shadow, bounce, alpha):
    """(matte area, missed blobs [(x, y, w, h, area, sharpness)], missed mask)"""
    lr = table_change(b, shadow, bounce)
    d, spread, mx = np.abs(lr).mean(2), lr.max(2) - lr.min(2), lr.max(2)
    objectlike = (d > NOISE) & (spread > CHROMA) & ((mx > OBJ) | (d > DEEP))
    cand_b, cand = blobs(objectlike & (alpha < 0.25), MIN_BLOB)
    missed_b, missed = [], np.zeros_like(cand)
    if cand_b:
        # keep candidates whose border with the table (away from the matte) is a hard edge
        lum = np.log(np.maximum(cv2.GaussianBlur(fr.from_srgb(b), (0, 0), 1).mean(2), 1e-4)).astype(np.float32)
        grad = np.hypot(cv2.Sobel(lum, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(lum, cv2.CV_32F, 0, 1, ksize=3))
        near_matte = cv2.dilate((alpha > 0.25).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        _, lab = cv2.connectedComponents(cand.astype(np.uint8))
        for bl in cand_b:
            x, y, w, h, _ = bl
            ids = np.unique(lab[y:y + h, x:x + w])
            sel = np.isin(lab, ids[ids > 0]) & cand
            ring = (cv2.dilate(sel.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & ~sel & ~near_matte
            sharp = float(np.percentile(grad[ring], 90)) if ring.sum() > 20 else 0.0
            if sharp >= SHARP:
                missed_b.append(bl + (round(sharp, 2),))
                missed |= sel
    return float((alpha > 0.5).mean()), missed_b, missed


def area_jump(areas, i):
    """How far frame i's matte area sticks out from its neighbours' (signed fraction). Inside a take it counts only
    as a spike, away from the frames on both sides in the same direction: an object that moves in or grows makes a
    step, which is fine. The first / last frame have one side only, so there it takes three times as much."""
    rel = lambda j: (areas[i] - areas[j]) / max(areas[j], 1e-6)
    if len(areas) < 2:
        return 0.0
    if 0 < i < len(areas) - 1:
        a, b = rel(i - 1), rel(i + 1)
        return round(float(min(a, b) if a > 0 and b > 0 else max(a, b) if a < 0 and b < 0 else 0.0), 3)
    return round(float(rel(1 if i == 0 else i - 1)) / 3, 3)


def to8(rgb):
    return cv2.cvtColor((np.clip(rgb, 0, 1) * 255).astype(np.uint8), cv2.COLOR_RGB2BGR)


def zoom(b, alpha, mask, box, path):
    x, y, w, h = box[:4]
    m = max(60, int(0.6 * max(w, h)))
    x0, y0 = max(0, x - m), max(0, y - m)
    x1, y1 = min(b.shape[1], x + w + m), min(b.shape[0], y + h + m)
    photo = to8(b[y0:y1, x0:x1])
    marked = photo.copy()
    marked[mask[y0:y1, x0:x1]] = MAGENTA
    al = alpha[y0:y1, x0:x1, None]
    chk = ((np.indices(al.shape[:2]).sum(0) // 12) % 2 * 60 + 140).astype(np.float32)[..., None]
    obj = (photo.astype(np.float32) * al + chk * (1 - al)).astype(np.uint8)
    img = np.hstack([photo, marked, obj])
    s = min(3.0, 1500.0 / img.shape[1])
    cv2.imwrite(path, cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST if s > 1 else cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 90])


def do_frame(job):
    rfolder, pfolder, zdir, seq, num = job
    tag = "%s.%s" % (seq, num)
    paths = [fr.frame_path(rfolder, seq, num), fr.subject_path(rfolder, seq, num)] + \
        [os.path.join(rfolder, "%s_%s.%s.png" % (seq, o, num)) for o in ("shadow", "bounce")]
    if not all(os.path.exists(p) for p in paths):
        return None
    b = fr.read_srgb(paths[0])
    alpha = cv2.imread(paths[1], cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255
    shadow, bounce = fr.read_png(paths[2]), fr.read_png(paths[3])
    area, missed_b, missed = check_frame(b, shadow, bounce, alpha)
    for i, bl in enumerate(missed_b[:3]):
        zoom(b, alpha, missed, bl, os.path.join(zdir, "%s_missed%d.jpg" % (tag, i + 1)))
    pv = cv2.imread(os.path.join(pfolder, "PREVIEW_%s.jpg" % tag))
    th = cv2.resize(pv if pv is not None else to8(b), THUMB, interpolation=cv2.INTER_AREA)
    small = cv2.resize(missed.astype(np.uint8), THUMB, interpolation=cv2.INTER_NEAREST)
    th[cv2.dilate(small, np.ones((5, 5), np.uint8)) > 0] = MAGENTA
    return {"sequence": seq, "frame": int(num), "matte_area": round(area, 4),
            "missed_px": sum(bl[4] for bl in missed_b), "missed_spots": len(missed_b), "_thumb": th}


def qc_object(folder, workers):
    """QC one object; folder is its LAYERS folder or its work folder. Returns the number of flagged frames."""
    rfolder, wfolder = read_dir(folder), layers_dir(folder)
    key = "%s/%s" % (split_run(folder)[0], shot_key(folder))
    todo = fr.frames(rfolder)
    if not todo:
        print("%s: no developed frames in %s" % (key, rfolder))
        return 0
    zdir = os.path.join(wfolder, "_qc")
    os.makedirs(zdir, exist_ok=True)
    for old in glob.glob(os.path.join(zdir, "*.jpg")):
        remove_file(old)
    jobs = [(rfolder, previews_dir(folder), zdir, seq, num) for seq, num in todo]
    n = max(1, min(workers, len(jobs)))
    if n > 1:
        with Pool(n, initializer=one_thread) as pool:
            res = pool.map(do_frame, jobs)
    else:
        res = [do_frame(j) for j in jobs]
    skipped = [j for j, r in zip(jobs, res) if r is None]
    if skipped:
        print("  %d frame(s) without mask / passes yet, skipped" % len(skipped))
    rows, tiles, flagged = [], [], 0
    for seq in sorted({r["sequence"] for r in res if r}):
        seq_rows = [r for r in res if r and r["sequence"] == seq]
        areas = np.array([x["matte_area"] for x in seq_rows])
        for i, x in enumerate(seq_rows):
            x["area_jump"] = area_jump(areas, i)
            issues = []
            if x["missed_spots"]:
                issues.append("missed %d spot(s) %d px" % (x["missed_spots"], x["missed_px"]))
            if abs(x["area_jump"]) > JUMP:
                issues.append("area jump %.0f%%" % (100 * x["area_jump"]))
            x["issues"] = "; ".join(issues)
            flagged += bool(issues)
            th = x.pop("_thumb")
            bar = np.full((40, th.shape[1], 3), (40, 40, 200) if issues else (50, 50, 50), np.uint8)
            cv2.putText(bar, "%s %04d  %s" % (seq[-24:], x["frame"], x["issues"] or "ok"), (6, 27),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(np.vstack([th, bar]))
            rows.append(x)
    if not rows:
        print("%s: nothing to check yet" % key)
        return 0
    with open(os.path.join(wfolder, "_qc.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    cols = min(4, len(tiles))
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
    cv2.imwrite(os.path.join(wfolder, "_qc_sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])

    print("== %s: %d frames, %d flagged   (sheet: %s)" % (key, len(rows), flagged, os.path.join(wfolder, "_qc_sheet.jpg")))
    for x in rows:
        if x["issues"]:
            print("   %s.%04d  %s" % (x["sequence"], x["frame"], x["issues"]))
    return flagged


def objects(run):
    """Every object folder of a run (LAYERS/<...>) that has cut-outs."""
    root = os.path.join(run_roots(resolve_run(run))[1], LAYERS)
    return sorted({os.path.dirname(p) for p in glob.glob(os.path.join(root, "**", "MULTIPLY_*.png"), recursive=True)})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="*", help="object folders, LAYERS or work (default: every object in the run)")
    ap.add_argument("--run", default="latest", help="run to check when no folders are given (default: latest)")
    ap.add_argument("--workers", type=int, default=default_workers(QC_GB), help="frames checked at once")
    args = ap.parse_args(argv)
    folders = args.folders or objects(args.run)
    if not args.folders:
        print("QC: %d object folder(s)" % len(folders))
    flagged = sum(qc_object(os.path.abspath(f), args.workers) for f in folders)
    print("\n%d flagged frame(s)" % flagged)
    return 0          # QC reports, it doesn't stop the workflow


if __name__ == "__main__":
    sys.exit(main())
