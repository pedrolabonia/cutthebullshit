"""The developed frames and clean plates in tmp_read, whatever format a run made them in.

Runs from 2026-10-16 on: prep develops each RAW once, straight to the file After Effects uses:
    <seq>_beauty.####.png     16-bit sRGB, the photo (also the input of cleanplate and passes)
    <seq>_plate.####.png      16-bit sRGB clean plate (cleanplate.py)
Runs made before the switch to PNG frames have linear half-float EXRs instead, <seq>.####.exr and <seq>_plate.####.exr, plus
an 8-bit <seq>_beauty.####.png made from the EXR for After Effects; they keep working as they are (nothing is
developed again). Where a frame has both, the EXR is the source.
"""

import glob
import os
import re

import cv2
import numpy as np

BEAUTY_RX = re.compile(r"^(?P<seq>.+)_beauty\.(?P<num>\d{4})\.png$")
EXR_RX = re.compile(r"^(?P<seq>.+)\.(?P<num>\d{4})\.exr$")


def beauty_path(folder, seq, num):
    return os.path.join(folder, "%s_beauty.%s.png" % (seq, num))


def legacy_exr(folder, seq, num):
    return os.path.join(folder, "%s.%s.exr" % (seq, num))


def frame_path(folder, seq, num):
    """The developed frame (EXR in an older run, else the 16-bit beauty PNG); the PNG path if neither exists yet."""
    exr = legacy_exr(folder, seq, num)
    return exr if os.path.exists(exr) else beauty_path(folder, seq, num)


def plate_path(folder, seq, num):
    """The clean plate (EXR in an older run, else 16-bit PNG); the PNG path if neither exists yet."""
    exr = os.path.join(folder, "%s_plate.%s.exr" % (seq, num))
    return exr if os.path.exists(exr) else os.path.join(folder, "%s_plate.%s.png" % (seq, num))


def subject_path(folder, seq, num):
    return os.path.join(folder, "%s_subject.%s.png" % (seq, num))


def frames(folder):
    """[(seq, num as '0001')] of every developed frame in a tmp_read folder, sorted."""
    found = set()
    for p in glob.glob(os.path.join(folder, "*.exr")) + glob.glob(os.path.join(folder, "*_beauty.*.png")):
        name = os.path.basename(p)
        if name.startswith("._"):
            continue
        m = EXR_RX.match(name) or BEAUTY_RX.match(name)
        if m and not m.group("seq").endswith("_plate") and ".tmp." not in name:
            found.add((m.group("seq"), m.group("num")))
    return sorted(found)


def is_legacy(folder, seq, num):
    return os.path.exists(legacy_exr(folder, seq, num))


def to_srgb(lin):
    x = np.clip(lin, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def from_srgb(s):
    return np.where(s <= 0.04045, s / 12.92, ((s + 0.055) / 1.055) ** 2.4)


def read_exr(path):
    import OpenEXR
    with OpenEXR.File(path) as f:
        return np.asarray(f.channels()["RGB"].pixels, np.float32)


def read_png(path):
    """RGB float 0-1 of an 8- or 16-bit PNG."""
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise IOError("can't read %s" % path)
    scale = 65535.0 if img.dtype == np.uint16 else 255.0
    return cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2RGB).astype(np.float32) / scale


def read_srgb(path):
    """Display-space (sRGB) RGB float 0-1 of a frame or plate, EXR or PNG."""
    return to_srgb(read_exr(path)).astype(np.float32) if path.endswith(".exr") else read_png(path)


def read_linear(path):
    """Linear RGB float of a frame or plate, EXR or PNG."""
    return read_exr(path) if path.endswith(".exr") else from_srgb(read_png(path)).astype(np.float32)


def srgb16(srgb):
    """0-1 float sRGB -> uint16 RGB."""
    return np.clip(np.round(srgb * 65535.0), 0, 65535).astype(np.uint16)


def write_png16(path, rgb16):
    """16-bit RGB PNG (uint16 RGB array), written to .part first so a half-written file never looks done."""
    tmp = path[:-4] + ".part.png"
    if not cv2.imwrite(tmp, cv2.cvtColor(rgb16, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_PNG_COMPRESSION, 1]):
        raise IOError("could not write %s" % tmp)
    os.replace(tmp, path)
