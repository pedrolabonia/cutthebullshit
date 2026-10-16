"""Prep step: develop the RAWs, once, into the half-resolution 16-bit sRGB PNGs the rest of the pipeline uses.

Stop-motion folders (a parent folder ends in -anim / _anim) become one sequence per folder,
numbered by the take's own frame number:
    .../teapot-anim/RAW/S01_teapot-anim_v1_0003_0001_014_01_X1_0033.arw     (any RAW, or TIFF / JPEG / PNG)
 -> <work>/RUN NN/<path below the mirror root>/S01_teapot-anim_v1_beauty.0003.png
Every other photo is a still, a single-frame item of its own:
    .../spoon/v3/RAW/S01_spoon_v3_0002_0001_025_01_X1_0004.arw  ->  S01_spoon_v3_0002_beauty.0001.png

That <seq>_beauty PNG is the photo all the way through: cleanplate and passes read it, After Effects uses it.
Frames are 16-bit sRGB at half the camera's size (half_size / crop in the settings), denoised
(wavelet denoise in the RAW development by default, --denoise strong adds non-local means), at the camera's own
exposure and white balance (--exposure N brightens with a soft highlight roll-off). A _frames.csv next to them maps frame numbers back
to the original photo names.

    cutthebullshit prep <src_folder> [<src_folder> ...]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from multiprocessing import Pool

import numpy as np

from . import progress

from . import frames as fr
from .config import CROP, HALF_SIZE, PHOTO_FOLDER, SEQUENCE_PATTERN, STOP_MOTION_SUFFIXES, is_raw
from .config import MIRROR_DEPTH, default_workers, one_thread, frame_name, list_frames, mirror_dir, mirror_parts, resolve_run, run_roots

SEQ_RX = re.compile(SEQUENCE_PATTERN)       # settings: sequence_pattern (default S01_teapot-anim_v1_0003_...)


def is_animation(src):
    """A photo is a stop-motion frame when one of its parent folders ends in a stop-motion suffix (default -anim /
    _anim; versions inside it, e.g. teapot-anim/v1, are separate animations). Everything else is a still."""
    return any(p.lower().endswith(tuple(s.lower() for s in STOP_MOTION_SUFFIXES)) for p in mirror_parts(src))


def anim_name(src):
    """A stop-motion's name from its folders, for photos whose names don't follow sequence_pattern: the stop-motion
    folder and any below it except the photo folder (teapot-anim/v1/RAW -> teapot-anim_v1)."""
    parts = mirror_parts(src)
    ends = tuple(x.lower() for x in STOP_MOTION_SUFFIXES)
    i = max(j for j, p in enumerate(parts) if p.lower().endswith(ends))
    keep = [p for p in parts[i:] if not (PHOTO_FOLDER and p == PHOTO_FOLDER)]
    return re.sub(r"\s+", "-", "_".join(keep))


def sequence_name(src, index):
    """(sequence name, frame number) for a source photo.

    stop-motion: S01_teapot-anim_v1_0003_0001_014_01_X1_0033 -> (S01_teapot-anim_v1, 3)
    still:       S01_spoon_v3_0002_0001_025_01_X1_0004               -> (S01_spoon_v3_0002, 1)"""
    m = SEQ_RX.match(frame_name(src))
    if is_animation(src):
        if m:
            return m.group("base"), int(m.group("num"))
        return anim_name(src), index
    if m:
        return "%s_%s" % (m.group("base"), m.group("num")), 1
    return frame_name(src), 1


RAW_NOISE_THR = 1000     # LibRaw wavelet denoise threshold (0 = off): ~3x less noise, keeps paper/wall texture


def develop_arw(path, noise_thr=RAW_NOISE_THR):
    """A photo -> linear RGB (sRGB primaries), at half size unless half_size = false in the settings, centre-cropped to
    `crop` (full-size [width, height]) if set.

    RAW (any format LibRaw reads): camera white balance, no auto brightness; half size merges each 2x2 Bayer quad
    instead of demosaicing (4x faster, less noisy); noise_thr runs LibRaw's wavelet denoise on the RAW data.
    TIFF / JPEG / PNG: already developed, taken as sRGB (8 or 16 bit) and only made linear / halved / cropped."""
    if is_raw(path):
        import rawpy
        with rawpy.imread(path) as r:
            a = r.postprocess(half_size=HALF_SIZE, use_camera_wb=True, no_auto_bright=True, gamma=(1, 1), output_bps=16,
                              output_color=rawpy.ColorSpace.sRGB, user_flip=0, noise_thr=noise_thr or None,
                              highlight_mode=rawpy.HighlightMode.Blend)   # clipped channels blend to white, no flat patches
        a = a.astype(np.float32) / 65535.0
        scale = 2 if HALF_SIZE else 1
    else:
        import cv2
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            raise IOError("can't read %s" % path)
        img = img[..., :3] if img.ndim == 3 else np.dstack([img] * 3)
        s = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / (65535.0 if img.dtype == np.uint16 else 255.0)
        a = np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4).astype(np.float32)
        scale = 1
        if HALF_SIZE:
            a = cv2.resize(a, (a.shape[1] // 2, a.shape[0] // 2), interpolation=cv2.INTER_AREA)
            scale = 2
    if CROP:
        cw, ch = int(CROP[0]) // scale, int(CROP[1]) // scale
        h, w = a.shape[:2]
        if h >= ch and w >= cw:
            y0, x0 = (h - ch) // 2, (w - cw) // 2
            a = a[y0:y0 + ch, x0:x0 + cw]
    return np.ascontiguousarray(a)


def rolloff(x, knee=0.8):
    """Soft highlight shoulder: values above `knee` roll off toward 1.0 instead of clipping (in place)."""
    over = x > knee
    x[over] = knee + (1 - knee) * np.tanh((x[over] - knee) / (1 - knee))
    return x


MIDTONES = 1.15     # display-space gamma: >1 lifts the midtones (black and white stay put)
CONTRAST = 0.25     # gentle S-curve around mid-grey so the lift doesn't look washed out (0 = none)


def tone(lin, midtones=MIDTONES, contrast=CONTRAST):
    """Midtone lift + gentle S-curve, done on display (sRGB) values and returned linear. Expects 0..1 input
    (after exposure + roll-off); 0, 0.5 (display) and 1 are fixed points of the S-curve."""
    if midtones == 1 and not contrast:
        return lin
    x = np.clip(lin, 0, 1)
    s = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    if midtones != 1:
        s = np.power(s, 1.0 / midtones)
    if contrast:
        s = (1 - contrast) * s + contrast * (s * s * (3 - 2 * s))          # blend with smoothstep
    return np.where(s <= 0.04045, s / 12.92, np.power((s + 0.055) / 1.055, 2.4)).astype(np.float32)


def camera_jpeg_linear(src):
    """The camera's own JPEG preview embedded in a RAW, as linear float RGB (IOError if it has none)."""
    import cv2
    import rawpy
    with rawpy.imread(src) as r:
        th = r.extract_thumb()
    if th.format != rawpy.ThumbFormat.JPEG:
        raise IOError("no embedded JPEG in %s" % src)
    s = cv2.imdecode(np.frombuffer(th.data, np.uint8), cv2.IMREAD_COLOR)[..., ::-1].astype(np.float32) / 255
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4).astype(np.float32)


def fit_camera_look(dev, cam):
    """Per-channel curves taking our linear development to the camera JPEG's look (tone curve, white balance,
    contrast), by matching percentiles - no pixel alignment needed. Returns [[xs, ys]] * 3 (JSON-able)."""
    import cv2
    small = cv2.resize(dev, (cam.shape[1], cam.shape[0]), interpolation=cv2.INTER_AREA)
    q = np.linspace(0, 100, 1025)
    curves = []
    for c in range(3):
        xs = np.percentile(small[..., c], q)
        ys = np.percentile(cam[..., c], q)
        xs = np.maximum.accumulate(xs + np.arange(len(xs)) * 1e-7)
        ys = np.maximum.accumulate(ys)
        curves.append([[0.0] + xs.tolist() + [float(xs[-1]) * 4], [0.0] + ys.tolist() + [1.0]])
    return curves


def apply_camera_look(dev, curves):
    out = np.empty_like(dev)
    for c in range(3):
        out[..., c] = np.interp(dev[..., c], curves[c][0], curves[c][1])
    return out


def apply_exposure(lin, stops, knee=0.8):
    """Brighten by `stops`, then the soft highlight roll-off."""
    x = lin * np.float32(2.0 ** stops) if stops else lin.copy()
    return rolloff(x, knee)


def nlmeans(lin, h_luma=2.0, h_chroma=6.0):
    """Strong extra denoise: non-local means in sRGB, gentle on luma, strong on chroma (~12x less noise;
    smooths fine paper/wall texture)."""
    import cv2
    x = np.clip(lin, 0, 1)
    s = np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)
    y = 0.2126 * s[..., 0] + 0.7152 * s[..., 1] + 0.0722 * s[..., 2]
    to16 = lambda v, off: np.clip(v * 65535 + off, 0, 65535).astype(np.uint16)
    yd = cv2.fastNlMeansDenoising(to16(y, 0), h=[h_luma * 655.35], templateWindowSize=5, searchWindowSize=11,
                                  normType=cv2.NORM_L1).astype(np.float32) / 65535
    c = cv2.fastNlMeansDenoising(np.dstack([to16(s[..., 0] - y, 32768), to16(s[..., 2] - y, 32768)]),
                                 h=[h_chroma * 655.35], templateWindowSize=5, searchWindowSize=15, normType=cv2.NORM_L1)
    r = (c[..., 0].astype(np.float32) - 32768) / 65535 + yd
    b = (c[..., 1].astype(np.float32) - 32768) / 65535 + yd
    g = (yd - 0.2126 * r - 0.0722 * b) / 0.7152
    s2 = np.clip(np.dstack([r, g, b]), 0, 1)
    out = np.where(s2 <= 0.04045, s2 / 12.92, ((s2 + 0.055) / 1.055) ** 2.4).astype(np.float32)
    return np.where(lin > 1, lin, out)        # keep highlights above 1 untouched


def write_exr(path, rgb):
    import OpenEXR
    header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
    tmp = path + ".tmp.exr"
    with OpenEXR.File(header, {"RGB": rgb.astype(np.float16)}) as f:
        f.write(tmp)
    os.replace(tmp, path)


PREP_GB = 1.4       # peak RAM of one develop_frame (measured: 1.35 GB)


def camera_curves_for(src, lin):
    """The camera look of a sequence, fitted on this photo: [] when there is none to match (an already developed
    TIFF / JPEG keeps its own look; a RAW without an embedded JPEG preview gets the plain development)."""
    if not is_raw(src):
        return []
    try:
        return fit_camera_look(lin, camera_jpeg_linear(src))
    except Exception as e:
        print("  no camera look for %s (%s): plain development" % (os.path.basename(src), e), flush=True)
        return []


def develop_frame(job):
    """One frame, in its own process: RAW -> look -> 16-bit beauty PNG. curves None (camera look) = fit them on this
    frame and save them as the sequence's _look json. Returns (index, name, error or None, seconds, max, curves)."""
    i, src, out, look_path, denoise, look, curves, exposure, midtones, contrast = job
    t = time.time()
    try:
        if os.path.getsize(src) == 0:
            raise IOError("0-byte file (a cloud online-only placeholder? make it available offline)")
        # camera exposure and white balance as shot: every frame gets its own clean plate, so no matching
        lin = develop_arw(src, RAW_NOISE_THR if denoise in ("raw", "strong") else 0)
        if denoise == "strong":
            lin = nlmeans(lin)
        if look == "camera":
            if curves is None:
                curves = camera_curves_for(src, lin)
                with open(look_path, "w") as fh:
                    json.dump(curves, fh)
            if curves:                                # [] = no camera look to match (a TIFF / JPEG, or no preview)
                lin = apply_camera_look(lin, curves)
            if exposure or midtones != 1 or contrast:
                lin = tone(apply_exposure(lin, exposure), midtones, contrast)
        else:
            lin = tone(apply_exposure(lin, exposure), midtones, contrast)
        fr.write_png16(out, fr.srgb16(fr.to_srgb(lin)))
        return i, os.path.basename(out), None, time.time() - t, float(lin.max()), curves
    except Exception as e:
        return i, frame_name(src), str(e), time.time() - t, 0.0, None


def prep_folder(src_dir, depth, force=False, denoise="raw", read_root=None, exposure=0.0, midtones=MIDTONES,
                contrast=CONTRAST, look="camera", workers=None):
    frames = list_frames(src_dir)
    if not frames:
        print("no photos in %s" % src_dir)
        return 0
    out_dir = mirror_dir(read_root, frames[0], depth)
    os.makedirs(out_dir, exist_ok=True)
    rows, failed, todo = [], 0, []
    print("== %s (%d frames) -> %s" % (src_dir, len(frames), out_dir), flush=True)
    for i, src in enumerate(frames, 1):
        base, num = sequence_name(src, i)
        # an older run's EXR counts as developed too (nothing is developed twice); new frames are 16-bit PNGs
        done = fr.frame_path(out_dir, base, "%04d" % num)
        out = fr.beauty_path(out_dir, base, "%04d" % num)
        rows.append({"sequence": base, "frame": num, "file": os.path.basename(done if os.path.exists(done) else out),
                     "source": frame_name(src)})
        if not force and os.path.exists(done) and os.path.getmtime(done) >= os.path.getmtime(src):
            print("[%d/%d] skip %s" % (i, len(frames), os.path.basename(done)), flush=True)
            progress.tick("prep", skipped=True)
            continue
        todo.append((i, src, base, out))

    def job(i, src, base, out, curves):
        return (i, src, out, os.path.join(out_dir, "_look_%s.json" % base), denoise, look, curves, exposure,
                midtones, contrast)

    def report(res):
        i, name, err, secs, mx, curves = res
        if err:
            print("[%d/%d] FAIL %s: %s" % (i, len(frames), name, err), flush=True)
        else:
            print("[%d/%d] ok %s  max %.2f  (%.1fs)" % (i, len(frames), name, mx, secs), flush=True)
        progress.tick("prep")
        return 1 if err else 0

    # camera look: one curve per sequence (no flicker), fitted on its first frame and kept on disk as _look_<seq>.json.
    # A stop-motion's first frame to do is developed first (it fits the curve if there is none), the rest after it.
    curves, jobs, first = {}, [], []
    for i, src, base, out in todo:
        path = os.path.join(out_dir, "_look_%s.json" % base)
        if look == "camera" and base not in curves:
            if os.path.exists(path) and not force:
                with open(path) as fh:
                    curves[base] = json.load(fh)
            else:
                seq_first = next(f for k, f in enumerate(frames, 1) if sequence_name(f, k)[0] == base)
                if seq_first == src:
                    curves[base] = None                # this frame fits it
                    first.append(job(i, src, base, out, None))
                    continue
                # the sequence's first photo is done already but its curve file is gone: fit it again from it
                dev = develop_arw(seq_first, RAW_NOISE_THR if denoise in ("raw", "strong") else 0)
                curves[base] = camera_curves_for(seq_first, dev)
                with open(path, "w") as fh:
                    json.dump(curves[base], fh)
        jobs.append((i, src, base, out))
    n = max(1, min(workers or default_workers(PREP_GB), len(first) + len(jobs)))
    if first or jobs:
        print("   developing %d frame(s), %d at once" % (len(first) + len(jobs), n), flush=True)
    with Pool(n, initializer=one_thread) as pool:
        # first frames that fit a stop-motion's curve go before the rest of that stop-motion
        seq_of = {i: base for i, _, base, _ in todo}
        for res in pool.imap_unordered(develop_frame, first):
            failed += report(res)
            if res[5] is not None:
                curves[seq_of[res[0]]] = res[5]
        rest = []
        for i, src, base, out in jobs:
            if look == "camera" and curves.get(base) is None:
                failed += 1                           # its first frame failed: no curve to match the others to
                print("[%d/%d] FAIL %s: the first frame of %s failed, so it has no look" % (i, len(frames),
                                                                                           frame_name(src), base))
                progress.tick("prep")
                continue
            rest.append(job(i, src, base, out, curves.get(base)))
        for res in pool.imap_unordered(develop_frame, rest):
            failed += report(res)
    with open(os.path.join(out_dir, "_frames.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["sequence", "frame", "file", "source"])
        w.writeheader()
        w.writerows(rows)
    for base in sorted({r["sequence"] for r in rows}):
        nums = [r["frame"] for r in rows if r["sequence"] == base]
        print("   sequence %s  frames %d-%d (%d)" % (base, min(nums), max(nums), len(nums)), flush=True)
    return failed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sources", nargs="+", help="photo folders (RAW of any camera, or TIFF / JPEG / PNG), e.g. <photos>/S01 Kitchen/teapot-anim/RAW")
    ap.add_argument("--depth", type=int, default=MIRROR_DEPTH, help="parent folders to mirror (default %(default)s)")
    ap.add_argument("--force", action="store_true", help="redo frames that already exist")
    ap.add_argument("--denoise", choices=("off", "raw", "strong"), default="raw",
                    help="raw = wavelet denoise in the RAW development (default, ~3x less noise); strong = + non-local "
                         "means (~12x, smooths fine texture); off")
    ap.add_argument("--run", default="new", help="'new' (default), 'latest' or a run number")
    ap.add_argument("--workers", type=int, default=None, help="frames developed at once (default: cores - 2, capped by RAM)")
    ap.add_argument("--look", choices=("camera", "linear"), default="camera",
                    help="camera = match the camera's own JPEG preview embedded in each RAW (default); linear = the "
                         "plain development + --exposure / --midtones / --contrast")
    ap.add_argument("--exposure", type=float, default=None,
                    help="brighten by this many stops before the 8-bit outputs (default %(default)s, about the look of the "
                         "first renders; 0 = camera exposure); highlights roll off softly")
    ap.add_argument("--midtones", type=float, default=None, help="midtone lift, display gamma (linear look default %s; 1 = none)" % MIDTONES)
    ap.add_argument("--contrast", type=float, default=None, help="gentle S-curve (linear look default %s; 0 = none)" % CONTRAST)
    args = ap.parse_args(argv)
    lin_look = args.look == "linear"          # extra adjustments: defaults only for the linear look
    if args.exposure is None:
        args.exposure = 1.4 if lin_look else 0.0
    if args.midtones is None:
        args.midtones = MIDTONES if lin_look else 1.0
    if args.contrast is None:
        args.contrast = CONTRAST if lin_look else 0.0
    read_root = run_roots(resolve_run(args.run))[0]
    failed = sum(prep_folder(s, args.depth, args.force, args.denoise, read_root, args.exposure, args.midtones, args.contrast,
                             args.look, args.workers) for s in args.sources)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
