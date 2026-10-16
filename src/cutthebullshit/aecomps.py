"""After Effects step: build one precomp per sequence (object, shadow and bounce light as blend layers).

For every sequence in the given work folders (<work>/RUN NN/<scene>/<object>/.../RAW) with, per frame,
    <seq>_beauty.####.png     the photo, 16-bit sRGB (prep.py; 8-bit from the EXR in older runs)
    <seq>_subject.####.png    Photoshop Select Subject mask, white = object (cleanplate.py)
    <seq>_shadow.####.png     shadow        -> Multiply (passes.py)
    <seq>_bounce.####.png     bounce light  -> Screen (passes.py)
it imports them into the run's After Effects project and makes a precomp <seq>, top to bottom:
    CONTROL null              moves / scales / rotates everything below together (all parented to it), and holds
                              the precomp's controls, published as Essential Properties so they can be set on the
                              precomp's layer in the scene comp (each instance its own values) without opening it:
                              Shadow Opacity (--shadow-opacity, default 75), Bounce Light Opacity (--bounce-opacity), Matte Grow / Shrink (px),
                              Matte Softness (px)
    OBJECT                    the beauty through the MATTE (luma track matte)
    MATTE                     precomp <seq> MATTE (hidden), with the grow / shrink (Minimax) and softness (blur)
                              driven by the controls; inside it the subject mask and two disabled FIX solids
                              (enable one and draw a mask to add to / remove from the object)
    SCREEN (bounce light)     Screen
    MULTIPLY (shadow)         Multiply
The shadow and bounce passes carry on under the object (passes.py), so growing or shrinking the matte never opens
a gap between the object and its shadow.
A stop-motion (several frames) is one precomp with every input imported as an image sequence at --fps; a still is
its own --still-seconds precomp. Filed under recorte/<scene>/<object>/... in the Project panel.

It also builds one comp per scene, <scene> (e.g. "S01 Kitchen") in the root of the Project panel, holding every object precomp of
that scene in the project at 24 fps (--scene-fps; the precomps stay at --fps) with Collapse Transformations on, over the background (bottom layer, an image fit to the
comp's height or a colour; --bg, default the settings' background); it is rebuilt on every run so it lists all objects.

Drop the precomp over any background and turn on its Collapse Transformations switch so the Screen and
Multiply layers blend with what is underneath. The layers are made to blend on display (sRGB) values, like
Photoshop: the script sets the project to 16 bpc, sRGB working space, no linearizing and
no "Blend Colors Using 1.0 Gamma" (--keep-color-settings to leave it alone). A master project in linear
blending will make the shadows and bounce light look different.

    cutthebullshit aecomps "<work>/RUN 01/S01 Kitchen/teapot-anim/v1/RAW" [--fps 12]
"""

import argparse
import glob
import json
import os
import re
import sys
import time

from . import frames
from . import progress
from . import apps
from .config import BG, SHADOW_OPACITY, OUTPUT_DIR, parse_bg, state_path, read_dir, shot_key, split_run

RESULT = state_path("ae_result.json")     # After Effects writes each job's result here
SEQ_RX = re.compile(r"^(?P<seq>.+)\.(?P<num>\d{4})\.exr$")
INPUTS = ("beauty", "subject", "shadow", "bounce")     # <seq>_<input>.####.png next to the frames in the work folder
DEFAULT_BG = BG
PROJECT_NAME = "recorte_precomps.aep"    # one After Effects project per run: <output>/RUN NN/recorte_precomps.aep

JSX = r"""
(function () {
    var job = %(job)s;
    var out = {comps: [], errors: []};
    function finish() { var f = new File(job.result); f.encoding = "UTF-8"; f.open("w"); f.write(out.toSource()); f.close(); }
    // work in this run's project: save+close another saved project, refuse an unsaved one that has work in it
    var target = new File(job.save);
    var cur = app.project ? app.project.file : null;
    if (!cur || cur.fsName != target.fsName) {
        if (!cur && app.project && app.project.numItems > 0) {
            out.errors.push("After Effects has an unsaved project with items open - save or close it, then rerun aecomps");
            finish(); return;
        }
        if (cur && app.project.dirty) {           // never save someone's open work behind their back
            out.errors.push("After Effects has unsaved changes in " + cur.fsName + " - save or close it, then rerun aecomps");
            finish(); return;
        }
        if (cur) app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
        if (target.exists) app.open(target); else app.newProject();
    }
    out.project = job.save;
    function folderPath(names) {
        var parent = app.project.rootFolder;
        for (var i = 0; i < names.length; i++) {
            var found = null;
            for (var j = 1; j <= parent.numItems; j++) {
                var it = parent.item(j);
                if (it instanceof FolderItem && it.name == names[i]) { found = it; break; }
            }
            if (!found) { found = app.project.items.addFolder(names[i]); found.parentFolder = parent; }
            parent = found;
        }
        return parent;
    }
    function removeNamed(folder, name) {
        for (var j = folder.numItems; j >= 1; j--) {
            if (folder.item(j).name == name) folder.item(j).remove();
        }
    }
    function importSeq(path, folder, straight, still) {
        var io = new ImportOptions(new File(path));
        io.sequence = !still;                 // a still photo is imported as an image, not a 1-frame sequence
        io.forceAlphabetical = false;
        var f = app.project.importFile(io);
        f.parentFolder = folder;
        if (!still) f.mainSource.conformFrameRate = job.fps;
        f.mainSource.alphaMode = straight ? AlphaMode.STRAIGHT : AlphaMode.IGNORE;
        return f;
    }
    // one white and one black solid shared by every MATTE's FIX layers (not two new solids per sequence)
    function fixSolid(comp, rgb, name, folder) {
        for (var j = 1; j <= folder.numItems; j++)
            if (folder.item(j).name == name && folder.item(j).mainSource instanceof SolidSource) return comp.layers.add(folder.item(j));
        var l = comp.layers.addSolid(rgb, name, comp.width, comp.height, 1, comp.duration);
        l.source.parentFolder = folder;
        return l;
    }
    if (job.display_blend) {
        // the layers are built to blend on display (sRGB) values, Photoshop-style
        app.project.bitsPerChannel = 16;
        app.project.linearBlending = false;
        try { app.project.workingSpace = "sRGB IEC61966-2.1"; } catch (e) {}
        try { app.project.linearizeWorkingSpace = false; } catch (e) {}
        out.display_blend = true;
    }
    app.beginUndoGroup("recorte precomps");
    try {
        var luzFolder = folderPath(["recorte", "_luz"]);
        for (var s = 0; s < job.seqs.length; s++) {
            var q = job.seqs[s];
            try {
                var folder = folderPath(q.folders);
                var footFolder = folderPath(q.folders.concat(["_footage"]));
                if (job.replace) {
                    removeNamed(folder, q.name);
                    removeNamed(folder, q.name + " MATTE");
                    for (var k = footFolder.numItems; k >= 1; k--) {
                        if (footFolder.item(k).name.indexOf(q.name) >= 0) footFolder.item(k).remove();
                    }
                }
                var still = q.frames == 1;
                var bea = importSeq(q.beauty, footFolder, false, still);
                var sub = importSeq(q.subject, footFolder, false, still);
                var shd = importSeq(q.shadow, footFolder, false, still);
                var bnc = importSeq(q.bounce, footFolder, false, still);
                var dur = still ? job.still_seconds : q.frames / job.fps;
                var W = bea.width, H = bea.height;

                // <seq> MATTE: white = object. The one place to fix a matte by hand.
                var m = app.project.items.addComp(q.name + " MATTE", W, H, 1, dur, job.fps);
                m.parentFolder = folder;
                m.comment = "recorte matte: white = object (Photoshop Select Subject). Grow / shrink / soften it from the " +
                            "precomp's Essential Properties; to fix a spot, enable a FIX solid here and draw a mask on it.";
                var lsub = m.layers.add(sub);
                lsub.name = "SUBJECT MASK (_subject.png)";
                var add = fixSolid(m, [1, 1, 1], "LUZ FIX white", luzFolder);
                add.name = "FIX + ADD TO OBJECT (enable, draw a mask)";
                add.enabled = false;
                add.label = 9;
                var rem = fixSolid(m, [0, 0, 0], "LUZ FIX black", luzFolder);
                rem.name = "FIX - REMOVE FROM OBJECT (enable, draw a mask)";
                rem.enabled = false;
                rem.label = 1;

                var comp = app.project.items.addComp(q.name, W, H, 1, dur, job.fps);
                comp.parentFolder = folder;
                comp.comment = "recorte: object / SCREEN / MULTIPLY (LUZ: beauty through the Select Subject matte). " +
                               "Turn on Collapse Transformations on this precomp's layer so Screen and Multiply blend " +
                               "with the background below.";
                var lm = comp.layers.add(shd); lm.name = "MULTIPLY (shadow)"; lm.blendingMode = BlendingMode.MULTIPLY;
                lm.property("Opacity").setValue(job.shadow_opacity);
                var ls = comp.layers.add(bnc); ls.name = "SCREEN (bounce light)"; ls.blendingMode = BlendingMode.SCREEN;
                ls.property("Opacity").setValue(job.bounce_opacity);
                var lmat = comp.layers.add(m); lmat.name = "MATTE (white = object)"; lmat.enabled = false;
                var lo = comp.layers.add(bea); lo.name = "OBJECT";
                lo.setTrackMatte(lmat, TrackMatteType.LUMA);
                // one null drives everything (move / scale / rotate them together) and holds the controls
                var ctl = comp.layers.addNull(comp.duration);
                ctl.name = "CONTROL " + q.name;
                ctl.source.name = "CONTROL " + q.name;
                ctl.source.parentFolder = footFolder;
                ctl.property("Anchor Point").setValue([ctl.source.width / 2, ctl.source.height / 2]);
                ctl.property("Position").setValue([comp.width / 2, comp.height / 2]);
                lo.parent = ctl; lmat.parent = ctl; ls.parent = ctl; lm.parent = ctl;
                // controls, published as Essential Properties: set them on this precomp's layer in any comp
                // (scene comp included) without opening it; each instance keeps its own values
                var ref = 'thisComp.layer("' + ctl.name + '").effect("';
                // (adding an effect invalidates earlier property references: everything is looked up again by name)
                var controls = [["Shadow Opacity", job.shadow_opacity], ["Bounce Light Opacity", job.bounce_opacity],
                                ["Matte Grow / Shrink (px)", 0], ["Matte Softness (px)", 0]];
                for (var c = 0; c < controls.length; c++) {
                    var e = ctl.property("ADBE Effect Parade").addProperty("ADBE Slider Control");
                    e.name = controls[c][0];
                    e.property(1).setValue(controls[c][1]);
                }
                lm.property("Opacity").expression = "clamp(" + ref + 'Shadow Opacity")("Slider"), 0, 100)';
                ls.property("Opacity").expression = "clamp(" + ref + 'Bounce Light Opacity")("Slider"), 0, 100)';
                var mfx = [["ADBE Minimax", "matte grow", 2, "Math.max(0, "],          // Maximum: white grows
                           ["ADBE Minimax", "matte shrink", 1, "Math.max(0, -"],       // Minimum: white shrinks
                           ["ADBE Gaussian Blur 2", "matte softness", 0, "Math.max(0, "]];
                for (var c = 0; c < mfx.length; c++) {
                    var e = lmat.property("ADBE Effect Parade").addProperty(mfx[c][0]);
                    e.name = mfx[c][1];
                }
                for (var c = 0; c < mfx.length; c++) {
                    var e = lmat.property("ADBE Effect Parade").property(mfx[c][1]);
                    var slider = mfx[c][1] == "matte softness" ? "Matte Softness (px)" : "Matte Grow / Shrink (px)";
                    if (mfx[c][0] == "ADBE Minimax") {
                        e.property("ADBE Minimax-0001").setValue(mfx[c][2]);
                        e.property("ADBE Minimax-0002").expression = mfx[c][3] + ref + slider + '")("Slider"))';
                    } else {
                        e.property("ADBE Gaussian Blur 2-0001").expression = mfx[c][3] + ref + slider + '")("Slider"))';
                        e.property("ADBE Gaussian Blur 2-0003").setValue(1);            // repeat edge pixels
                    }
                }
                comp.motionGraphicsTemplateName = q.name;
                for (var c = 0; c < controls.length; c++)
                    ctl.property("ADBE Effect Parade").property(controls[c][0]).property(1)
                       .addToMotionGraphicsTemplateAs(comp, controls[c][0]);
                var names = [];
                for (var j = 1; j <= comp.numLayers; j++)
                    names.push(comp.layer(j).name + (comp.layer(j).parent ? " <- " + comp.layer(j).parent.name : ""));
                out.comps.push({name: q.name, frames: q.frames, w: W, h: H, duration: comp.duration, still: still,
                                beauty_frames: still ? 1 : Math.round(bea.duration * job.fps), layers: names});
            } catch (e) {
                out.errors.push(q.name + ": " + e.toString());
            }
        }

        // one comp per scene (recorte/<scene>/<scene>) with every object precomp of that scene in the project,
        // Collapse Transformations on, so each precomp's Screen / Multiply blend with what is underneath
        out.scenes = [];
        var scenes = {};
        for (var s2 = 0; s2 < job.scenes.length; s2++) scenes[job.scenes[s2]] = true;
        for (var scene in scenes) {
            try {
                var sceneFolder = folderPath(["recorte", scene]);
                var pre = [];
                (function collect(fd) {
                    for (var j = 1; j <= fd.numItems; j++) {
                        var it = fd.item(j);
                        if (it instanceof FolderItem) collect(it);
                        else if (it instanceof CompItem && it.comment.indexOf("recorte: object") == 0) pre.push(it);
                    }
                })(sceneFolder);
                if (!pre.length) continue;
                pre.sort(function (x, y) { return x.name < y.name ? -1 : 1; });
                // replace this scene's comp, wherever it is (root bin now; older runs put it in recorte/<scene>)
                for (var j = sceneFolder.numItems; j >= 1; j--) {
                    var old = sceneFolder.item(j);
                    if (old instanceof CompItem && old.comment.indexOf("recorte scene") == 0) old.remove();
                }
                for (var j = app.project.rootFolder.numItems; j >= 1; j--) {
                    var old = app.project.rootFolder.item(j);
                    if (old instanceof CompItem && old.name == scene && old.comment.indexOf("recorte scene") == 0) old.remove();
                }
                var dur = 0, w = pre[0].width, h = pre[0].height;
                for (var j = 0; j < pre.length; j++) dur = Math.max(dur, pre[j].duration);
                var sc = app.project.items.addComp(scene, w, h, 1, dur, job.scene_fps);
                sc.parentFolder = app.project.rootFolder;
                sc.comment = "recorte scene: every object precomp of " + scene + ", Collapse Transformations on.";
                var names = [];
                for (var j = 0; j < pre.length; j++) {
                    var l = sc.layers.add(pre[j]);
                    l.collapseTransformation = true;
                    names.push(pre[j].name + (l.collapseTransformation ? " [collapsed]" : ""));
                }
                // background at the bottom: a colour solid, or an image fit to the comp's height, centred
                if (job.bg_color) {
                    var bs = sc.layers.addSolid(job.bg_color, "BG", sc.width, sc.height, 1, dur);
                    bs.moveToEnd();
                    names.push("background colour " + job.bg_color.join(","));
                } else if (job.bg) {
                    var bgItem = null, bgFolder = folderPath(["recorte", "_background"]);
                    for (var j = 1; j <= bgFolder.numItems; j++) {
                        if (bgFolder.item(j) instanceof FootageItem && bgFolder.item(j).mainSource.file &&
                            bgFolder.item(j).mainSource.file.fsName == new File(job.bg).fsName) bgItem = bgFolder.item(j);
                    }
                    if (!bgItem) {
                        bgItem = app.project.importFile(new ImportOptions(new File(job.bg)));
                        bgItem.parentFolder = bgFolder;
                    }
                    var bl = sc.layers.add(bgItem, dur);
                    bl.name = "BG " + bgItem.name;
                    var k = 100 * sc.height / bgItem.height;
                    bl.property("Scale").setValue([k, k]);
                    bl.property("Position").setValue([sc.width / 2, sc.height / 2]);
                    bl.moveToEnd();
                    names.push("background " + bgItem.name + " at " + Math.round(k * 10) / 10 + "%% (fit to height)");
                }
                out.scenes.push({scene: scene, objects: names, duration: dur});
            } catch (e) {
                out.errors.push("scene " + scene + ": " + e.toString());
            }
        }
    } finally {
        app.endUndoGroup();
    }
    if (!app.project.file) app.project.save(target); else app.project.save();
    out.saved = app.project.file.fsName;
    finish();
})();
"""


def find_sequences(folder):
    """Sequences in a work folder whose every frame has its beauty, subject, shadow and bounce PNG."""
    seqs = {}
    for seq, num in frames.frames(folder):
        seqs.setdefault(seq, []).append(int(num))
    out = []
    for name, nums in sorted(seqs.items()):
        nums.sort()
        frame = lambda kind, n: os.path.join(folder, "%s_%s.%04d.png" % (name, kind, n))
        missing = sorted({k for k in INPUTS for n in nums if not os.path.exists(frame(k, n))})
        if missing:
            print("  skip %s: no %s frames (run the cleanplate and passes steps)" % (name, ", ".join(missing)))
            continue
        if nums != list(range(nums[0], nums[-1] + 1)):
            print("  warning %s: frames are not continuous (%d-%d, %d files)" % (name, nums[0], nums[-1], len(nums)))
        rel = shot_key(folder)                              # the run has its own project: no RUN level inside
        out.append(dict({k: frame(k, nums[0]) for k in INPUTS}, name=name, frames=nums[-1] - nums[0] + 1,
                        folders=["recorte"] + ([] if rel in (".", "") else rel.split("/"))))
    return out


def run_jsx(job, work_dir, template=JSX, name="_aecomps.jsx"):
    jsx = os.path.join(work_dir, name)
    with open(jsx, "w", encoding="utf-8") as fh:
        fh.write(template % {"job": json.dumps(job)})
    if os.path.exists(RESULT):
        os.remove(RESULT)
    apps.run_ae_script(jsx, timeout=3600)    # many precomps take minutes
    for _ in range(1200):                    # the result file can land after the call returns
        if os.path.exists(RESULT):
            time.sleep(0.5)
            break
        time.sleep(0.5)
    if not os.path.exists(RESULT):
        raise RuntimeError("After Effects wrote no result (is it open? Preferences > Scripting & Expressions > "
                           "'Allow Scripts to Write Files and Access Network')")
    with open(RESULT, encoding="utf-8", errors="replace") as fh:     # After Effects writes it as UTF-8
        txt = fh.read()
    return txt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+", help="work folders (<work>/RUN NN/<scene>/<object>/.../RAW); "
                                               "an object's <output>/RUN NN/LAYERS folder works too")
    ap.add_argument("--fps", type=float, default=12, help="frame rate of the precomps (default %(default)s: one photo per frame)")
    ap.add_argument("--batch", type=int, default=40, help="sequences per After Effects call (default %(default)s)")
    ap.add_argument("--keep", action="store_true", help="don't replace precomps/footage that already exist")
    ap.add_argument("--scene-fps", type=float, default=24,
                    help="frame rate of the scene comp holding all precomps (default %(default)s; the precomps stay at --fps)")
    ap.add_argument("--still-seconds", type=float, default=10, help="length of the precomp of a still photo (default %(default)s)")
    ap.add_argument("--bg", default=DEFAULT_BG, help="background at the bottom of every scene comp: an image (fit to height), "
                                                     "a colour (#rrggbb, white, grey, 0.5, 200,190,170) or none")
    ap.add_argument("--shadow-opacity", type=float, default=SHADOW_OPACITY, help="MULTIPLY (shadow) layer opacity (default %(default)s)")
    ap.add_argument("--bounce-opacity", type=float, default=100, help="SCREEN (bounce light) layer opacity (default %(default)s)")
    ap.add_argument("--keep-color-settings", action="store_true",
                    help="don't switch the project to display-space blending (16 bpc, sRGB, no linearize, no 1.0 gamma)")
    ap.add_argument("--save", default=None,
                    help="After Effects project to add the precomps to (default: <output>/RUN NN/%s of the folders' run)" % PROJECT_NAME)
    args = ap.parse_args(argv)
    seqs = []
    # an object's <output>/RUN NN/LAYERS/... folder stands for its work folder
    args.folders = [read_dir(f) if os.sep + "LAYERS" + os.sep in os.path.abspath(f) + os.sep and
                    os.path.abspath(f).startswith(OUTPUT_DIR + os.sep) else f for f in args.folders]
    for f in args.folders:
        found = find_sequences(f)
        print("%s: %s" % (f, ", ".join("%s (%d frames)" % (s["name"], s["frames"]) for s in found) or "nothing"))
        seqs += found
    if not seqs:
        return 1
    os.makedirs(os.path.dirname(RESULT), exist_ok=True)
    if not args.save:
        args.save = os.path.join(OUTPUT_DIR, split_run(args.folders[0])[0], PROJECT_NAME)
    job = {"fps": args.fps, "replace": not args.keep, "save": args.save, "result": RESULT, "scene_fps": args.scene_fps,
           "display_blend": not args.keep_color_settings, "still_seconds": args.still_seconds,
           "shadow_opacity": args.shadow_opacity, "bounce_opacity": args.bounce_opacity,
           "bg": "", "bg_color": None}
    try:
        kind, val = parse_bg(args.bg)
    except ValueError as e:
        if args.bg != BG:
            ap.error(str(e))                          # asked for: say so
        print("  %s - scene comps without a background" % e)
        kind, val = "none", None
    if kind == "image":
        job["bg"] = val
    elif kind == "color":
        job["bg_color"] = [round(v, 4) for v in val]
    # in batches: After Effects saves the project after each one and every batch reports back (a single call over a
    # whole run would be silent for an hour); the scene comps are rebuilt once, with the last batch
    scenes = sorted({q["folders"][1] for q in seqs if len(q["folders"]) > 1})
    batches = [seqs[i:i + args.batch] for i in range(0, len(seqs), args.batch)]
    errors, t0 = 0, time.time()
    for b, batch in enumerate(batches, 1):
        last = b == len(batches)
        t = time.time()
        txt = run_jsx(dict(job, seqs=batch, scenes=scenes if last else []), os.path.dirname(RESULT))
        bad = [e for e in re.findall(r'errors:\[(.*?)\]', txt) if e]
        errors += sum(e.count('", "') + 1 for e in bad)
        print("[aecomps %d/%d] %d sequence(s) in %.0fs%s" % (b, len(batches), len(batch), time.time() - t,
                                                           ("  ERRORS: " + "; ".join(bad)) if bad else ""), flush=True)
        if last:
            print(txt)
        progress.tick("aecomps", len(batch))
    print("aecomps done in %.0fs: %d sequence(s) -> %s, %d error(s)" % (time.time() - t0, len(seqs), args.save, errors))
    # a sequence that fails is reported (and keeps whatever precomp it had); only a step where nothing worked fails
    return 1 if errors >= len(seqs) else 0


if __name__ == "__main__":
    sys.exit(main())
