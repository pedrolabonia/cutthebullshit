"""Preview step: a light .mp4 of every stop-motion sequence (more than one frame), from the PREVIEW_ renders.

    tmp_write/RUN NN/PREVIEWS/PREVIEW_<seq>.mp4      H.264, 1920 px wide, 12 fps (one photo per frame)

    cutthebullshit preview "<tmp_write>/RUN 01/LAYERS/S01 Kitchen/teapot-anim"
"""

import argparse
import glob
import os
import re
import sys

import cv2

from . import progress
from .config import previews_dir

PV_RX = re.compile(r"^PREVIEW_(?P<seq>.+)\.(?P<num>\d{4})\.jpg$")
OBJ_RX = re.compile(r"^(?P<seq>(?!MULTIPLY_|SCREEN_|PREVIEW_|LAYOUT_).+)\.(?P<num>\d{4})\.png$")


def make_mp4(folder, seq, nums, fps, width):
    first = cv2.imread(os.path.join(folder, "PREVIEW_%s.%04d.jpg" % (seq, nums[0])))
    h = int(round(first.shape[0] * width / first.shape[1] / 2)) * 2          # H.264 wants even sizes
    out = os.path.join(folder, "PREVIEW_%s.mp4" % seq)
    tmp = out + ".tmp.mp4"
    w = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"avc1"), fps, (width, h))
    if not w.isOpened():
        raise RuntimeError("no H.264 encoder (avc1) available")
    for n in range(nums[0], nums[-1] + 1):
        img = cv2.imread(os.path.join(folder, "PREVIEW_%s.%04d.jpg" % (seq, n)))
        if img is None:                                   # missing frame: hold the previous one
            continue
        frame = cv2.resize(img, (width, h), interpolation=cv2.INTER_AREA)
        w.write(frame)
    w.release()
    os.replace(tmp, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="object folders (LAYERS/<shot>) of a run")
    ap.add_argument("--fps", type=float, default=12)
    ap.add_argument("--width", type=int, default=1920)
    args = ap.parse_args(argv)
    for obj_folder in args.folders:
        own = {m.group("seq") for m in (OBJ_RX.match(os.path.basename(p)) for p in glob.glob(os.path.join(obj_folder, "*.png"))) if m}
        folder = previews_dir(obj_folder)
        seqs = {}
        for p in glob.glob(os.path.join(folder, "PREVIEW_*.jpg")):
            m = PV_RX.match(os.path.basename(p))
            if m and m.group("seq") in own:
                seqs.setdefault(m.group("seq"), []).append(int(m.group("num")))
        for seq, nums in sorted(seqs.items()):
            nums.sort()
            if len(nums) < 2:
                progress.tick("preview", len(nums))
                continue
            out = make_mp4(folder, seq, nums, args.fps, args.width)
            print("  %s: %d frames -> %s (%.1f MB)" % (seq, len(nums), out, os.path.getsize(out) / 1e6))
            progress.tick("preview", len(nums))
    return 0


if __name__ == "__main__":
    sys.exit(main())
