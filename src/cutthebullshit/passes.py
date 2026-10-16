"""Passes step: the shadow and bounce-light passes of every frame, 8-bit sRGB PNGs next to it in tmp_read.

For each developed frame (<seq>_beauty.####.png from prep, 16-bit) with its <seq>_plate and <seq>_subject
(cleanplate.py) it writes
    <seq>_shadow.####.png   Multiply pass: beauty / clean plate where the photo is darker than the plate, else white
    <seq>_bounce.####.png   Screen pass: the light that makes the photo brighter than the plate, else black
(In an older run, whose frames are EXRs, it also writes the 8-bit <seq>_beauty.####.png After Effects uses.)
Once a frame's passes are written its 16-bit plate is deleted (nothing reads it again); from then on the passes
count as done for cleanplate too. Changing the passes later = `cutthebullshit cleanplate --force` on those frames first.
The two passes are worked out on display (sRGB) values, the way After Effects blends them, so
plate x shadow, screened with bounce, gives back the photo; over any other background they carry only the
object's shadow and bounce light, never the table (outside the clean-plate selection the plate is the photo, so
both passes are neutral there). Under the object the shadow / light found just outside it is carried in, so
the passes run on under the object's edge: growing or shrinking the matte in After Effects never opens a light seam.
The object itself is <seq>_beauty through <seq>_subject (Select Subject), in the AE precomp (aecomps.py).

Resumable: frames whose passes are newer than their frame, plate and subject mask are skipped; --force redoes them.

    cutthebullshit passes "<tmp_read>/RUN 01/S01 Kitchen/teapot-anim/v1/RAW"
"""

import argparse
import os
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

from . import frames as fr
from . import progress
from .config import default_workers, one_thread, remove_file
from .frames import to_srgb

OUTS = ("shadow", "bounce")
BLUR = 4.0          # px, light / shadow passes: the fill's grain stays out
FLOOR = 0.02        # changes smaller than this are noise, not shadow / light
SUBJECT_GROW = 3    # px the object area is grown before the passes go neutral under it


def frame_files(folder, seq, num):
    """((frame, plate, subject), (outputs)); an older run's EXR frame also gets its 8-bit beauty PNG here."""
    ins = (fr.frame_path(folder, seq, num), fr.plate_path(folder, seq, num), fr.subject_path(folder, seq, num))
    outs = tuple(os.path.join(folder, "%s_%s.%s.png" % (seq, o, num)) for o in OUTS)
    if ins[0].endswith(".exr"):
        outs = (fr.beauty_path(folder, seq, num),) + outs
    return ins, outs


def frames(folder):
    """[(seq, num)] of every frame in a tmp_read folder that has a clean plate and a subject mask, or whose passes
    are already done (its plate is deleted once they are written)."""
    out, missing = [], {}
    for seq, num in fr.frames(folder):
        ins, outs = frame_files(folder, seq, num)
        if all(os.path.exists(i) for i in ins) or done(folder, seq, num):
            out.append((seq, num))
        else:
            missing.setdefault(seq, []).append(num)
    for seq, nums in sorted(missing.items()):
        print("  skip %s frame(s) %s: no clean plate / subject mask (run the cleanplate step)" % (seq, ",".join(nums)))
    return out


def up_to_date(ins, outs):
    """Outputs all there and newer than the inputs that still exist (the plate is gone once the passes are done)."""
    if not all(os.path.exists(o) for o in outs):
        return False
    return min(os.path.getmtime(o) for o in outs) >= max(os.path.getmtime(i) for i in ins if os.path.exists(i))


def done(folder, seq, num):
    """True when a frame's passes are written and up to date: they also stand for its (deleted) clean plate."""
    ins, outs = frame_files(folder, seq, num)
    return os.path.exists(ins[2]) and up_to_date(ins, outs)


def write_png(path, rgb):
    """8-bit PNG from 0-1 floats (RGB or gray), written to .part first so a half-written file never looks done."""
    img = np.clip(np.round(rgb * 255.0), 0, 255).astype(np.uint8)
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    tmp = path[:-4] + ".part.png"
    if not cv2.imwrite(tmp, img, [cv2.IMWRITE_PNG_COMPRESSION, 3]):
        raise IOError("could not write %s" % tmp)
    os.replace(tmp, path)


def masked_blur(img, w, sigma):
    """Gaussian blur of img counting only pixels where w > 0 (normalized convolution), + how much weight was there.
    Wide blurs run at 1/4 size (same result for a blur that wide, far faster)."""
    num, den = img * w[..., None], w
    if sigma >= 16:
        h, wd = w.shape
        small = lambda x: cv2.resize(x, (wd // 4, h // 4), interpolation=cv2.INTER_AREA)
        big = lambda x: cv2.resize(x, (wd, h), interpolation=cv2.INTER_LINEAR)
        num = big(cv2.GaussianBlur(small(num), (0, 0), sigma / 4))
        den = big(cv2.GaussianBlur(small(den), (0, 0), sigma / 4))
    else:
        num = cv2.GaussianBlur(num, (0, 0), sigma)
        den = cv2.GaussianBlur(den, (0, 0), sigma)
    return num / np.maximum(den, 1e-6)[..., None], den


PASSES_GB = 2.8     # peak RAM of one frame here (measured: 2.6 GB)
FILL_PAD = 320      # px around the object the fill can reach (3 x its widest blur, 96 px)


def fill_under(img, w, neutral):
    """Carry the surrounding values in under the object (w == 0), coarser and coarser until it is covered,
    so the shadow / light runs on under the object's soft edge instead of stopping short of it (no light seam).
    Only the box around the object is worked on: outside it nothing changes, and a whole-frame pass would need
    several full-frame copies per frame (memory, when frames run in parallel)."""
    ys, xs = np.nonzero(w < 1.0)
    if not len(ys):
        return img
    h, wd = w.shape
    y0, y1 = max(0, ys.min() - FILL_PAD), min(h, ys.max() + 1 + FILL_PAD)
    x0, x1 = max(0, xs.min() - FILL_PAD), min(wd, xs.max() + 1 + FILL_PAD)
    img[y0:y1, x0:x1] = _fill(img[y0:y1, x0:x1], w[y0:y1, x0:x1], neutral)
    return img


def _fill(img, w, neutral):
    out, have = img.copy(), w.copy()
    for sigma in (6, 24, 96):
        if have.min() > 0.999:
            break
        fill, den = masked_blur(out, have, sigma)
        k = np.clip(den * 4.0, 0.0, 1.0)[..., None]                 # trust the fill only where it saw enough pixels
        fill = fill * k + neutral * (1.0 - k)
        hole = (1.0 - have)[..., None]
        out = out * (1.0 - hole) + fill * hole
        have = np.maximum(have, np.clip(den * 4.0, 0.0, 1.0))
    return out


def passes(b, p, subject):
    """(shadow, bounce) display-space float images from the frame and clean plate, both sRGB 0-1.
    Outside what Photoshop filled the plate is the frame itself, so both passes are neutral there: only the box
    around the filled area and the object is worked on (far less memory and time per frame)."""
    h, w = subject.shape
    shadow = np.ones((h, w, 3), np.float32)
    bounce = np.zeros((h, w, 3), np.float32)
    live = np.any(b != p, axis=2) | (subject > 0)
    ys, xs = np.nonzero(live)
    del live
    if not len(ys):
        return shadow, bounce
    pad = FILL_PAD + int(4 * BLUR) + 8
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + 1 + pad)
    sh, bo = _passes(b[y0:y1, x0:x1], p[y0:y1, x0:x1], subject[y0:y1, x0:x1])
    shadow[y0:y1, x0:x1], bounce[y0:y1, x0:x1] = sh, bo
    return shadow, bounce


def _passes(b, p, subject):
    # table pixels only: the object (grown past its soft edge, whose pixels are part object) never enters the blur
    obj = (subject > 127).astype(np.uint8)
    if SUBJECT_GROW:
        obj = cv2.dilate(obj, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * SUBJECT_GROW + 1,) * 2))
    w = 1.0 - obj.astype(np.float32)
    bs, _ = masked_blur(b, w, BLUR)
    ps, _ = masked_blur(p, w, BLUR)
    eps = 1.0 / 255
    shadow = np.where(bs < ps, bs / np.maximum(ps, eps), 1.0)                       # multiply: plate * shadow = photo
    bounce = np.where(bs > ps, 1.0 - (1.0 - bs) / np.maximum(1.0 - ps, eps), 0.0)  # screen: plate (+) bounce = photo
    shadow = 1.0 - np.maximum(1.0 - shadow - FLOOR, 0.0) / (1.0 - FLOOR)
    bounce = np.maximum(bounce - FLOOR, 0.0) / (1.0 - FLOOR)
    # under the object: the shadow / light found just outside it, carried in (the OBJECT layer covers the rest)
    shadow = fill_under(shadow, w, 1.0)
    bounce = fill_under(bounce, w, 0.0)
    return shadow, bounce


def do_frame(job):
    folder, seq, num = job
    ins, outs = frame_files(folder, seq, num)
    t = time.time()
    subject = cv2.imread(ins[2], cv2.IMREAD_GRAYSCALE)
    if subject is None:
        raise IOError("can't read %s" % ins[2])
    b, p = fr.read_srgb(ins[0]), fr.read_srgb(ins[1])
    imgs = passes(b, p, subject)
    if len(outs) > len(OUTS):                          # older run: the 8-bit beauty After Effects uses, from the EXR
        imgs = (b,) + imgs
    for path, img in zip(outs, imgs):
        write_png(path, img)
    if ins[1].endswith(".png"):                        # nothing reads the plate again: ~74 MB a frame freed
        remove_file(ins[1])                            # (an older run's EXR plate is left as it is)
    return "%s.%s" % (seq, num), time.time() - t


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="tmp_read folders with developed frames + _plate + _subject")
    ap.add_argument("--workers", type=int, default=default_workers(PASSES_GB),
                    help="frames worked on at once (default %(default)s: one per core, cores - 2, as many as the RAM holds)")
    ap.add_argument("--force", action="store_true", help="redo frames whose PNGs are already up to date")
    args = ap.parse_args(argv)
    todo, skipped = [], 0
    for folder in args.folders:
        for seq, num in frames(folder):
            ins, outs = frame_files(folder, seq, num)
            if args.force and not os.path.exists(ins[1]):
                print("  can't redo %s.%s: its clean plate was deleted after its passes (cutthebullshit cleanplate --force first)"
                      % (seq, num))
                continue
            if not args.force and up_to_date(ins, outs):
                skipped += 1
                progress.tick("passes", skipped=True)
                continue
            todo.append((folder, seq, num))
    print("passes: %d frame(s) to do, %d already up to date (skipped)" % (len(todo), skipped), flush=True)
    failed, t0 = 0, time.time()
    if todo:
        with Pool(min(args.workers, len(todo)), initializer=one_thread) as pool:
            results = pool.imap_unordered(_safe, todo)
            for i, (name, secs, err) in enumerate(results, 1):
                if err:
                    failed += 1
                    print("[%d/%d] FAIL %s: %s" % (i, len(todo), name, err), flush=True)
                else:
                    print("[%d/%d] ok %s  %.1fs" % (i, len(todo), name, secs), flush=True)
                progress.tick("passes")
    print("passes done in %.0fs: %d written, %d skipped, %d failed" % (time.time() - t0, len(todo) - failed, skipped, failed))
    return 1 if failed else 0


def _safe(job):
    try:
        name, secs = do_frame(job)
        return name, secs, None
    except Exception as e:
        return "%s.%s" % (job[1], job[2]), 0.0, str(e)


if __name__ == "__main__":
    sys.exit(main())
