"""cutthebullshit: stop-motion object cut-outs, from RAW photos to After Effects precomps.

    cutthebullshit [--config FILE] [--work DIR] [--output DIR] <command> [options]
                                              (cutthebullshit <command> -h for a command's options)

    --config FILE   the settings file to use (default: ./cutthebullshit.toml, then ~/.cutthebullshit/config.toml)
    --work DIR      where the in-between files go: developed frames, masks, passes (the After Effects footage)
    --output DIR    where the results go: LAYERS, LAYOUTS, PREVIEWS, PRORES, the After Effects project

The whole run (most of the time this is all you need):
    run          develop -> clean plates -> passes -> layers -> previews -> ProRes -> After Effects, for RAW folders
                 (or scene / object folders above them); skips everything already done
    supervise    the same, unattended over many folders: watchdog, app restarts, retries, whole-run ETA

One step at a time (what `run` calls, for a re-run or a fix):
    prep         RAWs -> 16-bit <seq>_beauty PNGs (camera look)
    cleanplate   Photoshop: Select Subject + Content-Aware Fill -> <seq>_subject masks, clean plates
    passes       shadow (Multiply) and bounce-light (Screen) passes from beauty vs clean plate
    layers       LAYERS / LAYOUTS / PREVIEWS per object (OpenCV)
    preview      a light .mp4 of every stop-motion from its PREVIEW_ frames
    aecomps      the After Effects precomps and scene comps
    prores       ProRes 4444 movies of the stop-motions

    status       what is done / missing per object in a run
    qc           flags frames whose cut-out matte looks wrong (missed object parts, jumps between frames)
    doctor       checks this machine is ready: settings, folders, packages, ffmpeg, Photoshop / After Effects
"""

import importlib
import os
import sys

COMMANDS = {
    "run": "pipeline", "supervise": "supervise",
    "prep": "prep", "cleanplate": "cleanplate", "passes": "passes", "layers": "layers", "preview": "preview",
    "aecomps": "aecomps", "prores": "prores",
    "status": "status", "qc": "qc", "doctor": "doctor",
}


GLOBAL = {"--config": "CUTTHEBULLSHIT_CONFIG", "--work": "CUTTHEBULLSHIT_WORK_DIR", "--output": "CUTTHEBULLSHIT_OUTPUT_DIR"}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # global options go in the environment before any module reads the settings (and reach the jobs `supervise` starts)
    while argv and argv[0].split("=")[0] in GLOBAL:
        opt = argv.pop(0)
        key, val = (opt.split("=", 1) + [None])[:2]
        if val is None:
            if not argv:
                print("cutthebullshit: %s needs a value" % key, file=sys.stderr)
                return 2
            val = argv.pop(0)
        os.environ[GLOBAL[key]] = os.path.abspath(os.path.expanduser(val))
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if argv[0] in ("-V", "--version"):
        from . import __version__
        print(__version__)
        return 0
    cmd = argv[0]
    if cmd not in COMMANDS:
        print("cutthebullshit: unknown command %r (one of: %s)" % (cmd, ", ".join(COMMANDS)), file=sys.stderr)
        return 2
    sys.argv[0] = "cutthebullshit %s" % cmd           # so each command's --help shows how it was called
    module = importlib.import_module("cutthebullshit." + COMMANDS[cmd])
    return module.main(argv[1:]) or 0


if __name__ == "__main__":
    sys.exit(main())
