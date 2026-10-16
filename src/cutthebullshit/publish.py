"""Publish step: save a run's After Effects project in Dropbox, linked to the run's folders there.

1. brings the stop-motion ProRes movies up to date (cutthebullshit prores: only sequences whose frames changed; --no-prores
   to skip), then copies the run's LAYERS, LAYOUTS, PREVIEWS and PRORES to 01 PUBLISH/RUN NN/ (resumable; new and changed
   files are copied over, nothing there is deleted)
   Nothing in Dropbox is ever deleted: files only there (someone else's, or an older render's) stay as they are.
2. saves tmp_write/RUN NN/recorte_precomps.aep as 01 PUBLISH/RUN NN/recorte_precomps.aep with every footage item
   that pointed into tmp_write/RUN NN/ relinked to the same file under 01 PUBLISH/RUN NN/ (footage elsewhere, like
   the bg in Dropbox, keeps its link), plus recorte_precompsReport.txt. The relink rewrites the paths in an .aepx
   copy instead of using After Effects' Replace Footage, so it works when the Dropbox copies are online-only
   (After Effects can't read those and refuses to relink to them; the project loads them once they're offline)
3. writes 01 PUBLISH/RUN NN/<scene>.txt for every scene comp (its settings and layers)
4. closes the project and leaves an empty new project open, so the next run starts clean.
The project in tmp_write is not changed (it keeps pointing at tmp_write).

    cutthebullshit publish [--run NN] [--keep-open]
"""

import argparse
import os
import shutil
import sys
import time
from xml.sax.saxutils import escape

from . import progress
from .aecomps import PROJECT_NAME, RESULT, run_jsx
from .config import LAYERS, LAYOUTS, PREVIEWS, resolve_run, run_name, run_roots, remove_file

PRORES = "PRORES"                 # tmp_write/RUN NN/PRORES from cutthebullshit prores

from .config import DROPBOX, PUBLISH_ROOT

# open the run's project (save + close another saved project, refuse an unsaved one with items) and list footage
LIST_JSX = r"""
(function () {
    var job = %(job)s, sep = String.fromCharCode(31), lines = [];
    function finish() { var f = new File(job.result); f.encoding = "UTF-8"; f.open("w"); f.write(lines.join("\n")); f.close(); }
    var target = new File(job.project);
    if (!target.exists) { lines.push("ERROR\tno project " + job.project); finish(); return; }
    var cur = app.project ? app.project.file : null;
    if (!cur || cur.fsName != target.fsName) {
        if (!cur && app.project && app.project.numItems > 0) {
            lines.push("ERROR\tAfter Effects has an unsaved project with items open - save or close it, then rerun publish");
            finish(); return;
        }
        if (cur && app.project.dirty) {           // never save someone's open work behind their back
            lines.push("ERROR\tAfter Effects has unsaved changes in " + cur.fsName + " - save or close it, then rerun publish");
            finish(); return;
        }
        if (cur) app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
        app.open(target);
    } else {
        app.project.save();
    }
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (!(it instanceof FootageItem) || !(it.mainSource instanceof FileSource) || !it.mainSource.file) continue;
        var folders = [];
        for (var p = it.parentFolder; p && p != app.project.rootFolder; p = p.parentFolder) folders.unshift(p.name);
        lines.push(["ITEM", it.id, it.mainSource.isStill ? 1 : 0, it.footageMissing ? 1 : 0,
                    folders.join(sep), it.mainSource.file.fsName].join("\t"));
    }
    // scene comps (one per scene, all object precomps over the bg) for the per-scene .txt
    for (var i = 1; i <= app.project.numItems; i++) {
        var c = app.project.item(i);
        if (!(c instanceof CompItem) || c.comment.indexOf("recorte scene") != 0) continue;
        lines.push(["SCENE", c.name, c.width, c.height, c.frameRate, c.duration].join("\t"));
        for (var j = 1; j <= c.numLayers; j++) lines.push(["LAYER", c.name, j, c.layer(j).name].join("\t"));
    }
    // an XML copy whose footage paths Python rewrites (the run's project itself stays as it is, already saved)
    app.project.save(new File(job.aepx));
    app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
    app.newProject();
    finish();
})();
"""

# open the rewritten .aepx and save it as the publish .aep. After Effects never has to read the footage, so this works
# with Dropbox online-only files (which it can't read, and so won't relink to with replace()); dialogs are suppressed
# (it would warn about every file it can't read).
OPEN_JSX = r"""
(function () {
    var job = %(job)s, lines = [];
    function finish() { var f = new File(job.result); f.encoding = "UTF-8"; f.open("w"); f.write(lines.join("\n")); f.close(); }
    app.beginSuppressDialogs();
    try {
        app.open(new File(job.aepx));
        for (var i = 1; i <= app.project.numItems; i++) {
            var it = app.project.item(i);
            if (it instanceof FootageItem && it.mainSource instanceof FileSource && it.mainSource.file)
                lines.push(["LINK", it.footageMissing ? 1 : 0, it.mainSource.file.fsName].join("\t"));
        }
        app.project.save(new File(job.save_as));
        lines.push("SAVED\t" + app.project.file.fsName);
        if (job.close) {
            app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);
            app.newProject();
            lines.push("CLOSED");
        }
    } catch (e) {
        lines.push("ERROR\t" + e.toString());
    }
    app.endSuppressDialogs(false);
    finish();
})();
"""


def up_to_date(src, dst):
    try:
        a, b = os.stat(src), os.stat(dst)
    except FileNotFoundError:
        return False
    if b.st_mtime < a.st_mtime - 1:
        return False
    if a.st_size == b.st_size:
        return True
    # a Dropbox online-only file reads as 0 bytes / 0 blocks but keeps its date: it's there (in the cloud).
    # (copies are written to .part and renamed, so a half-copied file never looks like this)
    return b.st_size == 0 and b.st_blocks == 0 and a.st_size > 0


def mirror(src_root, dst_root):
    """Copy src_root's tree into dst_root (resumable): new and changed files are copied (overwriting the old copy),
    nothing in dst_root is ever deleted, also files src_root no longer has (they stay, e.g. other people's files or
    an older render's extra frames). Skips the ._ / .DS_Store files macOS leaves on the exFAT drive.
    Returns (files, copied, extra = files only in dst_root, bytes)."""
    want, n, copied, size = set(), 0, 0, 0
    for d, dirs, files in os.walk(src_root):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in files:
            if f.startswith("._") or f == ".DS_Store":
                continue
            src = os.path.join(d, f)
            dst = os.path.join(dst_root, os.path.relpath(src, src_root))
            want.add(dst)
            n += 1
            size += os.path.getsize(src)
            if not up_to_date(src, dst):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst + ".part")
                os.replace(dst + ".part", dst)
                copied += 1
    extra = 0
    if os.path.isdir(dst_root):
        for d, _, files in os.walk(dst_root):
            extra += sum(1 for f in files if os.path.join(d, f) not in want and f != ".DS_Store" and not f.startswith("._"))
    return n, copied, extra, size


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="latest", help="run number to publish (default: the latest run)")
    ap.add_argument("--root", default=PUBLISH_ROOT, help="publish folder (default %(default)s)")
    ap.add_argument("--no-prores", action="store_true",
                    help="don't export / upload the stop-motion ProRes movies (PRORES folder)")
    ap.add_argument("--keep-open", action="store_true", help="leave the published project open in After Effects")
    args = ap.parse_args(argv)

    if not args.root:
        ap.error("no publish folder: set publish_root in the settings (see cutthebullshit.example.toml) or pass --root")
    run_no = resolve_run(args.run)
    _, write_root = run_roots(run_no)
    project = os.path.join(write_root, PROJECT_NAME)
    run_dir = os.path.join(args.root, run_name(run_no))
    save_as = os.path.join(run_dir, PROJECT_NAME)
    work = os.path.dirname(RESULT)                   # the job scripts go next to the result file (~/.cutthebullshit)
    t0 = time.time()
    print("publish %s -> %s" % (write_root, run_dir), flush=True)

    # 1. the run's folders (ProRes movies brought up to date first, so they match the frames being published)
    folders = (LAYERS, LAYOUTS, PREVIEWS)
    if not args.no_prores:
        from . import prores
        if prores.main(["--run", str(run_no)]):
            print("  some ProRes exports failed (see above) - publishing the rest", flush=True)
        folders += (PRORES,)
    for name in folders:
        src = os.path.join(write_root, name)
        if not os.path.isdir(src):
            print("  no %s in %s" % (name, write_root))
            continue
        n, copied, extra, nbytes = mirror(src, os.path.join(run_dir, name))
        print("  %-9s %d file(s), %d MB  (%d copied, %d already there%s)" % (
            name, n, round(nbytes / 1e6), copied, n - copied,
            ", %d other file(s) there left as they are" % extra if extra else ""), flush=True)

    # 2. relink tmp_write/RUN NN/... -> 01 PUBLISH/RUN NN/... (by rewriting the paths in an .aepx copy) and save there
    aepx = os.path.join(write_root, "_publish.aepx")
    lines = run_jsx({"project": project, "aepx": aepx, "result": RESULT}, work, LIST_JSX, "_publish_list.jsx").splitlines()
    errors = [l.split("\t", 1)[1] for l in lines if l.startswith("ERROR\t")]
    if errors or not os.path.exists(aepx):
        print("\n".join("  ERROR " + e for e in errors) or "  ERROR After Effects wrote no .aepx copy")
        return 1
    items, report, kept, outside = 0, [], 0, {}
    for l in lines:
        if not l.startswith("ITEM\t"):
            continue
        _, iid, still, missing, _folders, path = l.split("\t", 5)
        if path.startswith(write_root + os.sep):
            new = os.path.join(run_dir, os.path.relpath(path, write_root))
            if not os.path.exists(new):
                errors.append("not in the publish folder: %s" % new)
            items += 1
            report.append(new)
        else:
            kept += 1
            note = "" if path.startswith(DROPBOX + os.sep) else "   <- NOT in Dropbox"
            if missing == "1" or not os.path.exists(path):
                note = "   <- MISSING"
            if note:
                outside.setdefault(note.replace("   <- ", ""), []).append(path)
            report.append("kept link: %s%s" % (path, note))
    # one line per kind (the full list is in the report): files outside the publish folder open only where they are
    for kind, paths in sorted(outside.items()):
        roots = sorted({os.sep.join(p.split(os.sep)[:6]) for p in paths})
        print("  %d footage item(s) %s, e.g. %s  (under %s; all listed in the report)" % (
            len(paths), kind, paths[0], ", ".join(roots[:3]) + (" ..." if len(roots) > 3 else "")), flush=True)
    with open(aepx, encoding="utf-8") as fh:
        x = fh.read()
    old_p, new_p = 'fullpath="%s/' % escape(write_root, {'"': "&quot;"}), 'fullpath="%s/' % escape(run_dir, {'"': "&quot;"})
    n_paths = x.count(old_p)
    # open it from the publish folder: After Effects also resolves footage relative to the project file, which from
    # tmp_write would lead straight back to tmp_write
    remove_file(aepx)                                    # the copy in tmp_write
    aepx = os.path.join(run_dir, "_publish.aepx")
    with open(aepx, "w", encoding="utf-8") as fh:
        fh.write(x.replace(old_p, new_p))
    out = run_jsx({"aepx": aepx, "save_as": save_as, "close": not args.keep_open, "result": RESULT}, work,
                  OPEN_JSX, "_publish_open.jsx").splitlines()
    errors += [l.split("\t", 1)[1] for l in out if l.startswith("ERROR\t")]
    links = [l.split("\t")[2] for l in out if l.startswith("LINK\t")]
    still_run = [p for p in links if p.startswith(write_root + os.sep)]
    if still_run:
        errors.append("%d footage item(s) still point at %s, e.g. %s" % (len(still_run), write_root, still_run[0]))
    offline = sum(1 for l in out if l.startswith("LINK\t1\t"))
    if not any(l.startswith("SAVED\t") for l in out):
        errors.append("After Effects didn't save %s" % save_as)
    # the _publish.aepx in the publish folder stays (Dropbox: never deleted; the next publish overwrites it)
    print("  %d footage path(s) moved to %s (%d of them online-only / not readable now: they load once available "
          "offline)" % (n_paths, run_dir, offline), flush=True)
    for e in errors:
        print("  ERROR " + e)
    stem = os.path.splitext(PROJECT_NAME)[0]
    with open(os.path.join(run_dir, stem + "Report.txt"), "w") as fh:
        fh.write("Report created: %s\nProject: %s\nSaved from: %s\nFootage items relinked to %s: %d\n"
                 "Footage items left as they were: %d\n\nFootage:\n%s\n" % (
                     time.strftime("%Y-%m-%d %H:%M:%S"), save_as, project, run_dir, items, kept,
                     "\n".join("  " + r for r in sorted(set(report)))))
        if errors:
            fh.write("\nErrors:\n%s\n" % "\n".join("  " + e for e in errors))
    out = lines + out

    # one <scene>.txt per scene comp in 01 PUBLISH/RUN NN/
    scenes = {}
    for l in out:
        f = l.split("\t")
        if f[0] == "SCENE":
            scenes[f[1]] = {"w": f[2], "h": f[3], "fps": float(f[4]), "dur": float(f[5]), "layers": []}
        elif f[0] == "LAYER" and f[1] in scenes:
            scenes[f[1]]["layers"].append("%3s  %s" % (f[2], f[3]))
    for name, sc in sorted(scenes.items()):
        txt = os.path.join(run_dir, name.replace("/", "-") + ".txt")
        with open(txt, "w") as fh:
            fh.write("%s\n\n%s\nProject: %s\nComp: %s (root of the Project panel)\n%sx%s, %g fps, %gs\n"
                     "Published: %s\n\nLayers (top to bottom):\n%s\n" % (
                         name, run_name(run_no), save_as, name, sc["w"], sc["h"], sc["fps"], sc["dur"],
                         time.strftime("%Y-%m-%d %H:%M:%S"), "\n".join(sc["layers"])))
        print("  %s" % txt)
    progress.tick("publish", 10 ** 9)
    print("  %d footage item(s) relinked to Dropbox, %d left as they were, in %ds -> %s%s" % (
        items, kept, time.time() - t0, save_as,
        "" if args.keep_open else "  (project closed, new empty project open)"), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
