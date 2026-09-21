"""Run every scenario in scenarios_*.py against ONE repo checkout and dump JSON.

    QT_QPA_PLATFORM=offscreen /usr/bin/python3.12 run_scenarios.py <repo_root> <out.json> [scenario_name ...]

Each scenario module defines functions `scenario_<tool>(ctx) -> dict` where ctx has
.repo_root, .iface, .tmp (a fresh temp dir per scenario), and helpers from qgis_env.
A scenario returns a JSON-serialisable dict of numeric fingerprints (use
qgis_env.raster_summary / layer_summary) plus "messages": the message-bar texts.
Exceptions are captured as {"error": "...", "traceback": "..."}; the runner never dies.
"""
from __future__ import annotations

import glob
import importlib
import json
import os
import sys
import tempfile
import traceback
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qgis_env  # noqa: E402


def main():
    os.environ["ARCHTOOLKIT_NO_DIALOG_MEMORY"] = "1"
    qgis_env.ensure_gdal_shims()
    repo_root = os.path.abspath(sys.argv[1])
    out_path = sys.argv[2]
    only = set(sys.argv[3:])
    os.chdir(repo_root)
    app, iface = qgis_env.boot(repo_root)
    from qgis.core import QgsProject
    results = {"repo_root": repo_root, "scenarios": {}}
    mods = sorted(glob.glob(os.path.join(HERE, "scenarios_*.py")))
    for mp in mods:
        mod = importlib.import_module(os.path.splitext(os.path.basename(mp))[0])
        for name in sorted(dir(mod)):
            if not name.startswith("scenario_"):
                continue
            short = name[len("scenario_"):]
            if only and short not in only:
                continue
            fn = getattr(mod, name)
            QgsProject.instance().removeAllMapLayers()
            iface._bar.messages.clear()
            ctx = types.SimpleNamespace(repo_root=repo_root, iface=iface, tmp=tempfile.mkdtemp(prefix=f"atk_{short}_"), env=qgis_env)
            try:
                res = fn(ctx)
                if not isinstance(res, dict):
                    res = {"value": res}
            except Exception as exc:  # scenario must never kill the run
                res = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-1500:]}
            msgs = []
            for args, kwargs in iface.pushed():
                try:
                    msgs.append(" | ".join(str(a) for a in args[:2]))
                except Exception:
                    msgs.append(repr(args)[:200])
            res["messages"] = msgs
            results["scenarios"][short] = res
            print(f"[{short}] {'ERROR ' + res['error'] if 'error' in res else 'ok'}", flush=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
