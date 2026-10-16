"""Unattended run: keeps `cutthebullshit supervise` going until it has finished. If the supervisor itself stops with
an error it is started again (after --wait s, up to --max-restarts times) on the same run, so it resumes where it
stopped (its progress is in <output>/RUN NN/_supervise.json). Keeps the machine awake meanwhile. The same on macOS
and Windows.

    cutthebullshit unattended <photo folders...> [--new-run | --run N] [--log FILE] [other supervise options]

    cutthebullshit unattended ~/Shoot --new-run --log ~/Desktop/shoot.log
    cutthebullshit unattended D:\\Shoot --run 3 --no-ae

Leave the window open (macOS: or start it with nohup ... &). Everything it prints also goes to --log.
`cutthebullshit supervise -h` lists the other options.
"""

import argparse
import os
import subprocess
import sys
import time

from . import apps
from .config import resolve_run, run_name

PACKAGE_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Tee:
    def __init__(self, path):
        self.fh = open(path, "a", encoding="utf-8") if path else None

    def write(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()
        if self.fh:
            self.fh.write(text)
            self.fh.flush()

    def say(self, msg):
        self.write("[unattended %s] %s\n" % (time.strftime("%H:%M:%S"), msg))


def supervise(args, out):
    """Run the supervisor once, its output to the screen and the log; its exit code."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join([PACKAGE_PARENT] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    p = subprocess.Popen([sys.executable, "-u", "-m", "cutthebullshit", "supervise"] + args, env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    try:
        for line in p.stdout:
            out.write(line)
        return p.wait()
    except KeyboardInterrupt:
        try:
            p.wait(timeout=30)                  # Ctrl+C reached the supervisor too: let it stop its job
        except subprocess.TimeoutExpired:
            p.kill()
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", help="also append everything to this file")
    ap.add_argument("--new-run", action="store_true", help="start a new RUN (decided once: restarts continue it)")
    ap.add_argument("--run", help="the run to work in (default: picked like cutthebullshit run does)")
    ap.add_argument("--max-restarts", type=int, default=20, help="give up after this many errors (default %(default)s)")
    ap.add_argument("--wait", type=int, default=60, help="seconds before a restart (default %(default)s)")
    args, rest = ap.parse_known_args(argv)
    if args.run and args.new_run:
        ap.error("--run and --new-run don't go together")
    if not [a for a in rest if not a.startswith("-")] and "--selftest" not in rest:
        ap.error("give the photo folders to process")

    out = Tee(args.log)
    if args.new_run:
        args.run = str(resolve_run("new"))
        out.say("new run: %s" % run_name(int(args.run)))
    sup_args = rest + (["--run", args.run] if args.run else [])
    apps.keep_awake()

    errors = 0
    try:
        while True:
            rc = supervise(sup_args, out)
            if rc == 0:
                out.say("finished")
                return 0
            errors += 1
            if errors >= args.max_restarts:
                out.say("supervisor failed %d times, giving up" % errors)
                return 1
            out.say("supervisor exited with an error - restarting in %ds (%d/%d)" % (args.wait, errors, args.max_restarts))
            time.sleep(args.wait)
    except KeyboardInterrupt:
        out.say("stopped (Ctrl+C)")
        return 130


if __name__ == "__main__":
    sys.exit(main())
