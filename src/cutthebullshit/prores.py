"""Export every stop-motion of a run as ProRes 4444 with alpha, 1920 wide, 24 fps, on 2s.

For every stop-motion sequence in tmp_write/RUN NN/LAYERS (folders named -anim / _anim, more than one frame), writes
    tmp_write/RUN NN/PRORES/<scene>/<object>/.../<seq>.mov
from the object PNGs (straight alpha): each PNG is held for --hold frames (default 2: "on 2s", so 12 drawings per
second at 24 fps). The frames are scaled to 1920 wide keeping their proportions, nothing cropped or padded
(3:2 frames -> 1920x1280; --width to change). Edges are scaled premultiplied (no dark fringes), the file stays straight alpha; Rec.709 colour tags.
--passes object,multiply,screen also exports MULTIPLY_<seq>.mov / SCREEN_<seq>.mov.

A .mov newer than all its frames is skipped (resumable) unless --force.

    cutthebullshit prores --run 1
    cutthebullshit prores --run 1 "S02 Garden" --passes object,multiply,screen --force
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import imageio_ffmpeg

from .config import LAYERS, resolve_run, run_name, run_roots

OBJ_RX = re.compile(r"^(?P<seq>(?!MULTIPLY_|SCREEN_|PREVIEW_|LAYOUT_).+)\.(?P<num>\d{4})\.png$")
ANIM_RX = re.compile(r"[-_]anim$", re.I)
PREFIX = {"object": "", "multiply": "MULTIPLY_", "screen": "SCREEN_"}


def stopmotions(layers_root, only=()):
    """[(folder, seq, [frame numbers])] for every sequence with > 1 frame below an -anim / _anim folder."""
    out = []
    for d, dirs, files in os.walk(layers_root):
        dirs[:] = sorted(x for x in dirs if not x.startswith(("_", ".")))
        rel = os.path.relpath(d, layers_root)
        if only and not any(rel == o or rel.startswith(o.rstrip("/") + os.sep) for o in only):
            continue
        if not any(ANIM_RX.search(p) for p in rel.split(os.sep)):
            continue
        seqs = {}
        for f in files:
            m = OBJ_RX.match(f)
            if m and not f.startswith("._"):
                seqs.setdefault(m.group("seq"), []).append(int(m.group("num")))
        for seq, nums in sorted(seqs.items()):
            if len(nums) > 1:
                out.append((d, seq, sorted(nums)))
    return out


def vf(width):
    scale = "scale=%d:-2:flags=lanczos" % width          # keeps the aspect (even height, as ProRes needs)
    # premultiply before scaling so transparent pixels' colour doesn't bleed into the edges, then back to straight
    return ("format=rgba,premultiply=inplace=1,%s,unpremultiply=inplace=1,"
            "scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le" % scale)


def encode(frames, out, fps, hold, width):
    """frames: ordered PNG paths. Each is linked `hold` times into a temp folder, so ffmpeg reads a plain sequence."""
    tmp = tempfile.mkdtemp(prefix="prores_")
    try:
        i = 0
        for f in frames:
            for _ in range(hold):
                i += 1
                os.symlink(f, os.path.join(tmp, "f%06d.png" % i))
        part = out + ".part.mov"
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
               "-framerate", str(fps), "-i", os.path.join(tmp, "f%06d.png"),
               "-vf", vf(width), "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
               "-alpha_bits", "16", "-vendor", "apl0",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-r", str(fps), part]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-400:])
        os.replace(part, out)
        return i
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("only", nargs="*", help="limit to these folders below LAYERS, e.g. \"S02 Garden\" or \"S02 Garden/swing-anim\"")
    ap.add_argument("--run", default="latest", help="run number (default: the latest)")
    ap.add_argument("--fps", type=int, default=24, help="movie frame rate (default %(default)s)")
    ap.add_argument("--hold", type=int, default=2, help="frames each drawing is held (default %(default)s: on 2s)")
    ap.add_argument("--width", type=int, default=1920, help="movie width; height follows the frames' aspect (default %(default)s)")
    ap.add_argument("--passes", default="object", help="comma list of object,multiply,screen (default %(default)s)")
    ap.add_argument("--out", default=None, help="output root (default tmp_write/RUN NN/PRORES)")
    # (publish.py runs this before uploading, so the movies in Dropbox always match the published frames)
    ap.add_argument("--force", action="store_true", help="re-export movies that are up to date")
    args = ap.parse_args(argv)
    passes = [p.strip() for p in args.passes.split(",") if p.strip()]
    bad = [p for p in passes if p not in PREFIX]
    if bad:
        ap.error("unknown pass(es): %s" % ", ".join(bad))

    run_no = resolve_run(args.run)
    _, write_root = run_roots(run_no)
    layers_root = os.path.join(write_root, LAYERS)
    out_root = args.out or os.path.join(write_root, "PRORES")
    seqs = stopmotions(layers_root, args.only)
    print("%s: %d stop-motion sequence(s), %s, %d wide %d fps on %ds -> %s" % (
        run_name(run_no), len(seqs), "+".join(passes), args.width, args.fps, args.hold, out_root), flush=True)
    t0, made, skipped, failed = time.time(), 0, 0, 0
    for k, (folder, seq, nums) in enumerate(seqs, 1):
        rel = os.path.relpath(folder, layers_root)
        for p in passes:
            frames = [os.path.join(folder, "%s%s.%04d.png" % (PREFIX[p], seq, n)) for n in nums]
            missing = [f for f in frames if not os.path.exists(f)]
            if missing:
                print("[%d/%d] skip %s%s: %d frame(s) missing" % (k, len(seqs), PREFIX[p], seq, len(missing)))
                continue
            out = os.path.join(out_root, rel, "%s%s.mov" % (PREFIX[p], seq))
            if (not args.force and os.path.exists(out)
                    and os.path.getmtime(out) >= max(os.path.getmtime(f) for f in frames)):
                skipped += 1
                continue
            os.makedirs(os.path.dirname(out), exist_ok=True)
            t = time.time()
            try:
                n = encode(frames, out, args.fps, args.hold, args.width)
                made += 1
                print("[%d/%d] %s  %d drawings -> %d frames (%.1fs)  %.1fs" % (
                    k, len(seqs), os.path.join(rel, os.path.basename(out)), len(frames), n, n / args.fps,
                    time.time() - t), flush=True)
            except Exception as e:
                failed += 1
                print("[%d/%d] FAIL %s: %s" % (k, len(seqs), out, e), flush=True)
    print("done in %.0fs: %d written, %d up to date, %d failed" % (time.time() - t0, made, skipped, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
