"""What is left to do, for honest time estimates (cutthebullshit run per invocation, supervise.py for the whole run).

pending() checks a source RAW folder against a run on disk with the same rules the steps use to skip frames, so a
resumed / reused run is estimated by the frames that will really be processed, not by every frame it has.
Seconds per frame come from timings.json (learned by cutthebullshit run after every step).
"""

import os

from . import prep
from .config import list_frames, mirror_dir

FRAME_STEPS = ("prep", "cleanplate", "passes", "layers")      # steps that work (and skip) frame by frame


def source_frames(src):
    """[(photo, seq, num)] numbered the way prep numbers them."""
    photos = list_frames(src)
    return [(f,) + tuple(prep.sequence_name(f, i)) for i, f in enumerate(photos, 1)]


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return None


def pending(src, read_root, steps=FRAME_STEPS):
    """{step: frames that step would still process} for one source folder in a run, plus 'frames' and 'seqs'.
    A frame that still needs prep also needs everything after it."""
    from . import frames as fr
    from . import passes
    out = {k: 0 for k in steps}
    frames = source_frames(src)
    out["frames"], out["seqs"] = len(frames), len({s for _, s, _ in frames})
    if not frames or not steps:
        return out
    rd = mirror_dir(read_root, frames[0][0])
    for photo, seq, num in frames:
        n4 = "%04d" % num
        t_frame, t_src = _mtime(fr.frame_path(rd, seq, n4)), _mtime(photo)
        need = {"prep": t_frame is None or (t_src is not None and t_frame < t_src)}
        ins, outs = passes.frame_files(rd, seq, n4)
        need["cleanplate"] = need["prep"] or not ((os.path.exists(ins[1]) and os.path.exists(ins[2]))
                                                  or passes.done(rd, seq, n4))
        need["passes"] = need["cleanplate"] or not passes.up_to_date(ins, outs)
        if "layers" in steps:
            from . import layers
            li, lo = layers.frame_files(rd, seq, n4)
            need["layers"] = need["passes"] or not layers.up_to_date(li, lo)     # (a new --bg isn't counted)
        for k in steps:
            out[k] += bool(need.get(k))
    return out


def seconds(todo, spf):
    """Estimated seconds for a pending() result (frame steps only)."""
    return sum(todo.get(k, 0) * spf.get(k, 0) for k in FRAME_STEPS)
