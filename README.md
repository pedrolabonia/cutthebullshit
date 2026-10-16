# cutthebullshit

Stop-motion object cut-outs, from RAW photos to After Effects precomps. Per frame: the photo (`_beauty`) through
Photoshop's Select Subject mask (`_subject`) for the object, plus a Multiply shadow and a Screen bounce-light pass
worked out against a per-frame Photoshop clean plate. The per-object deliverables (LAYERS, LAYOUTS, PREVIEWS, the
ProRes and preview movies) are made with OpenCV from the same passes.

## Install

macOS, Python 3.11+, Adobe Photoshop and After Effects (Preferences > Scripting & Expressions > *Allow Scripts to Write
Files and Access Network*).

```bash
git clone https://github.com/<you>/cutthebullshit && cd cutthebullshit
python3 -m venv .venv && .venv/bin/pip install -e .          # or: uv pip install -e .
.venv/bin/cutthebullshit --help
```

## Settings

Paths and the look of a job live in a small TOML file, not in the code: copy `cutthebullshit.example.toml` to
`~/.cutthebullshit/config.toml` (or `./cutthebullshit.toml` in the folder you run from, or point `CUTTHEBULLSHIT_CONFIG`
at it) and set what you need:

| setting | default | what |
|---|---|---|
| `tmp_read`, `tmp_write` | `~/cutthebullshit-work/…` | where the work happens, one `RUN NN` folder per run (~60 MB per photo) |
| `publish_root` | none (no publishing) | where `cutthebullshit publish` copies a run |
| `background` | `none` | PREVIEW / AE scene-comp background: an image, a colour or `none` (`--bg` overrides it) |
| `source_root` | none | the photo tree `cutthebullshit status` checks |
| `mirror_root` | none | folder name below which the photo tree is mirrored into the runs (else the last 3 folders) |
| `protected` | `~/Dropbox` | folders the tool never deletes anything in |

`pip install -e ".[exr]"` adds OpenEXR, needed only to keep using runs made with EXR frames (before 2026-10-16).
The tool keeps what it learns and the scripts it hands to After Effects in `~/.cutthebullshit/`
(`CUTTHEBULLSHIT_HOME` to move it).

```
src/cutthebullshit/   cli.py (the cutthebullshit command), pipeline.py (run), supervise.py, prep.py, cleanplate.py,
                      passes.py, layers.py, preview.py, aecomps.py, prores.py, publish.py, status.py,
                      config.py (paths, look, workers), frames.py, eta.py, progress.py
scripts/              run_supervised.sh (keeps `cutthebullshit supervise` going)
```

## Run everything

Open first: **Photoshop** and **After Effects**. Then:

```bash
cutthebullshit run "<photos>/<scene>/<object>/RAW" [more folders]
```

Folders named `CUT OUT` (any case, e.g. `cut out`) and everything inside them are never processed.
You can also pass a scene or object folder (`<photos>/S01 Kitchen`): every `RAW` folder below it is processed.
**Stop-motion** = a parent folder ends in `-anim` / `_anim` (one sequence per folder or version, e.g.
`on-our-way-anim/v1`) and becomes **one precomp** with its frames imported as image sequences at 12 fps;
**every other photo is a still** — its own 10 s precomp (`spoon/v3` → `S01_spoon_v3_0001`, `_0002`, `_0003`),
even when the files are numbered in order.

**Nothing already done is processed twice.** Without `--run` / `--new-run`, `cutthebullshit run` works in the newest RUN that
already has every source developed (else the latest RUN), and every step skips frames whose outputs are up to date,
so rerunning a folder only does what is missing. `--new-run` starts a new `RUN NN` (everything processed again
there); `--force` redoes frames in the run used. What each invocation did is logged in `tmp_write/RUN NN/_run.json`:

```
tmp_read/RUN NN/<scene>/<object>/.../RAW/   <seq>_beauty.####.png (16-bit, the photo, developed once), <seq>_subject /
                                            _shadow / _bounce.####.png: the After Effects footage; _frames.csv,
                                            _look_<seq>.json (prep). The 16-bit <seq>_plate.####.png only lives until
                                            passes has used it (then the passes count as done for cleanplate)
                                            (runs before 2026-10-16: <seq>.####.exr + <seq>_plate.####.exr instead, with an
                                            8-bit _beauty made from the EXR; they keep working, nothing is redone)
tmp_write/RUN NN/
  LAYERS/<scene>/<object>/.../              <seq>, MULTIPLY_<seq>, SCREEN_<seq> (.####.png), _preview_bg.txt
  LAYOUTS/<scene>/<object>/.../             LAYOUT_<seq>.####.png per object
  PREVIEWS/                                 PREVIEW_<seq>.####.jpg + PREVIEW_<seq>.mp4 of every object, flat
  recorte_precomps.aep, _run.json
```

| step | command | what | output |
|---|---|---|---|
| 1 | `cutthebullshit prep` | RAW → denoised half-res (4752×3168) 16-bit sRGB PNG with the camera's own look (matched to the JPEG embedded in each .arw). Developed once: this file is the photo for cleanplate, passes and After Effects | `tmp_read/RUN NN/<shot>/RAW/<seq>_beauty.####.png` |
| 2 | `cutthebullshit cleanplate` | Photoshop: Select Subject + shadow/glow area, Content-Aware Fill. Photoshop's TIFFs (and the `_photoshop` folder) are deleted once the plate is written (`--keep-debug` keeps them) | `<seq>_plate.####.png` (16-bit, until passes), `<seq>_subject.####.png` |
| 3 | `cutthebullshit passes` | 8-bit sRGB PNGs next to the frames: `_shadow` (beauty ÷ clean plate where darker → Multiply), `_bounce` (the light that makes it brighter than the plate → Screen). Display-space maths, like AE blends; both passes neutral outside the clean-plate selection and carried on under the object, so no seam at its edge. ~2.5 s a frame (3 at once on this Mac). Deletes each 16-bit plate once its passes are written; changing the passes later = `cutthebullshit cleanplate --force` on those frames first. (`--steps beauty` still works: the step's old name) | `tmp_read/…/RAW/<seq>_{shadow,bounce}.####.png` |
| 4 | `cutthebullshit layers` | OpenCV: per frame the object (`<seq>`, beauty + subject as straight alpha), `MULTIPLY_` (shadow), `SCREEN_` (bounce) in `LAYERS/<shot>`; `LAYOUT_` in `LAYOUTS/<shot>` (one RGBA for quick layout over any background in Normal mode, shadow at 75%; exact over middle grey); `PREVIEW_` half-size JPEG over the background (`--bg`, default: `background` in the settings) = the AE scene comp (measured 0.9–1.6/255, JPEG). ~2–3 s a frame, 5 at once | `tmp_write/RUN NN/{LAYERS,LAYOUTS}/<shot>/`, `PREVIEWS/` |
| 5 | `cutthebullshit preview` | light H.264 movie of every stop-motion, from the PREVIEW_ frames | `PREVIEWS/PREVIEW_<seq>.mp4` |
| 6 | `cutthebullshit aecomps` | After Effects precomp per sequence, the object / shadow / bounce layers (see After Effects below) + one comp per scene with all its object precomps, Collapse Transformations on | `tmp_write/RUN NN/recorte_precomps.aep` |
| 7 | `cutthebullshit publish` | Brings the stop-motion ProRes movies up to date (`cutthebullshit prores`, only what changed; `--no-prores` skips), then copies the run's `LAYERS`, `LAYOUTS`, `PREVIEWS`, `PRORES` to `02. Runs/01 PUBLISH/RUN NN/` (new and changed files only; **nothing in Dropbox is ever deleted**, files only there stay), saves the project there as `recorte_precomps.aep` relinked to those Dropbox copies (no collect; the bg keeps its Dropbox link) + a report and a `<scene>.txt` per scene comp, then closes it and opens an empty project so the next run starts clean | `01 PUBLISH/RUN NN/` |

At the start `cutthebullshit run` prints a time estimate per step and the finish time (seconds per frame learned from
earlier runs in `timings.json`), and after each step the time taken and the remaining time.
`cutthebullshit status --run NN` lists, per object, which stages are done and what is still missing (also in Dropbox).

**Background (`--bg`):** what the PREVIEW renders and the AE scene comps sit on, the same for both. On `cutthebullshit run` / `supervise` (or `layers` / `aecomps`): an image (fit to the frame's height, centred), a colour (`#rrggbb`, `white`, `grey`, `0.5`, `128`, `200,190,170`) or `none` (PREVIEW over middle grey, no bg in AE). Default: `background` in the settings (none: middle grey). A mistyped path stops the run at once; a different background re-renders the previews (each object's `LAYERS/<shot>/_preview_bg.txt` keeps the one used) and rebuilds the scene comps over it.

    cutthebullshit run <sources> --bg "#2a4d7a"
    cutthebullshit run <sources> --steps layers,preview,aecomps --bg ~/Desktop/other_bg.png

**Frames in parallel:** prep and passes work on one frame per core, all cores but two, as many as fit in RAM next to After Effects and Photoshop (`config.default_workers`: 6 GB kept for the apps; prep peaks at ~1.4 GB a frame, passes at ~2.8 GB, so 6 and 3 on this 8-core / 16 GB Mac). More would only make macOS swap. `--workers N` on `cutthebullshit prep` / `passes` / `layers` overrides it.

Every step can run on its own (`--steps ... --run NN`) and resumes where it stopped: prep skips frames already
developed (a PNG, or an older run's EXR), cleanplate skips frames with a plate and subject mask, passes skips frames
whose passes are newer than the frame, plate and mask, layers skips frames whose five outputs are newer than their
inputs (and made over the same `--bg`); aecomps just rebuilds (seconds, no image processing). `--force` redoes them.
The beauty PNGs and subject masks stay in `tmp_read`: publish doesn't copy them to Dropbox (its report lists
them as links kept outside the run) — Collect Files on the project gathers them.
`--look camera` (default) matches each take to the camera's own JPEG embedded in the .arw (tone curve, white
balance, contrast; one curve per take, saved as `_look_<seq>.json`, so stop-motions don't flicker). `--look linear`
= plain development + `--exposure` (1.4) / `--midtones` (1.15) / `--contrast` (0.25), which can also be added on
top of the camera look. `--force` redoes prep and plates in that run; `--denoise raw|strong|off` (raw = wavelet denoise in the RAW
development, default); `--grow` clean-plate selection margin (60 px); `--fps` (12 = one photo per frame).

Sequences are named after the take: `S01_teapot-anim_v1_0003_0001_014_01_X1_0033.arw` is frame 3 of
`S01_teapot-anim_v1`; `_frames.csv` next to the frames maps frames back to photos.


## Layout previs

`LAYOUT_<seq>.####.png` (`cutthebullshit layers`) = object + shadow + bounce light in one RGBA PNG on transparency, for quick
layout over any background in Normal mode (shadow at 75%, its warm tint kept). A single Normal layer can only
reproduce Multiply / Screen exactly over one colour, so it is built for neutral middle grey (`--layout-grey 0.5`):
exact there (measured 0.1/255), and over other backgrounds the shadow and light keep their shape and tint but drift
in strength (measured mean 3-5/255 in the shadow / light area over cream, near-white, dark grey and blue; the bounce
glow reads a little strong on very light backgrounds, where Screen barely lifts them). Use the precomp (or the three
passes) for the final comp.

## After Effects

Each precomp `<seq>` holds, top to bottom: a CONTROL null, OBJECT (the beauty through the MATTE, luma track matte),
MATTE (precomp `<seq> MATTE`: the subject mask, plus two disabled FIX solids — enable one and draw a mask to add to /
remove from the object), SCREEN (bounce light) and MULTIPLY (shadow), all parented to the null — move/scale/rotate
the null to move everything together. Its controls are **Essential Properties**, so they are on the precomp's layer
in the scene comp (twirl open *Essential Properties*; each instance keeps its own values) — no need to open it:

| control | default | |
|---|---|---|
| Shadow Opacity | 75 | the MULTIPLY layer; `cutthebullshit aecomps --shadow-opacity` |
| Bounce Light Opacity | 100 | the SCREEN layer; `--bounce-opacity` |
| Matte Grow / Shrink (px) | 0 | grows (+) or shrinks (−) the object's matte (Minimax) |
| Matte Softness (px) | 0 | blurs the matte edge |
 Each scene (e.g. `S01 Kitchen`) also gets a comp (in the root of the Project panel)
with all its object precomps at 24 fps (`--scene-fps`; the precomps stay at 12 so each photo holds 2 frames), Collapse Transformations already on, over `the background.png` as the bottom layer
(fit to the comp's height; `--bg` to change). Put a precomp over the background and turn
on **Collapse Transformations** on its layer so Screen/Multiply blend with the background. The layers blend on
display (sRGB) values like Photoshop: the script sets its project to 16 bpc, sRGB, no
linearizing, no "Blend Colors Using 1.0 Gamma" — a master project with linear blending will change how the
shadow and light look.

## Notes

- Work data lives in `tmp_read` / `tmp_write` (settings); only `publish` writes to the publish folder.
- **Never delete in Dropbox**: the pipeline only adds and overwrites files there (`config.remove_file` refuses any path
  under ~/Dropbox). Other people may put files in the publish folders too.
- Environment: `~/dev/recorte-env` (rawpy, OpenEXR for older EXR runs, OpenCV, numpy, imageio-ffmpeg).

## Unattended runs (cutthebullshit supervise)

For long runs left alone: `scripts/run_supervised.sh` keeps `cutthebullshit supervise` going, which runs
`cutthebullshit run` one RAW folder at a time (prep, cleanplate, passes, layers, preview), then After Effects + publish
over everything that got through.

```
N=$(python3 -c "from cutthebullshit.config import resolve_run; print(resolve_run('new'))")
nohup caffeinate -dims scripts/run_supervised.sh $N "<photo tree or scene folders>" > ~/cutthebullshit-work/run$N.log 2>&1 &
```
(`PYTHON=.venv/bin/python` if cutthebullshit isn't installed in the `python3` on the PATH.)

- hang (no output for 25 min, or Photoshop failing the same frame twice): the job is killed, that step's app restarted, folder retried
- crash: Photoshop must answer before every attempt (After Effects before the AE steps); if not, their dialogs are
  closed (`dismiss_dialogs.applescript`) or the app is killed and relaunched
- 3 attempts per folder, then it builds the passes, layers and previews of what has clean plates, marks the folder
  partial / failed and moves on
- progress in `tmp_write/RUN NN/_supervise.json` (rerun with the same run number resumes); summary of anything that
  failed in `tmp_write/RUN NN/_supervise_summary.txt`
- publish is skipped (only After Effects is built) if the Dropbox disk would end up with less than 3 GB free
- nothing is done twice: the run is picked like `cutthebullshit run` does, folders already in an older run are continued
  there, every step skips what is on disk, and After Effects / publish run once each at the end (a failed publish
  is retried on its own); `--no-ae` stops before After Effects, `--no-publish` before Dropbox
- ETA from what is really left on disk per step (done frames don't count), with the speeds in `timings.json`
  corrected by how long this session's folders took: at every folder start and every 5 min
  `ETA  folder 12/40: ~6m left  |  whole run: ~3h10m left, finish ~Fri 18:05`, also in
  `tmp_write/RUN NN/_supervise_eta.json`
- closing the apps' crash / recovery dialogs needs **Accessibility** for Claude (System Settings > Privacy & Security >
  Accessibility); `cutthebullshit supervise --selftest` restarts Photoshop and After Effects once to check the whole thing

## ProRes export of the stop-motions (cutthebullshit prores)

Every stop-motion of a run (folders named -anim / _anim, more than one frame) as ProRes 4444 with alpha, 1920 wide
(height follows the frames: 3:2 -> 1920x1280, nothing cropped; `--width` to change), 24 fps "on 2s" (each PNG held 2
frames). Straight alpha, Rec.709 tags, edges scaled premultiplied (no fringes).

    cutthebullshit prores --run 1                       # -> tmp_write/RUN 01/PRORES/<scene>/<object>/<seq>.mov
    cutthebullshit prores --run 1 "S02 Garden" --passes object,multiply,screen --hold 2 --force

Up-to-date movies are skipped. `cutthebullshit publish` runs it before uploading, so `PRORES` in Dropbox always matches the
published frames. Uses the ffmpeg from the `imageio-ffmpeg` package in recorte-env (the x86 ffmpeg in
~/bin doesn't run on this Mac).
