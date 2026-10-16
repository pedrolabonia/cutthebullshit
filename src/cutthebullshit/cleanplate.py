"""Clean-plate step: build one clean plate per frame with Photoshop Content-Aware Fill.

For each developed frame (<work>/.../<seq>_beauty.####.png, 16-bit; an older run's <seq>.####.exr):
  1. find what differs from the reference plate (object + shadow + bounce light), grow it generously,
     and turn it into selection polygons
  2. Photoshop: open the frame (16-bit sRGB TIFF), select those polygons, Content-Aware Fill, save
  3. write <seq>_plate.####.png (16-bit sRGB; an EXR next to an older run's EXR frames) next to the frame, plus
     <seq>_subject.####.png: Photoshop's Select Subject mask (white = object)
The Photoshop TIFFs are deleted once the plate is written (--keep-debug keeps them + a selection preview).

Outside the selection the plate is the frame's own pixels, so the background matches exactly.

    cutthebullshit cleanplate <work folder of a sequence> [--frames 4,5] [--grow 60]
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

import cv2
import numpy as np

from . import progress

from . import frames as fr
from .config import PHOTOSHOP, need_app, remove_file
from .prep import write_exr

PS_APP = PHOTOSHOP       # the newest installed Photoshop, or photoshop_app in the settings
SEQ_FILE_RX = re.compile(r"^(?P<seq>.+)\.(?P<num>\d{4})\.exr$")


def read_exr(path):
    import OpenEXR
    with OpenEXR.File(path) as f:
        return np.asarray(f.channels()["RGB"].pixels, np.float32)


def to_srgb(lin):
    x = np.clip(lin, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def from_srgb(s):
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)


def smooth_wall(loga, iters=5, deg=3, init=None):
    """Robust low-order polynomial fit of the wall's lighting (per channel, log space).

    Needs no reference plate: pixels that don't fit (object, shadow, bounce) are dropped each iteration."""
    h, w = loga.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx, yy = xx / w - 0.5, yy / h - 0.5
    terms = [xx ** i * yy ** j for i in range(deg + 1) for j in range(deg + 1 - i)]
    X = np.stack([t.ravel() for t in terms], 1)
    fit = np.zeros_like(loga)
    # start from wall-coloured pixels only, so a dark/bright object can't drag the first fit
    lum = loga.mean(axis=2).ravel()
    keep = np.abs(lum - np.median(lum)) < 0.25
    if init is not None and init.sum() > 0.05 * init.size:
        keep = init.ravel().copy()                     # known wall pixels (e.g. outside the subject)
    for _ in range(iters):
        res_all = np.zeros(h * w, np.float32)
        for c in range(3):
            y = loga[..., c].ravel()
            coef, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
            fit[..., c] = (X @ coef).reshape(h, w)
            res_all = np.maximum(res_all, np.abs(y - fit[..., c].ravel()))
        mad = 1.4826 * np.median(res_all[keep]) + 1e-4
        keep = res_all < 2.5 * mad
    return fit


def wall_plate(lin, subject=None, grow=60, thresh=0.06, feather=12):
    """Fallback plate when Content-Aware Fill can't run: the wall's smooth lighting, fitted only on pixels outside
    the (grown) subject, replaces the subject and whatever departs from that wall (shadow / bounce light).
    Returns (plate, filled mask)."""
    s = 8
    a = cv2.GaussianBlur(cv2.resize(lin, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA), (0, 0), 1.5)
    la = np.log(np.maximum(a, 1e-4))
    k = max(3, int(round(grow / s)) * 2 + 1)
    ell = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    sm = np.zeros(la.shape[:2], np.uint8)
    if subject is not None:
        sm = cv2.dilate((cv2.resize(subject, (la.shape[1], la.shape[0]), interpolation=cv2.INTER_AREA) > 127)
                        .astype(np.uint8), ell)
    fit = smooth_wall(la, init=(sm == 0) if sm.any() else None)
    out = (np.abs(la - fit).max(axis=2) > thresh).astype(np.uint8)
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fill = cv2.dilate(out | sm, ell)
    fill = cv2.resize(fill * 255, (lin.shape[1], lin.shape[0]), interpolation=cv2.INTER_LINEAR) > 127
    wall = np.exp(cv2.resize(fit, (lin.shape[1], lin.shape[0]), interpolation=cv2.INTER_CUBIC)).astype(np.float32)
    w = np.maximum(cv2.GaussianBlur(fill.astype(np.float32), (0, 0), feather), fill)[..., None]
    return (lin * (1 - w) + wall * w).astype(np.float32), fill


def change_mask(lin, thresh=0.06, grow=60):
    """Everything that departs from the wall (object, shadow, bounce light), grown by `grow` px."""
    s = 8                                              # work at 1/8 of the frame: smooth, fast
    a = cv2.resize(lin, None, fx=1 / s, fy=1 / s, interpolation=cv2.INTER_AREA)
    a = cv2.GaussianBlur(a, (0, 0), 1.5)
    la = np.log(np.maximum(a, 1e-4))
    d = np.abs(la - smooth_wall(la)).max(axis=2)
    m = (d > thresh).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m)
    keep = np.zeros(n, bool)
    if n > 1:
        big = stats[1:, cv2.CC_STAT_AREA].max()
        keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= max(20, 0.01 * big)
    m = keep[lab].astype(np.uint8)
    k = max(3, int(round(grow / s)) * 2 + 1)
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return cv2.resize(m * 255, (lin.shape[1], lin.shape[0]), interpolation=cv2.INTER_LINEAR) > 127


def mask_polygons(mask, eps=2.0):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polys = []
    for c in cnts:
        if cv2.contourArea(c) < 200:
            continue
        c = cv2.approxPolyDP(c, eps, True)
        pts = [[int(p[0][0]), int(p[0][1])] for p in c]
        if len({tuple(q) for q in pts}) >= 3 and cv2.contourArea(np.array(pts, np.int32)) > 0:
            polys.append(pts)                          # Photoshop rejects degenerate polygons (Illegal Argument)
    return polys


JSX = r"""
(function () {
    var job = %(job)s;
    app.displayDialogs = DialogModes.NO;
    var doc = app.open(new File(job.src)), step = "start";
    try {
        var first = true;
        var note = "";
        if (job.subject) {
            // Photoshop's own Select Subject, grown a little past the object's edge
            var found = true;
            step = "select subject";
            try {
                var s = new ActionDescriptor();
                s.putBoolean(stringIDToTypeID("sampleAllLayers"), false);
                executeAction(stringIDToTypeID("autoCutout"), s, DialogModes.NO);
            } catch (e) {
                found = false;            // nothing found (tiny / low-contrast object): empty subject, diff key only
            }
            // keep the subject exactly as Photoshop found it (before growing) -> the object's matte
            var ch = doc.channels.add();  // a new channel is black = no subject, if Select Subject found nothing
            ch.name = "subject";
            if (found) {
                try { doc.selection.store(ch); } catch (e) { found = false; }
            }
            doc.activeChannels = doc.componentChannels;   // fill the image, not the new channel
            if (found) {
                step = "grow subject";
                doc.selection.expand(new UnitValue(job.grow, "px"));
                first = false;
            } else {
                note = " nosubject";
                try { doc.selection.deselect(); } catch (e) {}
            }
        }
        // plus the shadow / bounce-light areas found by the wall fit
        step = "add shadow areas";
        for (var i = 0; i < job.polys.length; i++) {
            try {
                doc.selection.select(job.polys[i], first ? SelectionType.REPLACE : SelectionType.EXTEND, 0, true);
                first = false;
            } catch (e) {
                note += " badpoly";       // skip a shape Photoshop won't take rather than lose the frame
            }
        }
        var d = new ActionDescriptor();
        d.putEnumerated(charIDToTypeID("Usng"), charIDToTypeID("FlCn"), stringIDToTypeID("contentAware"));
        d.putBoolean(stringIDToTypeID("contentAwareColorAdaptationFill"), true);
        d.putUnitDouble(charIDToTypeID("Opct"), charIDToTypeID("#Prc"), 100);
        d.putEnumerated(charIDToTypeID("Md  "), charIDToTypeID("BlnM"), charIDToTypeID("Nrml"));
        if (!first) {                     // nothing selected: nothing to fill, the plate is the photo itself
            step = "content-aware fill";
            try {
                executeAction(charIDToTypeID("Fl  "), d, DialogModes.NO);
            } catch (e) {
                // "not enough source pixels": the area to fill covers too much of the frame -> Python fills it
                // from the smooth wall fit instead (the subject channel is still saved)
                note += " nocaf";
            }
            doc.selection.deselect();
        } else {
            note += " nofill";
        }
        step = "save";
        var o = new TiffSaveOptions();
        o.imageCompression = TIFFEncoding.NONE;
        o.layers = false;
        o.alphaChannels = true;
        doc.saveAs(new File(job.dst), o, true, Extension.LOWERCASE);
    } catch (e) {
        throw new Error(step + ": " + e.message);
    } finally {
        doc.close(SaveOptions.DONOTSAVECHANGES);
    }
    return "ok" + note;
})();
"""


def photoshop_fill(src_tif, dst_tif, polys, work_dir, grow=60, subject=True):
    """Fill (Photoshop Select Subject grown by `grow` px, if subject) + polys with Content-Aware Fill."""
    jsx = os.path.join(work_dir, "_fill.jsx")
    with open(jsx, "w") as fh:
        fh.write(JSX % {"job": json.dumps({"src": src_tif, "dst": dst_tif, "polys": polys, "grow": grow,
                                           "subject": subject})})
    # AppleScript gives up after 2 min by default; a busy Photoshop can take longer on one frame
    cmd = ["osascript", "-e", "with timeout of 900 seconds", "-e",
           'tell application "%s" to do javascript (read POSIX file "%s" as «class utf8»)' % (need_app(PS_APP, "Photoshop"), jsx),
           "-e", "end timeout"]
    err = ""
    for attempt in range(3):
        if attempt:
            close_doc(os.path.basename(src_tif))
            print("    Photoshop retry %d/2 (%s)" % (attempt, err[:120]), flush=True)
            time.sleep(5)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=960)
        except subprocess.TimeoutExpired:
            err = "no answer in 16 min"
            continue
        if r.returncode == 0 and "ok" in r.stdout:
            return r.stdout.strip()
        err = (r.stdout.strip() + " " + r.stderr.strip()).strip()
    raise RuntimeError("Photoshop: %s" % err)


def close_doc(name):
    """Close a document left open by a failed attempt, without saving."""
    js = ("for (var i = app.documents.length - 1; i >= 0; i--) { if (app.documents[i].name == '%s') "
          "app.documents[i].close(SaveOptions.DONOTSAVECHANGES); } 'ok';" % name.replace("'", ""))
    subprocess.run(["osascript", "-e", "with timeout of 60 seconds", "-e",
                    'tell application "%s" to do javascript "%s"' % (need_app(PS_APP, "Photoshop"), js.replace('"', '\\"')), "-e", "end timeout"],
                   capture_output=True, text=True, timeout=90)


def clean_frame(src, seq, num, grow, work_dir, select="photoshop", keep_debug=False):
    """src: the developed frame (16-bit beauty PNG, or an older run's EXR)."""
    folder = os.path.dirname(src)
    legacy = src.endswith(".exr")
    out = fr.plate_path(folder, seq, num) if not legacy else os.path.join(folder, "%s_plate.%s.exr" % (seq, num))
    lin = fr.read_linear(src)
    # shadow / bounce light (and the object) as departures from the wall's smooth lighting
    polys = mask_polygons(change_mask(lin, grow=grow))
    mask = None
    src_tif = os.path.join(work_dir, "%s.%s.tif" % (seq, num))
    dst_tif = os.path.join(work_dir, "%s_filled.%s.tif" % (seq, num))
    if legacy:
        s16 = (to_srgb(lin) * 65535 + 0.5).astype(np.uint16)
    else:                                              # the PNG's own 16-bit values, exactly
        s16 = cv2.cvtColor(cv2.imread(src, cv2.IMREAD_UNCHANGED)[..., :3], cv2.COLOR_BGR2RGB)
    cv2.imwrite(src_tif, s16[..., ::-1])
    t = time.time()
    res = photoshop_fill(src_tif, dst_tif, polys, work_dir, grow, subject=(select == "photoshop"))
    if "nosubject" in res:
        print("    Select Subject found nothing: empty subject mask, matte from the difference key only (check in QC)",
              flush=True)
    tif = cv2.imread(dst_tif, cv2.IMREAD_UNCHANGED)
    if select == "photoshop":
        if tif.ndim < 3 or tif.shape[2] < 4:
            raise RuntimeError("Photoshop saved no subject channel")
        subj = (tif[..., 3].astype(np.float32) / 65535 * 255 + 0.5).astype(np.uint8)
        cv2.imwrite(fr.subject_path(folder, seq, num), subj)
    filled = tif[..., :3][..., ::-1].astype(np.float32) / 65535
    plate = from_srgb(filled).astype(np.float32)
    if "nocaf" in res:
        # Content-Aware Fill had too few source pixels: fill the same selection from the wall's smooth lighting
        plate, mask = wall_plate(lin, subj if select == "photoshop" else None, grow)
        print("    Content-Aware Fill: not enough source pixels (%.0f%% of the frame) - filled from the wall fit "
              "(check in QC)" % (100 * mask.mean()), flush=True)
    if mask is None:   # what Photoshop changed = its selection
        mask = np.abs(filled - s16[..., :3].astype(np.float32) / 65535).max(axis=2) > 1.5 / 65535
        mask = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    # outside the selection keep the frame's exact values
    if legacy and "nocaf" not in res:  # (the wall-fit plate already does, with a soft edge)
        plate[~mask] = lin[~mask]
    if keep_debug:
        dbg = (to_srgb(cv2.resize(lin, None, fx=0.25, fy=0.25)) * 255).astype(np.uint8)[..., ::-1].copy()
        small = cv2.resize(mask.astype(np.uint8), (dbg.shape[1], dbg.shape[0]), interpolation=cv2.INTER_NEAREST)
        cs, _ = cv2.findContours(small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(dbg, cs, -1, (0, 0, 255), 2)
        cv2.imwrite(os.path.join(work_dir, "%s_selection.%s.jpg" % (seq, num)), dbg)
    if legacy:
        write_exr(out, plate)
    else:
        p16 = fr.srgb16(to_srgb(plate))
        if "nocaf" not in res:
            p16[~mask] = s16[..., :3][~mask]           # bit-identical to the frame outside the selection
        fr.write_png16(out, p16)
    remove_file(src_tif)
    if not keep_debug:
        remove_file(dst_tif)                           # the filled 16-bit TIFF: ~120 MB a frame, the plate has it all
    return out, len(polys), float(mask.mean()), time.time() - t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="work folder with developed frames (<seq>_beauty.####.png or <seq>.####.exr)")
    ap.add_argument("--frames", help="comma-separated frame numbers (default: all)")
    ap.add_argument("--grow", type=int, default=60, help="grow the object+shadow area by this many px (default %(default)s)")
    ap.add_argument("--select", choices=("photoshop", "difference"), default="photoshop",
                    help="photoshop = Select Subject + shadow/glow areas (default); difference = shadow/glow/object areas only")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--keep-debug", action="store_true", help="keep Photoshop's filled TIFF and a selection preview "
                                                                "in _photoshop/ (~120 MB a frame)")
    args = ap.parse_args(argv)
    work = os.path.join(args.folder, "_photoshop")
    os.makedirs(work, exist_ok=True)
    frames = fr.frames(args.folder)
    if args.frames:
        want = {int(x) for x in args.frames.split(",")}
        frames = [(s, n) for s, n in frames if int(n) in want]
    failed = 0
    for i, (seq, num) in enumerate(frames, 1):
        f = fr.frame_path(args.folder, seq, num)
        out = fr.plate_path(args.folder, seq, num)
        subj = fr.subject_path(args.folder, seq, num)
        from . import passes
        if not args.force and ((os.path.exists(out) and (os.path.exists(subj) or args.select != "photoshop"))
                               or passes.done(args.folder, seq, num)):
            print("[%d/%d] skip %s" % (i, len(frames), os.path.basename(out)), flush=True)
            progress.tick("cleanplate", skipped=True)
            continue
        try:
            out, n, frac, secs = clean_frame(f, seq, num, args.grow, work, args.select, args.keep_debug)
            print("[%d/%d] ok %s  %.1f%% of frame filled, Photoshop %.1fs" % (
                i, len(frames), os.path.basename(out), 100 * frac, secs), flush=True)
        except Exception as e:
            failed += 1
            print("[%d/%d] FAIL %s: %s" % (i, len(frames), os.path.basename(f), e), flush=True)
        progress.tick("cleanplate")
    if not args.keep_debug:                            # only _fill.jsx is left in _photoshop: remove it and the folder
        jsx = os.path.join(work, "_fill.jsx")
        if os.path.exists(jsx):
            remove_file(jsx)
        try:
            os.rmdir(work)
        except OSError:
            pass                                       # not empty (e.g. an older --keep-debug run's files): leave it
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
