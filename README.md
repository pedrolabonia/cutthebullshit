# cutthebullshit

Turns photos of objects shot on a table into ready-to-comp cut-outs: each object on its own, plus the shadow it casts
and the light it bounces onto the table as separate layers. You can drop them over any background and they still look
like they were shot there. Built for stop-motion: a folder of frames becomes one animated sequence.

From a folder of camera photos it makes:

- **After Effects precomps**: one per object (one per stop-motion sequence), with controls for shadow strength, bounce
  light strength and matte grow / soften, plus a comp per scene with everything over your background.
- **PNG layers**: the object with alpha, a Multiply shadow pass and a Screen bounce-light pass, for any compositing app.
- **Layout PNGs**: object + shadow + light flattened into one transparent PNG, for quick layouts.
- **Previews**: JPEGs and an MP4 of each object over your background, and ProRes 4444 movies of the stop-motions.
- **A QC report** flagging frames where the cut-out probably missed part of the object.

It runs on a Mac and uses Photoshop (Select Subject and Content-Aware Fill) and After Effects; everything else is
done in Python with OpenCV.

## How it works

For every photo:

1. **prep**: develops the RAW once into a 16-bit PNG that keeps the camera's own look.
2. **cleanplate**: Photoshop finds the object (Select Subject → the object's matte) and paints it out
   (Content-Aware Fill → the empty table, the "clean plate").
3. **passes**: comparing the photo with the empty table gives the shadow (where the photo is darker) and the bounce
   light (where it is brighter).
4. **layers / preview / prores**: the PNG layers, layout PNGs, previews and movies.
5. **aecomps**: builds the After Effects project.

Nothing is ever processed twice: rerun the same folder and only what is missing gets done.

## Requirements

- **macOS** (Apple silicon or Intel).
- **Adobe Photoshop** and **Adobe After Effects**, installed the normal way from Creative Cloud. Tested with the 2026
  versions; the newest installed version of each is used.
- **Python 3.11 or newer.** If you don't have it, the install script can fetch one through
  [uv](https://docs.astral.sh/uv/).
- **Disk space:** about 60 MB per photo for the working files, on a fast drive if you can.

**No plugins, extensions or MCP servers are needed.** The tool controls Photoshop and After Effects with AppleScript,
which is built into macOS. It runs scripts inside the apps the same way *File > Scripts* would. It only needs the
setting and permissions in the steps below.

## Install

**1. Get the code and install it**

```bash
git clone https://github.com/<you>/cutthebullshit
cd cutthebullshit
scripts/install.sh
```

This creates a Python environment in `.venv` inside the repo, installs everything into it (OpenCV, rawpy, numpy and
an ffmpeg build, nothing system-wide) and runs the setup check. To pick the place or the Python:
`VENV=~/envs/ctb scripts/install.sh`, `PYTHON=/path/to/python3.12 scripts/install.sh`.

The command is then `.venv/bin/cutthebullshit`. To type just `cutthebullshit`, add the folder to your PATH:

```bash
echo 'export PATH="'$PWD'/.venv/bin:$PATH"' >> ~/.zshrc
```

**2. Let After Effects scripts write files**

In After Effects: *Settings* (*Preferences* in older versions) *> Scripting & Expressions >* turn on **Allow Scripts to
Write Files and Access Network**. The scripts hand their results back through a file, so without this the After
Effects step can't run. Photoshop needs no setting.

**3. Let your terminal control the apps (macOS Automation)**

The first time the tool talks to Photoshop or After Effects, macOS asks whether your terminal app (Terminal, iTerm,
VS Code…) may control it. Click **OK**. If you clicked *Don't Allow*, or no prompt appeared, turn it on in *System
Settings > Privacy & Security > Automation*: under your terminal app, enable Adobe Photoshop and Adobe After Effects.
The easiest way to get both prompts at once is the check in step 5.

Only for unattended runs (`cutthebullshit supervise`): also add your terminal app under *System Settings > Privacy &
Security > Accessibility*. It lets the supervisor click away the crash and recovery dialogs that would otherwise block
the apps overnight.

**4. Tell it where your files go** (optional for a first try)

Copy the example settings and edit the folders:

```bash
mkdir -p ~/.cutthebullshit
cp cutthebullshit.example.toml ~/.cutthebullshit/config.toml
```

Without a settings file, working files go to `~/cutthebullshit/work` and results to `~/cutthebullshit/output`. See
[Settings](#settings).

**5. Check everything**

Open Photoshop and After Effects, then:

```bash
cutthebullshit doctor --apps
```

It checks the settings, that the work and output folders are writable and have free space, the Python packages and
ffmpeg, that both apps are found, the After Effects scripting setting and Accessibility. It also asks both apps to run
a tiny script, which triggers the Automation prompts from step 3. It ends with `ready`, or with a list of what to fix.
`cutthebullshit doctor` without `--apps` does the same checks without touching the apps.

## Quick start

With Photoshop and After Effects open (no unsaved work in After Effects; see [After Effects](#after-effects)):

```bash
./run_example.sh ~/Shoot/teapot-anim
```

This cuts out every photo in `~/Shoot/teapot-anim` and puts the results in `~/Shoot/teapot-anim cutthebullshit`, next
to it. A few more ways to call it:

```bash
./run_example.sh ~/Shoot/teapot-anim ~/Desktop/teapot-cutout                # choose the output folder
./run_example.sh ~/Shoot/teapot-anim ~/Desktop/teapot-cutout --bg "#2a4d7a"  # preview over a blue background
./run_example.sh ~/Shoot ~/Desktop/cutouts --steps prep,cleanplate,passes,layers,preview,prores   # skip After Effects
```

[`run_example.sh`](run_example.sh) is a thin wrapper: it uses the example settings and puts the working files in
`<output>/_work`. The same with the command itself:

```bash
cutthebullshit --work ~/Desktop/cutouts/_work --output ~/Desktop/cutouts run ~/Shoot/teapot-anim
```

The folder name `teapot-anim` matters: a folder ending in `-anim` is a stop-motion (see below).

## Your photos

**Formats:** any camera RAW (`.arw .cr2 .cr3 .nef .dng .raf .orf .rw2` and the rest that LibRaw reads), or photos
already developed to TIFF, JPEG or PNG (used as they are).

**Stills and stop-motions:** a folder whose name ends in `-anim` or `_anim` is a **stop-motion**. Its photos become
one sequence, one photo per frame at 12 fps, and one precomp. **Every other photo is a still** with its own precomp,
even when the files are numbered in order. Versions inside a stop-motion folder (`teapot-anim/v1`, `teapot-anim/v2`)
are separate sequences.

**One folder or a whole shoot:** pass `run` a folder that holds photos, or any folder above several. From a folder
above, it picks up every folder named `RAW` (`photo_folder` in the settings) and skips anything inside a folder named
`CUT OUT`. A typical organized shoot:

```
Shoot/
  S01 Kitchen/            <- a scene: gets its own comp in After Effects
    teapot-anim/v1/RAW/   <- a stop-motion, one sequence
    spoon/RAW/            <- stills
  S02 Garden/
    ...
```

**Names:** sequences are named after the take. With the default pattern, `S01_teapot-anim_v1_0003_IMG1234.ARW` is
frame 3 of `S01_teapot-anim_v1`. Photos whose names don't fit (`IMG_1234.CR3`) are numbered in folder order, and a
stop-motion is then named after its folder. `_frames.csv`, next to the working files, lists which photo became which
frame.

## Settings

Settings live in a small TOML file. The first one found is used:

1. the file given with `cutthebullshit --config FILE`;
2. `cutthebullshit.toml` in the folder you run from;
3. `~/.cutthebullshit/config.toml`, your everyday settings.

Every setting is optional. [`cutthebullshit.example.toml`](cutthebullshit.example.toml) explains each one.

| setting | default | what it does |
|---|---|---|
| `work_dir` | `~/cutthebullshit/work` | working files: developed photos, mattes, passes. After Effects reads its footage from here, so keep it until you collect the project |
| `output_dir` | `~/cutthebullshit/output` | results: layers, layouts, previews, movies, the After Effects project |
| `background` | `none` | what previews and the After Effects scene comps sit on: an image, a colour (`"#rrggbb"`, `"white"`, `"0.5"`, `"200,190,170"`) or `"none"` (middle grey) |
| `photo_folder` | `"RAW"` | name of the folders holding photos, when you pass a folder above them (`""`: any folder with photos) |
| `photo_extensions` | all common RAWs + `.tif .jpg .png` | what counts as a photo |
| `exclude_folders` | `["cut out"]` | folders never processed (any capitalization) |
| `stop_motion_suffixes` | `["-anim", "_anim"]` | folder name endings that mean stop-motion |
| `sequence_pattern` | `^(?P<base>.+?_v\d+)_(?P<num>\d+)_` | regular expression: file name → sequence (`base`) and frame number (`num`) |
| `half_size` | `true` | develop RAWs at half resolution (4× faster, less noise; a 24 MP photo gives 6 MP) |
| `crop` | none | centre crop `[width, height]` in full-resolution pixels |
| `mirror_root` | none | the folder of your shoot whose sub-folders are recreated in the output (else the last 2–3 folders of each path) |
| `source_root` | none | your shoot folder, for `cutthebullshit status` |
| `protected` | `["~/Dropbox"]` | folders where the tool never deletes anything (it only adds and overwrites) |
| `photoshop_app`, `after_effects_app` | newest installed | e.g. `"Adobe After Effects 2025"` |

`--config FILE`, `--work DIR` and `--output DIR`, put before the command, override the settings for one call:
`cutthebullshit --output ~/Desktop/test run ~/Shoot/teapot-anim`.

## What you get

Every run gets a numbered `RUN NN` folder in both the work and the output folder; the folders below it mirror your
shoot.

```
<output>/RUN 01/
  LAYERS/S01 Kitchen/teapot-anim/v1/     teapot-anim_v1.0001.png             object, with alpha
                                         MULTIPLY_teapot-anim_v1.0001.png    shadow (Multiply blend)
                                         SCREEN_teapot-anim_v1.0001.png      bounce light (Screen blend)
                                         _qc_sheet.jpg, _qc.csv, _qc/        QC report (cutthebullshit qc)
  LAYOUTS/S01 Kitchen/teapot-anim/v1/    LAYOUT_teapot-anim_v1.0001.png      all three in one PNG, for layout
  PREVIEWS/                              PREVIEW_teapot-anim_v1.0001.jpg     over your background
                                         PREVIEW_teapot-anim_v1.mp4          stop-motions only
  PRORES/S01 Kitchen/teapot-anim/v1/     teapot-anim_v1.mov                  ProRes 4444 with alpha, stop-motions only
  recorte_precomps.aep                   the After Effects project
  _run.json                              what each run command did

<work>/RUN 01/S01 Kitchen/teapot-anim/v1/RAW/
  teapot-anim_v1_beauty.0001.png         the developed photo (16-bit)
  teapot-anim_v1_subject.0001.png        the object's matte (Photoshop Select Subject)
  teapot-anim_v1_shadow.0001.png         shadow pass
  teapot-anim_v1_bounce.0001.png         bounce-light pass
```

The After Effects project uses the files in the work folder as footage. To hand the project to someone, use
*File > Dependencies > Collect Files* in After Effects.

**Which run?** `run` keeps working in the newest run that already has these photos (else the latest run), so
rerunning a folder only fills in what is missing. `--new-run` starts a fresh `RUN NN` and processes everything again
there. `--run 3` picks one. `--force` redoes everything in the run used.

## The steps

`cutthebullshit run` does all of these in order. Each one is also a command of its own, and `--steps` picks a subset
(`--steps layers,preview`). Every step skips what is already done.

| step | what it does | time per photo* |
|---|---|---|
| `prep` | develops each RAW once: denoised, half size, 16-bit, matched to the camera's own look (the JPEG preview inside the RAW; one look per sequence, so stop-motions don't flicker). TIFF / JPEG / PNG are taken as they are | ~3 s |
| `cleanplate` | Photoshop: Select Subject → the matte; Content-Aware Fill over the object and its shadow → the empty table | ~13 s |
| `passes` | shadow and bounce light: the photo compared with the empty table. The empty table is deleted afterwards (~70 MB a photo) | ~3 s |
| `layers` | the PNG layers, layout PNGs and preview JPEGs | ~2 s |
| `preview` | an MP4 of every stop-motion, from the previews | — |
| `prores` | a ProRes 4444 movie with alpha of every stop-motion (see below) | — |
| `aecomps` | the After Effects project (see below) | seconds |

\* Measured on an 8-core Mac with 16 GB of RAM. `run` prints an estimate per step when it starts and learns from
every run.

Other commands:

| command | what it does |
|---|---|
| `cutthebullshit qc` | flags frames whose cut-out probably went wrong (see [QC](#qc)) |
| `cutthebullshit status --run 1` | per object of your shoot (`source_root` in the settings): which steps are done, what is missing |
| `cutthebullshit supervise` | `run` for long unattended jobs (see [below](#long-unattended-runs)) |
| `cutthebullshit doctor` | the setup check |
| `cutthebullshit <command> -h` | all options of a command |

**Useful options of `run`:**

- `--bg` sets what previews and scene comps sit on: an image (fit to height, centred), a colour (`"#2a4d7a"`,
  `white`, `grey`, `0.5`, `200,190,170`) or `none`. It overrides `background` in the settings. Changing it re-renders
  only the previews and rebuilds the scene comps.
- `--look linear` develops plainly instead of matching the camera's look; `--exposure`, `--midtones` and `--contrast`
  adjust it.
- `--denoise raw|strong|off` (default `raw`).
- `--grow 60` sets how far around the object Photoshop fills, in pixels.
- `--fps 12` is the stop-motion frame rate.

Photos are worked on in parallel: one per CPU core, minus two, limited by RAM so Photoshop and After Effects keep
6 GB. `--workers N` on `prep`, `passes`, `layers` or `qc`, run on their own, sets the number yourself.

## After Effects

The `aecomps` step builds `recorte_precomps.aep` in the run's output folder. It needs After Effects open with nothing
unsaved. If another project is open and saved, it is closed. If anything is unsaved, the step stops and asks you to
save or close it first. It never saves over your work.

**Each object's precomp** contains:

- a CONTROL null; everything is parented to it, so move it to move everything;
- OBJECT: the photo through the matte;
- MATTE: the Photoshop matte, plus two disabled FIX solids. Enable one and draw a mask on it to add to or remove from
  the object;
- SCREEN: the bounce light;
- MULTIPLY: the shadow.

**Its controls** are on the precomp's layer in the scene comp: twirl open *Essential Properties*. You don't need to
open the precomp, and each copy of it keeps its own values.

| control | default | |
|---|---|---|
| Shadow Opacity | 75 | strength of the shadow (`--shadow-opacity` to change the default) |
| Bounce Light Opacity | 100 | strength of the bounce light (`--bounce-opacity`) |
| Matte Grow / Shrink (px) | 0 | + grows, − shrinks the object's matte |
| Matte Softness (px) | 0 | softens the matte edge |

**Scene comps:** each scene folder (e.g. `S01 Kitchen`) gets a 24 fps comp with all its objects over the background.
The stop-motions hold each photo for 2 frames (12 fps).

**Using a precomp in your own comp:** put it over your background and turn on **Collapse Transformations** on its
layer. That is what lets the Multiply and Screen layers inside blend with your background. The scene comps already
have it on.

The project blends colours the way Photoshop does (16 bpc, sRGB, no linear blending). A master project set to linear
blending will make the shadow and light look different.

## Layout PNGs

`LAYOUT_*.png` flattens object, shadow (at 75%) and bounce light into one transparent PNG, for placing objects
quickly in Normal blend mode in any app. A single normal layer can only reproduce Multiply and Screen exactly over one
colour, so it is made exact over middle grey. Over other backgrounds the shadow and light keep their shape and tint
but come out slightly stronger or weaker: an average of 3–5 levels out of 255 in the shadow area. Use the precomp or
the three PNG layers for final work.

## QC

```bash
cutthebullshit qc               # every object in the newest run
cutthebullshit qc --run 2
cutthebullshit qc "<output>/RUN 02/LAYERS/S01 Kitchen/teapot-anim/v1"
```

It flags two kinds of problems:

- **missed**: part of the object fell outside the matte, such as a thin string, a corner or a small loose piece.
  Outside the object only shadow and light should be left, and those change the table's brightness, not its colour.
  A clearly coloured patch there with a hard edge is most likely object.
- **jump**: on one frame the matte is much bigger or smaller than on the frames either side, as when Select Subject
  lost or added a chunk. An object that steadily moves into frame or grows is fine.

Each object's `LAYERS` folder gets:

- `_qc_sheet.jpg`: every frame as a thumbnail, missed parts in magenta, flagged frames labelled in red;
- `_qc/…_missed1.jpg`: a close-up of each spot (photo | spot marked | cut-out);
- `_qc.csv`: one row per frame.

To fix a frame, use *Matte Grow* or the FIX solids in After Effects. Or redo its matte with
`cutthebullshit cleanplate --force --frames 3 <its work folder>` and run the passes and layers again.

QC is a pointer, not a verdict. A strongly coloured shadow or reflection is sometimes flagged, and a missed part the
same colour as the table is not seen.

## Long unattended runs

For a whole shoot left running overnight, `cutthebullshit supervise` runs one photo folder at a time and handles the
apps:

- A step that hangs (no output for 25 minutes) is stopped, its app is restarted and the folder is tried again.
- Before each folder it checks that Photoshop (and, for the last step, After Effects) still answers. If not, it closes
  their dialogs or restarts them.
- After 3 failed attempts a folder is marked failed. The supervisor still builds what it can for that folder and moves
  on.
- After Effects runs once at the end, over everything that got through. `--no-ae` stops before it.
- Every 5 minutes it prints how long is left for the folder and for the whole run.
- Progress is kept in `<output>/RUN NN/_supervise.json`, so running it again with the same run number resumes. A
  summary of failures goes to `_supervise_summary.txt`.

[`scripts/run_supervised.sh`](scripts/run_supervised.sh) restarts the supervisor if it ever exits with an error.
`caffeinate` keeps the Mac awake:

```bash
N=$(.venv/bin/python -c "from cutthebullshit.config import resolve_run; print(resolve_run('new'))")
PYTHON=.venv/bin/python nohup caffeinate -dims scripts/run_supervised.sh $N ~/Shoot > run$N.log 2>&1 &
tail -f run$N.log
```

Closing dialogs needs the Accessibility permission from [Install](#install) step 3.
`cutthebullshit supervise --selftest` restarts both apps once to check that this works.

## ProRes movies

Every stop-motion with more than one frame is exported as ProRes 4444 with alpha, 1920 wide and 24 fps, each photo
held for 2 frames. Change these with `--width` and `--hold`. `run` does this automatically. To run it on its own:

```bash
cutthebullshit prores --run 1
cutthebullshit prores --run 1 "S02 Garden" --passes object,multiply,screen --force
```

## Troubleshooting

| problem | fix |
|---|---|
| `Not authorized to send Apple events` (error -1743), or the apps never answer | Automation permission, [Install](#install) step 3 |
| After Effects step: "has unsaved changes" | save or close your project in After Effects and rerun; everything else is already done and skipped |
| After Effects step does nothing / no result file | turn on *Allow Scripts to Write Files and Access Network* ([Install](#install) step 2); close any open dialog in After Effects |
| Photoshop errors on every frame | close Photoshop's dialogs; check its scratch disk has free space (*Settings > Scratch Disks*) |
| photos fail to develop, or are 0 bytes | photos in Dropbox / iCloud may be online-only: make the folder available offline |
| `Adobe … not found in /Applications` | set `photoshop_app` / `after_effects_app` in the settings to the app's name |
| anything else | `cutthebullshit doctor --apps` |

## Notes

- **Never deletes in shared folders:** inside `~/Dropbox` and any `protected` folder, the tool only adds and
  overwrites files. It deletes only its own temporary files (Photoshop's TIFFs, empty-table images after the passes,
  old QC close-ups), and only in the work and output folders.
- What the tool learns (time per step) and the scripts it hands to After Effects are kept in `~/.cutthebullshit/`
  (`CUTTHEBULLSHIT_HOME` moves it).
- Runs made by older versions with EXR frames still work after `pip install -e ".[exr]"`.
- macOS only for now: the apps are driven with AppleScript. All of that lives in `src/cutthebullshit/apps/`, so
  Windows support means adding one backend module next to `_mac.py` (After Effects' `AfterFX.exe -r`, Photoshop's COM
  interface, `taskkill`, `pywinauto` for dialogs).

```
src/cutthebullshit/   cli.py (the command), pipeline.py (run), supervise.py, prep.py, cleanplate.py, passes.py,
                      layers.py, preview.py, prores.py, aecomps.py, qc.py, status.py, doctor.py,
                      config.py (settings), frames.py, eta.py, progress.py,
                      apps/ (driving Photoshop and After Effects: the only platform-specific code)
scripts/              install.sh, run_supervised.sh
run_example.sh        one folder of photos, start to finish
```
