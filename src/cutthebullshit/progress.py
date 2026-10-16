"""Live ETA for cutthebullshit run runs.

cutthebullshit run calls begin() with the plan (units and estimated seconds per unit for each step); the steps call
tick() after every frame / chunk / sequence. Outside a cutthebullshit run run (a step run on its own) tick() does nothing.
"""

import time

_plan, _state = {}, {}


def fmt(sec):
    sec = int(round(max(0, sec)))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return ("%dh%02dm" % (h, m)) if h else ("%dm%02ds" % (m, s)) if m else ("%ds" % s)


def begin(plan):
    """plan: ordered {step: (units, est_seconds_per_unit[, pending])}; pending = units the step will really
    process (the rest it skips as already done; default: all of them)"""
    _plan.clear()
    _plan.update(plan)
    _state.clear()
    _state.update(t0=time.time(), step=None, done={k: 0 for k in plan}, finished=set(), step_t0=None,
                  skipped=0, skip_time=0.0, last=time.time())


def step_start(step):
    if step in _plan:
        _state["step"], _state["step_t0"], _state["last"] = step, time.time(), time.time()
        _state["skipped"], _state["skip_time"] = 0, 0.0


def step_end(step):
    if step in _plan:
        _state["finished"].add(step)
        _state["done"][step] = _plan[step][0]


def remaining():
    left = 0.0
    for k, plan in _plan.items():
        units, spf = plan[0], plan[1]
        pending = plan[2] if len(plan) > 2 else units
        if k in _state["finished"]:
            continue
        worked = _state["done"][k] - _state["skipped"] if k == _state["step"] else 0
        if k == _state["step"] and worked > 0:
            # measured speed of the running step, leaving out frames that were skipped (resumed runs)
            spf = (time.time() - _state["step_t0"] - _state["skip_time"]) / worked
        left += max(0, pending - worked) * spf
    return left


def tick(step, n=1, skipped=False):
    if not _plan or step not in _plan:
        return
    now = time.time()
    if skipped and step == _state["step"]:
        _state["skipped"] += n
        _state["skip_time"] += now - _state["last"]
    _state["last"] = now
    _state["done"][step] = min(_plan[step][0], _state["done"][step] + n)
    left = remaining()
    elapsed = time.time() - _state["t0"]
    pct = 100.0 * elapsed / max(elapsed + left, 1e-6)
    print("   [%s %d/%d]  run %2.0f%%  |  elapsed %s  |  remaining ~%s  |  finish ~%s" % (
        step, _state["done"][step], _plan[step][0], pct, fmt(elapsed), fmt(left),
        time.strftime("%H:%M", time.localtime(time.time() + left))), flush=True)
