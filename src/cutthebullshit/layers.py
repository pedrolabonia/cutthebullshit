"""Layers step: the per-object deliverables, made with OpenCV from the frames passes.py finished.

For every frame with its <seq>_beauty, _subject, _shadow and _bounce in tmp_read it writes (cutthebullshit prores,
preview.py and publish.py read these):
    LAYERS/<shot>/<seq>.####.png            the object: beauty with the Select Subject mask as straight alpha
    LAYERS/<shot>/MULTIPLY_<seq>.####.png   shadow (Multiply)
    LAYERS/<shot>/SCREEN_<seq>.####.png     bounce light (Screen)
    LAYOUTS/<shot>/LAYOUT_<seq>.####.png    object + shadow + bounce in one RGBA on transparency, for quick layout over
                                            any background in Normal mode (shadow at --shadow-opacity): built for neutral
                                            middle grey, where it equals the After Effects precomp exactly
    PREVIEWS/PREVIEW_<seq>.####.jpg         half size, over --bg (image / colour / none, default: the settings' background): the After
                                            Effects scene comp exactly (display-space blending, shadow at --shadow-opacity)
Changing --bg re-renders an object's previews (its LAYERS folder keeps the background used in _preview_bg.txt).
Resumable: frames whose five outputs are newer than their inputs are skipped; --force redoes them.

    cutthebullshit layers "<tmp_read>/RUN 01/S01 Kitchen/teapot-anim/RAW"
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
from .config import (BG, SHADOW_OPACITY, bg_key, default_workers, layers_dir, layouts_dir, one_thread, parse_bg,
                    previews_dir)

LAYERS_GB = 2.0     # peak RAM of one frame here
LAYOUT_GREY = 0.5   # LAYOUT_ is exact over this neutral grey (display values, how After Effects blends here)


def frame_files(folder, seq, num):
    ins = (fr.frame_path(folder, seq, num), fr.subject_path(folder, seq, num),
           os.path.join(folder, "%s_shadow.%s.png" % (seq, num)), os.path.join(folder, "%s_bounce.%s.png" % (seq, num)))
    ld, tag = layers_dir(folder), "%s.%s" % (seq, num)
    outs = (os.path.join(ld, tag + ".png"), os.path.join(ld, "MULTIPLY_" + tag + ".png"),
            os.path.join(ld, "SCREEN_" + tag + ".png"), os.path.join(layouts_dir(folder), "LAYOUT_" + tag + ".png"),
            os.path.join(previews_dir(folder), "PREVIEW_" + tag + ".jpg"))
    return ins, outs


BG_FILE = "_preview_bg.txt"     # in LAYERS/<shot>: the background its PREVIEW_ renders were made over


def up_to_date(ins, outs, key=None):
    """All five outputs there and newer than the inputs; key: the background now asked for (None: don't check)."""
    if not all(os.path.exists(o) for o in outs):
        return False
    if key is not None:
        f = os.path.join(os.path.dirname(outs[0]), BG_FILE)
        if not os.path.exists(f) or open(f).read().strip() != key:
            return False
    return min(os.path.getmtime(o) for o in outs) >= max(os.path.getmtime(i) for i in ins)


def bg_image(kind, val, h, w):
    """The PREVIEW background at h x w: an image fit to height and centred, a colour, or middle grey for none."""
    if kind == "image":
        return fit_bg(cv2.cvtColor(cv2.imread(val), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0, h, w)
    rgb = val if kind == "color" else (0.5, 0.5, 0.5)
    return np.tile(np.array(rgb, np.float32), (h, w, 1))


def write(path, img, params=()):
    """8-bit image (uint8, BGR / BGRA) via .part, so a half-written file never looks done."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path[:-4] + ".part" + path[-4:]
    if not cv2.imwrite(tmp, img, list(params)):
        raise IOError("could not write %s" % tmp)
    os.replace(tmp, path)


def u8(x):
    return np.clip(np.round(x * 255.0), 0, 255).astype(np.uint8)


def fit_bg(bg, h, w):
    """The background image the way the scene comp places it: fit to height, centred (cropped / padded to w)."""
    k = h / bg.shape[0]
    b = cv2.resize(bg, (max(1, int(round(bg.shape[1] * k))), h), interpolation=cv2.INTER_AREA)
    x0 = (b.shape[1] - w) // 2
    if x0 >= 0:
        return b[:, x0:x0 + w]
    out = np.zeros((h, w, 3), np.float32)
    out[:, -x0:-x0 + b.shape[1]] = b
    return out


def composite(bg, obj, a, shadow, bounce, s):
    """The After Effects precomp over bg (display values): Multiply shadow at opacity s, Screen bounce, object on top."""
    c = bg * (1.0 - s * (1.0 - shadow))
    c = 1.0 - (1.0 - c) * (1.0 - bounce)
    return obj * a + c * (1.0 - a)


def layout(obj, a, shadow, bounce, s, base):
    """One straight-alpha RGBA that, over a background in Normal mode, gives what the precomp gives with Multiply
    (shadow at opacity s) and Screen (bounce). A single Normal layer can only match blend modes exactly over one colour:
    base, a neutral middle grey - exact there, and the shadow's darkening / the light's tint stay right in proportion
    over any background (only their strength drifts the further the background is from middle grey).
        shadow:  alpha = s * (1 - darkest channel of the shadow), colour = what base becomes under it
        bounce:  alpha = brightest channel of the light,           colour = what base becomes under it
    then the object over both."""
    base = base.reshape(1, 1, 3).astype(np.float32)
    m = 1.0 - s * (1.0 - shadow)                              # Multiply at opacity s: base -> base * m
    a_s = (1.0 - m.min(axis=2, keepdims=True))
    c_s = base * (m - (1.0 - a_s)) / np.maximum(a_s, 1e-6)    # Normal: base*(1-a) + c*a = base*m
    a_b = bounce.max(axis=2, keepdims=True)
    c_b = base + bounce * (1.0 - base) / np.maximum(a_b, 1e-6)   # Normal: base + a*(c-base) = screen(base, bounce)
    c_s, c_b = np.clip(c_s, 0, 1), np.clip(c_b, 0, 1)
    under = c_b * a_b + (1.0 - a_b) * (c_s * a_s)             # bounce over shadow, premultiplied
    a_u = a_b + (1.0 - a_b) * a_s
    prem = obj * a + (1.0 - a) * under
    alpha = a + (1.0 - a) * a_u
    rgb = prem / np.maximum(alpha, 1e-6)
    return rgb, alpha


def do_frame(job):
    folder, seq, num, bg, s, base = job
    t = time.time()
    ins, outs = frame_files(folder, seq, num)
    obj = fr.read_srgb(ins[0])
    a = cv2.imread(ins[1], cv2.IMREAD_GRAYSCALE).astype(np.float32)[..., None] / 255.0
    shadow, bounce = fr.read_png(ins[2]), fr.read_png(ins[3])
    h, w = a.shape[:2]
    # LAYERS: object with straight alpha (colour cleared where fully transparent: small files)
    o8 = u8(obj)
    o8[a[..., 0] <= 0] = 0
    write(outs[0], np.dstack([cv2.cvtColor(o8, cv2.COLOR_RGB2BGR), u8(a)]), (cv2.IMWRITE_PNG_COMPRESSION, 3))
    for src, dst in ((ins[2], outs[1]), (ins[3], outs[2])):     # the passes themselves, as MULTIPLY_ / SCREEN_
        with open(src, "rb") as fi:
            data = fi.read()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst + ".part", "wb") as fo:
            fo.write(data)
        os.replace(dst + ".part", dst)
    rgb, alpha = layout(obj, a, shadow, bounce, s, np.array(base, np.float32))
    write(outs[3], np.dstack([cv2.cvtColor(u8(rgb), cv2.COLOR_RGB2BGR), u8(alpha)]), (cv2.IMWRITE_PNG_COMPRESSION, 3))
    del rgb, alpha
    # PREVIEW at half size over the background, as in the scene comp
    hh, hw = h // 2, w // 2
    half = lambda x: cv2.resize(x, (hw, hh), interpolation=cv2.INTER_AREA)
    a2 = half(a)[..., None] if a.ndim == 3 else half(a)
    pv = composite(bg_image(bg[0], bg[1], hh, hw), half(obj), a2, half(shadow), half(bounce), s)
    write(outs[4], cv2.cvtColor(u8(pv), cv2.COLOR_RGB2BGR), (cv2.IMWRITE_JPEG_QUALITY, 92))
    return "%s.%s" % (seq, num), time.time() - t


def _safe(job):
    try:
        name, secs = do_frame(job)
        return name, secs, None
    except Exception as e:
        return "%s.%s" % (job[1], job[2]), 0.0, str(e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="tmp_read folders whose frames have their passes")
    ap.add_argument("--shadow-opacity", type=float, default=SHADOW_OPACITY,
                    help="shadow strength in LAYOUT_ and PREVIEW_, as in After Effects (default %(default)s)")
    ap.add_argument("--layout-grey", type=float, default=LAYOUT_GREY,
                    help="the neutral grey (0-1, display values) LAYOUT_ is exact over (default %(default)s: middle grey)")
    ap.add_argument("--bg", default=BG, help="PREVIEW background, as in the scene comps: an image (fit to height), a colour "
                                             "(#rrggbb, white, grey, 0.5, 200,190,170) or none (middle grey); "
                                             "default: background in the settings")
    ap.add_argument("--workers", type=int, default=default_workers(LAYERS_GB),
                    help="frames worked on at once (default %(default)s: one per core, cores - 2, as many as the RAM holds)")
    ap.add_argument("--force", action="store_true", help="redo frames whose outputs are already up to date")
    args = ap.parse_args(argv)
    try:
        bg, key = parse_bg(args.bg), bg_key(args.bg)
    except ValueError as e:
        if args.bg != BG:
            ap.error(str(e))                          # asked for: say so
        print("  %s - PREVIEWs over middle grey instead" % e)
        bg, key = ("color", (0.5, 0.5, 0.5)), bg_key("grey")
    print("layers: PREVIEW background %s" % (bg[1] if bg[0] == "image" else "%s %s" % (bg[0], bg[1] or "")), flush=True)
    # the colour LAYOUT_ is exact over: neutral middle grey, so it works over anyone's background
    base = [args.layout_grey] * 3
    todo, skipped, missing = [], 0, {}
    for folder in args.folders:
        for seq, num in fr.frames(folder):
            ins, outs = frame_files(folder, seq, num)
            if not all(os.path.exists(i) for i in ins):
                missing.setdefault(seq, []).append(num)
                continue
            if not args.force and up_to_date(ins, outs, key):
                skipped += 1
                progress.tick("layers", skipped=True)
                continue
            todo.append((folder, seq, num, bg, args.shadow_opacity / 100.0, base))
    for seq, nums in sorted(missing.items()):
        print("  skip %s frame(s) %s: no subject / passes yet (run the cleanplate and passes steps)" % (seq, ",".join(nums)))
    print("layers: %d frame(s) to do, %d already up to date (skipped)" % (len(todo), skipped), flush=True)
    failed, t0 = 0, time.time()
    if todo:
        with Pool(min(args.workers, len(todo)), initializer=one_thread) as pool:
            for i, (name, secs, err) in enumerate(pool.imap_unordered(_safe, todo), 1):
                if err:
                    failed += 1
                    print("[%d/%d] FAIL %s: %s" % (i, len(todo), name, err), flush=True)
                else:
                    print("[%d/%d] ok %s  %.1fs" % (i, len(todo), name, secs), flush=True)
                progress.tick("layers")
    # each object's LAYERS folder records the background its previews now have (all its frames are done over it)
    if not failed:
        for folder in args.folders:
            ld = layers_dir(folder)
            if os.path.isdir(ld):
                with open(os.path.join(ld, BG_FILE), "w") as fh:
                    fh.write(key + "\n")
    print("layers done in %.0fs: %d written, %d skipped, %d failed" % (time.time() - t0, len(todo) - failed, skipped, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
