"""Formatting for terminal and MCP output."""
import re
import sqlite3


def best_help_lines(help_text, q, n=3):
    """The n help lines most relevant to query q (original order preserved)."""
    toks = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) > 2]
    if not toks:
        return []
    lines = [l.strip() for l in help_text.splitlines() if l.strip()]
    scored = []
    for l in lines:
        s = sum(l.lower().count(t) for t in toks[:5])
        if s:
            scored.append((s, l))
    scored.sort(key=lambda x: -x[0])
    top = [l for _, l in scored[:n * 2]][:n]
    return top


def render_tool(row, q=""):
    t = {k: row[k] for k in row.keys()} if isinstance(row, sqlite3.Row) else dict(row)
    if t.get("source") == "seed":
        # bundled reference entry, not something installed here: say where it
        # belongs so the answer is not mistaken for a local tool
        tag = "seed, %s" % (t.get("platform") or "all")
    else:
        tag = t["source"] + (f", {t['version']}" if t.get("version") else "")
    out = [f"{t['name']}  ({tag})"]
    if t.get("oneliner"):
        out.append(f"  {t['oneliner']}")
    if t.get("when_to_use"):
        out.append(f"  when: {t['when_to_use']}")
    if t.get("help_excerpt") and q:
        for l in best_help_lines(t["help_excerpt"], q):
            out.append(f"  | {l[:110]}")
    return "\n".join(out)
