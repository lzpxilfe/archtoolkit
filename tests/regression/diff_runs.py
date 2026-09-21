"""Compare two run_scenarios.py outputs (old, new) and print a per-scenario diff."""
from __future__ import annotations

import json
import math
import sys


def _flat(d, prefix=""):
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            out.update(_flat(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = d
    return out


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
    return a == b


def main():
    old = json.load(open(sys.argv[1], encoding="utf-8"))["scenarios"]
    new = json.load(open(sys.argv[2], encoding="utf-8"))["scenarios"]
    names = sorted(set(old) | set(new))
    for n in names:
        o = old.get(n, {"error": "missing"})
        w = new.get(n, {"error": "missing"})
        print("=" * 78)
        print(f"{n}: old={'ERROR' if 'error' in o else 'ok'} new={'ERROR' if 'error' in w else 'ok'}")
        if "error" in o:
            print("  old error:", str(o["error"])[:300])
        if "error" in w:
            print("  new error:", str(w["error"])[:300])
        fo = {k: v for k, v in _flat(o).items() if not k.startswith("messages") and not k.startswith("traceback")}
        fw = {k: v for k, v in _flat(w).items() if not k.startswith("messages") and not k.startswith("traceback")}
        keys = sorted(set(fo) | set(fw))
        changed = [(k, fo.get(k, "<absent>"), fw.get(k, "<absent>")) for k in keys if not _same(fo.get(k, "<absent>"), fw.get(k, "<absent>"))]
        if not changed:
            print("  numeric fingerprint: IDENTICAL")
        for k, a, b in changed[:60]:
            print(f"  {k}: {a!s:.60}  ->  {b!s:.60}")
        if len(changed) > 60:
            print(f"  ... {len(changed) - 60} more")
        om, wm = o.get("messages", []), w.get("messages", [])
        if om != wm:
            print(f"  messages old({len(om)}): " + " || ".join(m[:70] for m in om[:6]))
            print(f"  messages new({len(wm)}): " + " || ".join(m[:70] for m in wm[:8]))


if __name__ == "__main__":
    main()
