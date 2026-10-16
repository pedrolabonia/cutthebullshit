#!/bin/bash
# Example: cut out every object in one folder of photos, start to finish.
#
#   ./run_example.sh "<photos folder>" [output folder] [more `cutthebullshit run` options]
#
#   ./run_example.sh ~/Shoot/teapot-anim
#   ./run_example.sh ~/Shoot/teapot-anim ~/Desktop/teapot-cutout --bg "#2a4d7a"
#   ./run_example.sh ~/Shoot "/Volumes/Fast/cutouts" --steps prep,cleanplate,passes,layers,preview
#
# <photos folder>: one folder of photos (RAW, TIFF or JPEG), or any folder above several of them.
# Output: "<photos folder> cutthebullshit" next to it unless given; the in-between files (developed frames, masks,
# passes: the After Effects footage) go in <output>/_work. Rerunning only does what is missing.
# Settings: cutthebullshit.example.toml next to this script (CONFIG=... to use another file).
# Open Photoshop and After Effects first (or leave After Effects out: --steps prep,cleanplate,passes,layers,preview,prores).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
if [ $# -lt 1 ] || [ ! -d "$1" ]; then
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
src="$(cd "$1" && pwd)"; shift
out="$src cutthebullshit"
if [ $# -ge 1 ] && [[ "$1" != -* ]]; then out="$1"; shift; fi
config="${CONFIG:-$here/cutthebullshit.example.toml}"

# the installed command: this repo's .venv (scripts/install.sh), else cutthebullshit on the PATH
ctb="$here/.venv/bin/cutthebullshit"
[ -x "$ctb" ] || ctb="$(command -v cutthebullshit || true)"
if [ -z "$ctb" ]; then
  echo "cutthebullshit isn't installed: run scripts/install.sh first" >&2
  exit 1
fi

mkdir -p "$out"
echo "photos:   $src"
echo "output:   $out"
echo "settings: $config"
exec "$ctb" --config "$config" --work "$out/_work" --output "$out" run "$src" "$@"
