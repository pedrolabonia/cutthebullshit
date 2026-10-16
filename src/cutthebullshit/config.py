"""Settings, shared paths and naming.

Settings come from a TOML file, the first one found of: $CUTTHEBULLSHIT_CONFIG, ./cutthebullshit.toml,
~/.cutthebullshit/config.toml (see cutthebullshit.example.toml). Without one, everything works in ~/cutthebullshit-work.
"""

import os
import re
import tomllib

STATE_DIR = os.path.expanduser(os.environ.get("CUTTHEBULLSHIT_HOME", "~/.cutthebullshit"))


def _settings():
    for p in (os.environ.get("CUTTHEBULLSHIT_CONFIG"), os.path.join(os.getcwd(), "cutthebullshit.toml"),
              os.path.join(STATE_DIR, "config.toml")):
        if p and os.path.isfile(os.path.expanduser(p)):
            with open(os.path.expanduser(p), "rb") as fh:
                return tomllib.load(fh), os.path.expanduser(p)
    return {}, None


SETTINGS, SETTINGS_FILE = _settings()


def setting_path(key, default=None):
    v = SETTINGS.get(key)
    return os.path.expanduser(v) if v else (os.path.expanduser(default) if default else None)


def state_path(name):
    """A file in the tool's own folder (~/.cutthebullshit): learned timings, the job scripts it hands to After Effects /
    the results After Effects writes back. Never inside the installed code."""
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, name)


# folders the tool never deletes anything in (only adds and overwrites): ~/Dropbox, plus `protected = [...]` in the settings
PROTECTED = [os.path.realpath(os.path.expanduser(p)) for p in ["~/Dropbox"] + list(SETTINGS.get("protected", []))]
DROPBOX = PROTECTED[0]


def in_dropbox(path):
    """True for a path inside a protected (shared / synced) folder."""
    real = os.path.realpath(path)
    return any(real.startswith(p + os.sep) for p in PROTECTED)


def remove_file(path):
    """Delete a working file. Never anything in a protected folder (Dropbox...): there the tool only adds and overwrites."""
    if in_dropbox(path):
        print("  NOT deleting %s (never delete in a shared / synced folder)" % path)
        return False
    os.remove(path)
    return True


# the After Effects look, shared by aecomps.py (precomps / scene comps) and layers.py (LAYOUT_ / PREVIEW_ renders)
BG = os.path.expanduser(SETTINGS.get("background", "none"))   # an image, a colour or "none" (see parse_bg)
SHADOW_OPACITY = 75     # % of the MULTIPLY (shadow) layer
BG_NAMES = {"white": 1.0, "black": 0.0, "grey": 0.5, "gray": 0.5, "mid-grey": 0.5, "middle-grey": 0.5}


def parse_bg(spec):
    """The background for PREVIEW_ renders and After Effects scene comps, from what the user typed:
        an image path                      -> ("image", path)        fit to the frame's height, centred
        #rrggbb, white / black / grey,
        a grey 0-1 (0.5) or 0-255 (128),
        r,g,b (0-1 or 0-255)               -> ("color", (r, g, b))   0-1 display values
        "" / none                          -> ("none", None)         no background (PREVIEW_ then uses middle grey)
    Raises ValueError for anything else, or an image that isn't there (or is a 0-byte Dropbox online-only file)."""
    s = (spec or "").strip()
    if not s or s.lower() == "none":
        return "none", None
    low = s.lower()
    if low in BG_NAMES:
        v = BG_NAMES[low]
        return "color", (v, v, v)
    if re.match(r"^#[0-9a-f]{6}$", low):
        return "color", tuple(int(low[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    if re.match(r"^[0-9.]+(\s*,\s*[0-9.]+){0,2}$", s):
        vals = [float(x) for x in s.split(",")]
        if len(vals) == 2:
            raise ValueError("background colour: give one grey value or r,g,b, not %r" % s)
        if any(v > 1 for v in vals):
            vals = [v / 255.0 for v in vals]
        vals = vals * 3 if len(vals) == 1 else vals
        if any(v < 0 or v > 1 for v in vals):
            raise ValueError("background colour out of range: %r" % s)
        return "color", tuple(vals)
    path = os.path.expanduser(s)
    if not os.path.exists(path):
        raise ValueError("background image not found: %s" % path)
    if os.path.getsize(path) == 0:
        raise ValueError("background image is a 0-byte Dropbox online-only file (make it available offline): %s" % path)
    return "image", os.path.abspath(path)


def bg_key(spec):
    """What identifies a background, to tell when PREVIEW_ renders were made over another one."""
    kind, val = parse_bg(spec)
    if kind == "image":
        return "image %s %d" % (val, int(os.path.getmtime(val)))
    return "%s %s" % (kind, ",".join("%.4f" % v for v in val) if val else "")

APPS_GB = 6.0   # RAM left for After Effects, Photoshop and macOS while frames are worked on


def default_workers(gb_per_worker):
    """Frames worked on at once: one per core, all but two cores, and no more than the RAM holds besides the apps
    (each worker peaks at gb_per_worker on a 4752x3168 frame; past that macOS compresses / swaps and every frame gets
    slower). 8 cores / 16 GB: prep (1.4 GB) -> 6, passes (2.8 GB) -> 3."""
    cores = os.cpu_count() or 2
    try:
        ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError):
        ram = 16.0
    return max(1, min(cores - 2, int((ram - APPS_GB) / gb_per_worker)))


def one_thread():
    """Pool initializer: each worker uses one core (OpenCV / OpenMP / BLAS would otherwise each start a thread per core,
    and n workers x n threads only fight over the cores)."""
    for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[k] = "1"
    try:
        import cv2
        cv2.setNumThreads(1)
    except ImportError:
        pass


TMP_READ = setting_path("tmp_read", "~/cutthebullshit-work/tmp_read")      # developed frames, masks, passes: RUN NN/<shot>
TMP_WRITE = setting_path("tmp_write", "~/cutthebullshit-work/tmp_write")   # RUN NN/{LAYERS, LAYOUTS, PREVIEWS}, AE project
PUBLISH_ROOT = setting_path("publish_root")    # where `publish` copies a run (RUN NN inside); none: publish is off
SOURCE_ROOT = setting_path("source_root")      # the organized photo tree `status` checks by default
MIRROR_DEPTH = 3
FRAME_EXT = (".arw", ".exr")


def frame_name(path):
    return os.path.splitext(os.path.basename(path))[0]


# the folder of the photo tree everything below which is recreated in the RUN folders (e.g. "OBJECTS");
# none: the last MIRROR_DEPTH folders of each RAW folder's path are used
MIRROR_ROOT = SETTINGS.get("mirror_root", "")


def mirror_parts(path, depth=MIRROR_DEPTH):
    """Parent folders of a file below the mirror root (e.g. S01 Kitchen/spoon/v3/RAW); else the last `depth`."""
    parts = os.path.normpath(os.path.dirname(path)).split(os.sep)
    if MIRROR_ROOT and MIRROR_ROOT in parts:
        return parts[len(parts) - parts[::-1].index(MIRROR_ROOT):]
    return parts[-depth:]


def mirror_dir(root, path, depth=MIRROR_DEPTH):
    return os.path.join(root, *mirror_parts(path, depth))


EXCLUDE_DIRS = ("cut out",)      # never process anything inside these folders (finished cut-outs), any case


def is_excluded(path):
    """True if any folder in the path is named CUT OUT (case and surrounding spaces ignored)."""
    return any(p.strip().lower() in EXCLUDE_DIRS for p in os.path.normpath(path).split(os.sep))


def list_frames(folder):
    """Frames in a source folder, sorted; skips AppleDouble (._) files and anything inside a CUT OUT folder."""
    if is_excluded(folder):
        print("  skip %s (inside a CUT OUT folder)" % folder)
        return []
    out = []
    for f in sorted(os.listdir(folder)):
        if f.startswith("._") or not f.lower().endswith(FRAME_EXT):
            continue
        out.append(os.path.join(folder, f))
    return out


RUN_RX = re.compile(r"^RUN (\d+)$")


def run_name(n):
    return "RUN %02d" % n


def runs():
    """Run numbers that exist in tmp_read or tmp_write."""
    out = set()
    for root in (TMP_READ, TMP_WRITE):
        if os.path.isdir(root):
            out |= {int(m.group(1)) for m in (RUN_RX.match(d) for d in os.listdir(root)) if m}
    return sorted(out)


def resolve_run(run="latest"):
    """'new' -> next run number (folders created), 'latest' -> highest existing, or a number. Returns the number."""
    existing = runs()
    if run == "new":
        n = (existing[-1] + 1) if existing else 1
        for root in (TMP_READ, TMP_WRITE):
            os.makedirs(os.path.join(root, run_name(n)), exist_ok=True)
        return n
    if run == "latest":
        if not existing:
            raise SystemExit("no RUN folders yet in %s - run the full workflow first" % TMP_WRITE)
        return existing[-1]
    n = int(run)
    if n not in existing:
        raise SystemExit("%s does not exist (have: %s)" % (run_name(n), ", ".join(map(run_name, existing)) or "none"))
    return n


def run_roots(n):
    """(tmp_read/RUN NN, tmp_write/RUN NN)"""
    return os.path.join(TMP_READ, run_name(n)), os.path.join(TMP_WRITE, run_name(n))


LAYERS, LAYOUTS, PREVIEWS = "LAYERS", "LAYOUTS", "PREVIEWS"   # tmp_write/RUN NN/<these>


def split_run(folder):
    """(run folder name, shot parts) for any tmp_read / tmp_write folder of a run.

    Shot parts are the object path below the mirror root without RUN, LAYERS/... and the trailing RAW,
    e.g. ['S02 Garden', 'watering-can'] or ['S01 Kitchen', 'spoon', 'v3']."""
    parts = os.path.normpath(os.path.abspath(folder)).split(os.sep)
    i = max(j for j, p in enumerate(parts) if RUN_RX.match(p))
    run, rest = parts[i], parts[i + 1:]
    if rest and rest[0] in (LAYERS, LAYOUTS, PREVIEWS):
        rest = rest[1:]
    if rest and rest[-1] == "RAW":
        rest = rest[:-1]
    return run, rest


def shot_key(folder, root=None):
    """'S01 Kitchen/spoon/v3': an object's path below the mirror root, the same in every run."""
    return "/".join(split_run(folder)[1])


def run_write_root(folder):
    return os.path.join(TMP_WRITE, split_run(folder)[0])


def layers_dir(folder):
    """tmp_write/RUN NN/LAYERS/<scene>/<object>/...: object, MULTIPLY_, SCREEN_ of one object."""
    run, shot = split_run(folder)
    return os.path.join(TMP_WRITE, run, LAYERS, *shot)


def layouts_dir(folder):
    """tmp_write/RUN NN/LAYOUTS/<scene>/<object>/...: the LAYOUT_ pngs of one object."""
    run, shot = split_run(folder)
    return os.path.join(TMP_WRITE, run, LAYOUTS, *shot)


def previews_dir(folder):
    """tmp_write/RUN NN/PREVIEWS: every PREVIEW_ jpg and mp4 of the run, flat."""
    return os.path.join(run_write_root(folder), PREVIEWS)


def read_dir(folder):
    """tmp_read folder of an object (keeps the source structure, with RAW)."""
    run, shot = split_run(folder)
    d = os.path.join(TMP_READ, run, *shot)
    return os.path.join(d, "RAW") if os.path.isdir(os.path.join(d, "RAW")) else d


def load_json(path):
    if os.path.exists(path):
        import json
        with open(path) as fh:
            return json.load(fh)
    return {}


def short_name(raw_folder):
    """A RAW folder as it is named in the runs, e.g. 'S01 Kitchen/teapot-anim/RAW' (for logs)."""
    return "/".join(mirror_parts(os.path.join(raw_folder, "_")))
