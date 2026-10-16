"""cutthebullshit: stop-motion object cut-outs, from RAW photos to After Effects precomps.

    cutthebullshit <command> [options]        (cutthebullshit <command> -h for a command's options)

The whole run (most of the time this is all you need):
    run          develop -> clean plates -> passes -> layers -> previews -> After Effects -> publish, for RAW folders
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
    publish      copy a run to the publish folder and save its After Effects project there

    status       what is done / missing per object in a run (and in the publish folder)
"""

import importlib
import sys

COMMANDS = {
    "run": "pipeline", "supervise": "supervise",
    "prep": "prep", "cleanplate": "cleanplate", "passes": "passes", "layers": "layers", "preview": "preview",
    "aecomps": "aecomps", "prores": "prores", "publish": "publish",
    "status": "status",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
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
