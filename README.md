# cutthebullshit

Stop-motion object cut-outs, from camera photos to After Effects precomps. Per frame: the photo (`_beauty`) through
Photoshop's Select Subject mask (`_subject`) for the object, plus a Multiply shadow and a Screen bounce-light pass
worked out against a per-frame Photoshop clean plate. The per-object deliverables (LAYERS, LAYOUTS, PREVIEWS, the
ProRes and preview movies) are made with OpenCV from the same passes, and a QC pass flags frames whose matte looks
wrong.

## Quick start

macOS, Python 3.11+, Adobe Photoshop and After Effects (Settings > Scripting & Expressions > *Allow Scripts to Write
Files and Access Network*).

```bash
git clone https://github.com/<you>/cutthebullshit && cd cutthebullshit
scripts/install.sh
```

`scripts/install.sh` makes a `.venv` in the repo (with [uv](https://docs.astral.sh/uv/) if you have it, else
`python -m venv` + pip; `VENV=...` / `PYTHON=...` to choose), installs the package into it and runs
`cutthebullshit doctor`, which checks the machine: settings, work / output folders (writable, free space), the Python
packages and ffmpeg, Photoshop and After Effects (found, scripting allowed), Accessibility, and how many frames
each step works on at once. `cutthebullshit doctor --apps` also makes both apps answer a script.

Then open Photoshop and After Effects and cut out a folder of photos:

```bash
./run_example.sh ~/Shoot/teapot-anim                       # -> "~/Shoot/teapot-anim cutthebullshit"
./run_example.sh ~/Shoot/teapot-anim ~/Desktop/teapot-cutout --bg "#2a4d7a"
./run_example.sh ~/Shoot ~/Desktop/cutouts --steps prep,cleanplate,passes,layers,preview   # no After Effects
```

[`run_example.sh`](run_example.sh) takes one folder of photos (RAW, TIFF or JPEG; or any folder above several of
them) and an output folder (default: next to the photos), and runs
`cutthebullshit --config cutthebullshit.example.toml --work <output>/_work --output <output> run <photos>`.
Anything after the output folder goes to `cutthebullshit run`. Rerunning it only does what is missing.

## Settings

The paths and conventions of a job live in a small TOML file, not in the code. Start from
[`cutthebullshit.example.toml`](cutthebullshit.example.toml) (every setting explained there) and put it at
`~/.cutthebullshit/config.toml` (used everywhere), or `./cutthebullshit.toml` in the folder you run from, or pass it
with `cutthebullshit --config FILE`. Every setting is optional.

| setting | default | what |
|---|---|---|
| `work_dir` | `~/cutthebullshit/work` | the in-between files: developed frames, masks, passes (the After Effects footage) |
| `output_dir` | `~/cutthebullshit/output` | the results: LAYERS, LAYOUTS, PREVIEWS, PRORES, the After Effects project |
| `background` | `none` | PREVIEW / AE scene-comp background: an image, a colour or `none` (`--bg` overrides it) |
| `photo_folder` | `RAW` | the folders holding an object's photos, when you pass a folder above them (`""`: any folder with photos) |
| `photo_extensions` | every common RAW + `.tif .jpg .png` | what counts as a photo |
| `exclude_folders` | `["cut out"]` | folders never processed (any case) |
| `stop_motion_suffixes` | `["-anim", "_anim"]` | a folder ending in one of these is a stop-motion |
| `sequence_pattern` | `^(?P<base>.+?_v\d+)_(?P<num>\d+)_` | file name → sequence (`base`) and frame (`num`) |
| `half_size` | `true` | develop RAWs at half size (4× faster, cleaner) |
| `crop` | none | centre crop `[width, height]` in full-size pixels |
| `mirror_root` | none | folder name below which the photo tree is recreated in the runs (else the last 3 folders) |
| `source_root` | none | the photo tree `cutthebullshit status` checks |
| `protected` | `~/Dropbox` | folders the tool never deletes anything in (only adds and overwrites) |
| `photoshop_app`, `after_effects_app` | newest installed | e.g. `"Adobe After Effects 2025"` |

Global options, before the command, override the settings for one call:

```
cutthebullshit [--config FILE] [--work DIR] [--output DIR] <command> [options]
```

The tool keeps what it learns (`timings.json`) and the scripts it hands to After Effects in `~/.cutthebullshit/`
(`CUTTHEBULLSHIT_HOME` to move it). `pip install -e ".[exr]"` adds OpenEXR, needed only for runs made with EXR frames
by older versions.

```
src/cutthebullshit/   cli.py (the cutthebullshit command), pipeline.py (run), supervise.py, prep.py, cleanplate.py,
                      passes.py, layers.py, preview.py, aecomps.py, prores.py, qc.py, status.py, doctor.py,
                      config.py (settings, paths, workers, apps), frames.py, eta.py, progress.py
scripts/              install.sh, run_supervised.sh (keeps `cutthebullshit supervise` going)
run_example.sh        one folder of photos, start to finish
```

## Your photos

Any camera RAW LibRaw reads (`.arw .cr2 .cr3 .nef .dng .raf .orf .rw2 …`), or photos already developed to TIFF / JPEG
/ PNG (used as they are: no RAW development, no camera look). Pass `cutthebullshit run` a folder of photos, or any
folder above several (a scene, a whole shoot): every folder named `photo_folder` (`RAW`) below it is processed.
Folders named `CUT OUT` (any case) and everything inside them are never processed.

**Stop-motion** = a parent folder ends in `-anim` / `_anim` (one sequence per folder or version, e.g.
`teapot-anim/v1`): it becomes **one precomp** with its frames imported as an image sequence at 12 fps.
**Every other photo is a still**: its own 10 s precomp (`spoon/v3` → `S01_spoon_v3_0001`, `_0002`, `_0003`),
even when the files are numbered in order.

Sequences are named after the take: with the default `sequence_pattern`,
`S01_teapot-anim_v1_0003_0001_014_01_X1_0033.arw` is frame 3 of `S01_teapot-anim_v1`. Photos whose names don't match
are numbered in folder order; a stop-motion is then named after its folder (`teapot-anim/v1` → `teapot-anim_v1`).
`_frames.csv` next to the developed frames maps frames back to photos.

## Run everything

Open first: **Photoshop** and **After Effects**. Then:

```bash
cutthebullshit run "<photos>/<scene>/<object>/RAW" [more folders]
```

**Nothing already done is processed twice.** Without `--run` / `--new-run`, `cutthebullshit run` works in the newest
RUN that already has every source developed (else the latest RUN), and every step skips frames whose outputs are up
to date, so rerunning a folder only does what is missing. `--new-run` starts a new `RUN NN` (everything processed again
there); `--force` redoes frames in the run used. What each invocation did is logged in `<output>/RUN NN/_run.json`:

```
<work>/RUN NN/<scene>/<object>/.../RAW/     <seq>_beauty.####.png (16-bit, the photo, developed once), <seq>_subject /
                                            _shadow / _bounce.####.png: the After Effects footage; _frames.csv,
                                            _look_<seq>.json (prep). The 16-bit <seq>_plate.####.png only lives until
                                            passes has used it (then the passes count as done for cleanplate)
<output>/RUN NN/
  LAYERS/<scene>/<object>/.../              <seq>, MULTIPLY_<seq>, SCREEN_<seq> (.####.png), _preview_bg.txt,
                                            _qc.csv, _qc_sheet.jpg, _qc/ (cutthebullshit qc)
  LAYOUTS/<scene>/<object>/.../             LAYOUT_<seq>.####.png per object
  PREVIEWS/                                 PREVIEW_<seq>.####.jpg + PREVIEW_<seq>.mp4 of every object, flat
  PRORES/<scene>/<object>/.../              <seq>.mov of every stop-motion
  recorte_precomps.aep, _run.json
```

| step | command | what | output |
|---|---|---|---|
| 1 | `cutthebullshit prep` | RAW → denoised half-size 16-bit sRGB PNG with the camera's own look (matched to the JPEG preview embedded in the RAW; plain development if it has none). TIFF / JPEG / PNG are taken as they are. Developed once: this file is the photo for cleanplate, passes and After Effects | `<work>/RUN NN/<shot>/RAW/<seq>_beauty.####.png` |
| 2 | `cutthebullshit cleanplate` | Photoshop: Select Subject + shadow / glow area, Content-Aware Fill. Photoshop's TIFFs are deleted once the plate is written (`--keep-debug` keeps them) | `<seq>_plate.####.png` (16-bit, until passes), `<seq>_subject.####.png` |
| 3 | `cutthebullshit passes` | 8-bit sRGB PNGs next to the frames: `_shadow` (beauty ÷ clean plate where darker → Multiply), `_bounce` (the light that makes it brighter than the plate → Screen). Display-space maths, like AE blends; both passes neutral outside the clean-plate selection and carried on under the object, so no seam at its edge. Deletes each 16-bit plate once its passes are written; changing the passes later = `cutthebullshit cleanplate --force` on those frames first | `<work>/…/RAW/<seq>_{shadow,bounce}.####.png` |
| 4 | `cutthebullshit layers` | per frame the object (`<seq>`, beauty + subject as straight alpha), `MULTIPLY_` (shadow), `SCREEN_` (bounce) in `LAYERS/<shot>`; `LAYOUT_` in `LAYOUTS/<shot>` (see Layout previs); `PREVIEW_` half-size JPEG over the background = the AE scene comp | `<output>/RUN NN/{LAYERS,LAYOUTS}/<shot>/`, `PREVIEWS/` |
| 5 | `cutthebullshit preview` | a light H.264 movie of every stop-motion, from the PREVIEW_ frames | `PREVIEWS/PREVIEW_<seq>.mp4` |
| 6 | `cutthebullshit prores` | ProRes 4444 with alpha of every stop-motion (see below) | `PRORES/<shot>/<seq>.mov` |
| 7 | `cutthebullshit aecomps` | After Effects precomp per sequence (see After Effects) + one comp per scene with all its object precomps, Collapse Transformations on | `<output>/RUN NN/recorte_precomps.aep` |

Not part of `run`, any time after it:

| command | what |
|---|---|
| `cutthebullshit qc` | flags frames whose matte looks wrong (see QC) |
| `cutthebullshit status --run NN` | per object, which stages are done and what is still missing |
| `cutthebullshit doctor` | is this machine ready (see Quick start) |

At the start `cutthebullshit run` prints a time estimate per step and the finish time (seconds per frame learned from
earlier runs), and after each step the time taken and the remaining time.

**Background (`--bg`):** what the PREVIEW renders and the AE scene comps sit on, the same for both: an image (fit to
the frame's height, centred), a colour (`#rrggbb`, `white`, `grey`, `0.5`, `128`, `200,190,170`) or `none` (PREVIEW
over middle grey, no background in AE). Default: `background` in the settings. A mistyped path stops the run at once;
a different background re-renders the previews (each object's `LAYERS/<shot>/_preview_bg.txt` keeps the one used) and
rebuilds the scene comps over it.

    cutthebullshit run <sources> --bg "#2a4d7a"
    cutthebullshit run <sources> --steps layers,preview,aecomps --bg ~/Desktop/other_bg.png

**Frames in parallel:** prep, passes and layers work on one frame per core, all cores but two, as many as fit in RAM
next to After Effects and Photoshop (6 GB kept for the apps; prep peaks at ~1.4 GB a frame, passes at ~2.8 GB, layers
at ~2 GB; on 8 cores / 16 GB that is 6, 3 and 5 at once). More would only make macOS swap. `--workers N` overrides it.

Every step can run on its own (`--steps ... --run NN`) and resumes where it stopped: prep skips frames already
developed, cleanplate skips frames with a plate and subject mask, passes skips frames whose passes are newer than the
frame, plate and mask, layers skips frames whose outputs are newer than their inputs (and made over the same `--bg`);
aecomps just rebuilds (seconds, no image processing). `--force` redoes them.
`--look camera` (default) matches each take to the camera's own JPEG embedded in the RAW (tone curve, white
balance, contrast; one curve per take, saved as `_look_<seq>.json`, so stop-motions don't flicker). `--look linear`
= plain development + `--exposure` (1.4) / `--midtones` (1.15) / `--contrast` (0.25), which can also be added on top
of the camera look. `--denoise raw|strong|off` (raw = wavelet denoise in the RAW development, default); `--grow`
clean-plate selection margin (60 px); `--fps` (12 = one photo per frame).

## Layout previs

`LAYOUT_<seq>.####.png` (`cutthebullshit layers`) = object + shadow + bounce light in one RGBA PNG on transparency, for
quick layout over any background in Normal mode (shadow at 75%, its tint kept). A single Normal layer can only
reproduce Multiply / Screen exactly over one colour, so it is built for neutral middle grey (`--layout-grey 0.5`):
exact there (measured 0.1/255), and over other backgrounds the shadow and light keep their shape and tint but drift
in strength (measured mean 3-5/255 in the shadow / light area over cream, near-white, dark grey and blue). Use the
precomp (or the three passes) for the final comp.

## After Effects

Each precomp `<seq>` holds, top to bottom: a CONTROL null, OBJECT (the beauty through the MATTE, luma track matte),
MATTE (precomp `<seq> MATTE`: the subject mask, plus two disabled FIX solids — enable one and draw a mask to add to /
remove from the object), SCREEN (bounce light) and MULTIPLY (shadow), all parented to the null — move / scale / rotate
the null to move everything together. Its controls are **Essential Properties**, so they are on the precomp's layer
in the scene comp (twirl open *Essential Properties*; each instance keeps its own values) — no need to open it:

| control | default | |
|---|---|---|
| Shadow Opacity | 75 | the MULTIPLY layer; `cutthebullshit aecomps --shadow-opacity` |
| Bounce Light Opacity | 100 | the SCREEN layer; `--bounce-opacity` |
| Matte Grow / Shrink (px) | 0 | grows (+) or shrinks (−) the object's matte (Minimax) |
| Matte Softness (px) | 0 | blurs the matte edge |

Each scene (e.g. `S01 Kitchen`) also gets a comp (in the root of the Project panel) with all its object precomps at
24 fps (`--scene-fps`; the precomps stay at 12 so each photo holds 2 frames), Collapse Transformations already on,
over the background as the bottom layer. Put a precomp over a background and turn on **Collapse Transformations** on
its layer so Screen / Multiply blend with it. The layers blend on display (sRGB) values like Photoshop: the script
sets its project to 16 bpc, sRGB, no linearizing, no "Blend Colors Using 1.0 Gamma" — a master project with linear
blending will change how the shadow and light look.

aecomps never saves over work you haven't saved: if After Effects has an unsaved project open it stops and asks you to
save or close it first. The project references the footage in the work folder; *File > Dependencies > Collect Files*
gathers it.

## QC

`cutthebullshit qc` (every object of the newest run; `--run NN`, or object folders) reads each frame's photo, subject
mask and passes and flags

- **missed**: part of the object left outside the matte. Outside the mask the passes should hold only shadow and
  light, which change the table's brightness, not its colour; a strongly coloured change there with a hard edge is
  object (a corner, a string, a thin part Select Subject dropped).
- **jump**: the matte's area spikes against the frames on both sides (Select Subject lost or added a chunk on one
  frame); an object that moves in or grows steadily is fine.

In the object's `LAYERS` folder: `_qc.csv` (one row per frame), `_qc_sheet.jpg` (PREVIEW thumbnails, missed parts in
magenta, flagged frames in red) and `_qc/<seq>.####_missedN.jpg` (photo | marked | cut-out over a checkerboard for
every flagged spot). Fix a frame with the matte controls in After Effects, or redo its mask with
`cutthebullshit cleanplate --force --frames N <work folder>` and then passes / layers again. QC only reports; a
coloured shadow or reflection can be flagged now and then, and a missed part with the table's own colour isn't seen.

## Unattended runs (cutthebullshit supervise)

For long runs left alone: `scripts/run_supervised.sh` keeps `cutthebullshit supervise` going, which runs
`cutthebullshit run` one photo folder at a time (prep, cleanplate, passes, layers, preview, prores), then After Effects
once over everything that got through.

```bash
N=$(.venv/bin/python -c "from cutthebullshit.config import resolve_run; print(resolve_run('new'))")
PYTHON=.venv/bin/python nohup caffeinate -dims scripts/run_supervised.sh $N "<photo tree or scene folders>" > run$N.log 2>&1 &
```

- hang (no output for 25 min, or Photoshop failing the same frame twice): the job is killed, that step's app
  restarted, the folder retried
- crash: Photoshop must answer before every attempt (After Effects before the AE step); if not, their dialogs are
  closed (`dismiss_dialogs.applescript`) or the app is killed and relaunched
- 3 attempts per folder, then it builds the passes, layers and previews of what has clean plates, marks the folder
  partial / failed and moves on
- progress in `<output>/RUN NN/_supervise.json` (rerun with the same run number resumes); a summary of anything that
  failed in `<output>/RUN NN/_supervise_summary.txt`
- nothing is done twice: the run is picked like `cutthebullshit run` does, folders already in an older run are
  continued there, every step skips what is on disk, and After Effects runs once at the end; `--no-ae` stops before it
- ETA from what is really left on disk per step, with the learned speeds corrected by how long this session's folders
  took: at every folder start and every 5 min
  `ETA  folder 12/40: ~6m left  |  whole run: ~3h10m left, finish ~Fri 18:05`, also in `<output>/RUN NN/_supervise_eta.json`
- closing the apps' crash / recovery dialogs needs **Accessibility** for the app you run it from (System Settings >
  Privacy & Security > Accessibility); `cutthebullshit supervise --selftest` restarts Photoshop and After Effects once
  to check the whole thing

## ProRes export of the stop-motions (cutthebullshit prores)

Every stop-motion of a run (more than one frame) as ProRes 4444 with alpha, 1920 wide (height follows the frames:
3:2 → 1920×1280, nothing cropped; `--width` to change), 24 fps "on 2s" (each PNG held 2 frames). Straight alpha,
Rec.709 tags, edges scaled premultiplied (no fringes). Part of `run`; on its own:

    cutthebullshit prores --run 1                       # -> <output>/RUN 01/PRORES/<scene>/<object>/<seq>.mov
    cutthebullshit prores --run 1 "S02 Garden" --passes object,multiply,screen --hold 2 --force

Up-to-date movies are skipped. Uses the ffmpeg that comes with the `imageio-ffmpeg` package.

## Notes

- **Never deletes in protected folders**: in `~/Dropbox` (and `protected` in the settings) the tool only adds and
  overwrites files (`config.remove_file` refuses any path there). Its own working files (plates, Photoshop TIFFs, old
  QC zooms) are only ever deleted in the work / output folders.
- Photoshop and After Effects are driven with AppleScript, so the pipeline runs on macOS only for now.
