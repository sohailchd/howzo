"""CLI command handlers (scan / ask / whatis / deep / add / list)."""
import os
import sqlite3
import time

from . import config
from .db import db, upsert
from .helptext import capture_help
from .match import coverage, fts_query, find_by_name, has_word, query_tokens, rank_rows
from .render import render_tool
from .scan import scanners


def cmd_scan(args):
    c = db()
    try:
        # preserve on-demand captured help + enrichments across rescans
        keep = {r["name"]: (r["help_excerpt"], r["help_captured_at"], r["when_to_use"])
                for r in c.execute("SELECT name, help_excerpt, help_captured_at, when_to_use FROM tools")}
        custom_rows = {r["name"]: (r["source"], r["version"], r["path"], r["oneliner"],
                                   r["when_to_use"], r["help_excerpt"], r["help_captured_at"])
                       for r in c.execute("SELECT * FROM tools WHERE source IN ('custom','npx')")}
        c.execute("DELETE FROM tools")
    except sqlite3.DatabaseError:
        print("  warning: db corrupted, rebuilding")
        d = config.db_dir()
        for f in os.listdir(d):
            if f.startswith("howzo.db"):
                os.remove(os.path.join(d, f))
        c = db()
        keep, custom_rows = {}, {}
    deep = "--deep" in args
    t0 = time.time()
    for fn in scanners():
        fn(c)
    # custom tools added via 'howzo add' must survive rescans
    for name, (src, ver, path, one, w, h, h_at) in custom_rows.items():
        c.execute("INSERT INTO tools(name, source, version, path, oneliner, when_to_use, help_excerpt, "
                  "help_captured_at, scanned_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(name) DO NOTHING",
                  (name, src, ver, path, one, w, h, h_at, time.strftime("%Y-%m-%d")))
    for name, (h, h_at, w) in keep.items():
        c.execute("UPDATE tools SET help_excerpt=?, help_captured_at=?, when_to_use=? WHERE name=?",
                  (h, h_at, w, name))
    c.commit()
    total = c.execute("SELECT COUNT(*) FROM tools").fetchone()[0]
    print(f"  inventory: {total} tools in {time.time()-t0:.0f}s")
    if deep:
        print("  capturing --help (can take a few minutes)...")
        rows = c.execute("SELECT id, name, path FROM tools").fetchall()
        done = 0
        for tid, name, path in rows:
            h = capture_help(name, path)
            if h:
                c.execute("UPDATE tools SET help_excerpt=?, help_captured_at=? WHERE id=?",
                          (h, time.strftime("%Y-%m-%d"), tid))
                done += 1
        c.commit()
        print(f"  help captured for {done}/{len(rows)} tools")
    else:
        print("  (tip: 'howzo scan --deep' also captures --help for richer answers;")
        print("   'howzo deep <tool>' captures help for one tool on demand)")
    return 0


def cmd_ask(args):
    q = " ".join(args).strip()
    if not q:
        print('usage: howzo ask "how do I ..."')
        return 1
    c = db()
    row = find_by_name(c, q)
    if row:
        print(render_tool(row, q))
        return 0
    ftsq = fts_query(q)
    toks = query_tokens(q)
    rows = []
    if ftsq:
        try:
            rows = c.execute(
                "SELECT t.*, bm25(tools_fts) AS score FROM tools_fts f JOIN tools t ON t.id=f.rowid "
                "WHERE tools_fts MATCH ? ORDER BY score LIMIT 12", (ftsq,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
    if not rows and toks:
        # fallback: broad LIKE candidates per token, then word-boundary filter
        cand = {}
        for t in toks:
            like = f"%{t}%"
            for r in c.execute("SELECT * FROM tools WHERE lower(name) LIKE ? OR lower(oneliner) LIKE ? "
                               "OR lower(when_to_use) LIKE ? OR lower(help_excerpt) LIKE ? LIMIT 60",
                               (like, like, like, like)):
                hay = " ".join(filter(None, [r["name"], r["oneliner"], r["when_to_use"], r["help_excerpt"]]))
                if has_word(hay, t):
                    cand[r["id"]] = r
        rows = list(cand.values())
    rows = rank_rows(rows, toks)
    if not rows:
        print(f"no match for: {q}\n  (try 'howzo scan --deep' to index --help text)")
        return 1
    for r in rows[:3]:
        print(render_tool(r, q))
        print()
    best_cov = max(coverage(r, toks) for r in rows[:3])
    if best_cov < len(toks):
        print("  (partial match - no tool advertises all terms)")
    return 0


def cmd_whatis(args):
    c = db()
    for name in args:
        row = find_by_name(c, name)
        if not row:
            print(f"unknown tool: {name}")
            continue
        t = {k: row[k] for k in row.keys()}
        print(render_tool(t, " ".join(args)))
        if t.get("help_excerpt"):
            print("  help:")
            for l in t["help_excerpt"].splitlines()[:12]:
                print("   ", l)
        print()
    return 0


def cmd_add(args):
    if len(args) < 2:
        print('usage: howzo add <name> "what it does"   (e.g. howzo add my-internal-tool \'syncs staging DB\')')
        return 1
    name = args[0]
    desc = " ".join(args[1:])
    c = db()
    upsert(c, name, "custom", "", "", desc)
    c.commit()
    print(f"added: {name} (source=custom, survives rescans)")
    return 0


def cmd_deep(args):
    if not args:
        print("usage: howzo deep <tool>")
        return 1
    name = args[0]
    c = db()
    row = c.execute("SELECT * FROM tools WHERE lower(name)=?", (name.lower(),)).fetchone()
    if not row:
        print(f"not in inventory: {name} (run 'howzo scan')")
        return 1
    t = {k: row[k] for k in row.keys()}
    print(f"capturing help for {name}...")
    h = capture_help(name, t.get("path"))
    if not h:
        print("  no help captured (binary not found or silent --help)")
        return 1
    c.execute("UPDATE tools SET help_excerpt=?, help_captured_at=? WHERE id=?",
              (h, time.strftime("%Y-%m-%d"), t["id"]))
    c.commit()
    print(f"  ok ({len(h)} chars)")
    return 0


def cmd_list(args):
    c = db()
    src = None
    if "--source" in args:
        src = args[args.index("--source") + 1]
    q = "SELECT * FROM tools"
    params = ()
    if src:
        q += " WHERE source=?"
        params = (src,)
    q += " ORDER BY source, name"
    rows = c.execute(q, params).fetchall()
    print(f"{'TOOL':<28} {'SRC':<8} {'VER':<14} WHAT")
    for r in rows:
        t = {k: r[k] for k in r.keys()}
        print(f"{t['name']:<28} {t['source']:<8} {str(t.get('version') or '')[:13]:<14} {t.get('oneliner','')[:70]}")
    print(f"\n{len(rows)} tools")
    return 0
