#!/usr/bin/env python3
"""Record the benchmark baseline (tests/benchmark_baseline.json).

Run deliberately, never as part of a fix: the baseline is the contract that a
previously-passing case may not quietly start failing. Re-record when the
question set changes, and say why in the commit message.

    uv run --with pytest python tools/record_baseline.py
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

os.environ["HOWZO_DB"] = os.path.join(tempfile.mkdtemp(prefix="howzo-baseline-"), "howzo.db")

from howzo import __version__, seed           # noqa: E402
from howzo.commands import cmd_ask            # noqa: E402
from howzo.db import db, upsert               # noqa: E402
from test_benchmark import CASES, DISTRACTORS, _judge, _top  # noqa: E402


def main():
    c = db()
    for name, source, one in DISTRACTORS:
        upsert(c, name, source, "", "", one)
    seed.apply_seed(c)
    c.commit()

    passing, failing, forbidden = [], [], []
    counts = {}
    for case in CASES:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_ask(case.query.split())
        names = [n for n, _ in re.findall(r"^(\S+)\s+\(([^)]*)\)$", buf.getvalue(), re.M)][:3]
        reason = _judge(case, names)
        if reason:
            failing.append(case.query)
            if case.forbid_topk & set(names):
                forbidden.append(case.query)
        else:
            passing.append(case.query)
            counts[case.category] = counts.get(case.category, 0) + 1
        print("%-38s %-10s %s" % (case.query, "pass" if not reason else "MISS",
                                  " ".join(names) or "(nothing)"))

    baseline = {
        "recorded_with": "howzo %s" % __version__,
        "scorer": "per-concept best field, rarity-weighted (sqrt IDF); name tier exact",
        "cases": len(CASES),
        "seed_entries": len(seed.SEED),
        "distractors": len(DISTRACTORS),
        "passing": sorted(passing),
        "categories": counts,
        "known_misses": sorted(failing),
        "forbidden_answers": sorted(forbidden),
    }
    out = os.path.join(ROOT, "tests", "benchmark_baseline.json")
    with open(out, "w") as fh:
        json.dump(baseline, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("\n%d/%d passing -> %s" % (len(passing), len(CASES), out))
    c.close()


if __name__ == "__main__":
    main()
