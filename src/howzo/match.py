"""Query tokenization and ranking.

Match = FTS5 BM25 + a word-boundary token-coverage re-rank in Python,
so 'kill' never matches 'skill' and 'port' never matches 'report'.
"""
import os
import re
import sqlite3

STOP = {"a", "an", "and", "are", "as", "at", "can", "do", "does", "for", "from",
        "get", "how", "i", "in", "into", "is", "it", "me", "my", "on", "of", "or", "that",
        "the", "to", "up", "what", "whats", "which", "with", "you", "your", "show", "shows",
        "showing", "across", "by", "per", "use", "using"}


def query_tokens(q):
    """Lowercase word tokens, stop words removed, de-duped, capped at 10."""
    return list(dict.fromkeys(t for t in re.findall(r"[a-z0-9]+", q.lower())
                              if len(t) > 1 and t not in STOP))[:10]


def fts_query(q):
    """FTS5 match expression (quoted OR of tokens), or None if nothing to search."""
    toks = query_tokens(q)
    if not toks:
        return None
    return " OR ".join('"%s"' % t for t in toks)


def _tok_in(tok, words):
    """Prefix-stemmed containment: 'match'~'matching', 'find'~'finds',
    'file'~'filenames'. Bidirectional so a corrected longer token still
    hits its shorter base form. Substring confusables stay excluded:
    'kill' is not in 'skill', 'port' not in 'report'. A short query token
    (len < 4) only counts as an exact match: 'ip' must not hit 'ip2cc'
    and 'pdf' must not hit 'pdftohtml' — format/abbreviation words are
    not stems of those names."""
    for w in words:
        if w == tok or (len(tok) >= 4 and w.startswith(tok)) \
                or (len(w) >= 3 and tok.startswith(w)):
            return True
    return False


def coverage(row, toks):
    """How many distinct query tokens appear in this row (prefix-stemmed match)."""
    hay = " ".join(filter(None, [row["name"], row["oneliner"], row["when_to_use"],
                                row["help_excerpt"]])).lower()
    words = re.findall(r"[a-z0-9]+", hay)
    return sum(1 for t in toks if _tok_in(t, words))


def has_word(hay, tok):
    return _tok_in(tok, re.findall(r"[a-z0-9]+", hay.lower()))


def _lev(a, b, cap=2):
    """Damerau-Levenshtein distance (counts a single adjacent transposition
    as one edit — 'macthing' -> 'matching'), early-terminated above cap."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    la, lb = len(a), len(b)
    prev2 = None
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                base = prev2[j - 2] if prev2 is not None else 0
                if base + cost < cur[j]:
                    cur[j] = base + cost
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[lb]


_vocab_cache = {}


def clear_vocab_cache():
    """Drop in-memory vocab maps. Call after the corpus changes (a rescan):
    the on-disk vocab table is cleared by cmd_scan, and this drops any map a
    live connection cached from the old corpus."""
    _vocab_cache.clear()


def _vocab(c):
    """Word -> document-frequency map over the whole index, built once per db."""
    key = c.execute("PRAGMA database_list").fetchone()[2]
    v = _vocab_cache.get(key)
    if v is None:
        if c.execute("SELECT 1 FROM vocab LIMIT 1").fetchone() is None:
            df = {}
            for r in c.execute("SELECT name, oneliner, when_to_use, help_excerpt FROM tools"):
                text = " ".join(x for x in r if x).lower()
                for w in set(re.findall(r"[a-z0-9]+", text)):
                    if len(w) > 2:
                        df[w] = df.get(w, 0) + 1
            c.executemany("INSERT OR REPLACE INTO vocab(word, df) VALUES(?, ?)",
                          list(df.items()))
            c.commit()
        v = {r[0]: r[1] for r in c.execute("SELECT word, df FROM vocab")}
        _vocab_cache[key] = v
    return v


def expand_tokens(c, toks, cap=1):
    """Spell-correct query tokens against the index vocabulary.

    Returns (search_toks, fts_toks, resolved_toks): search_toks = original
    tokens plus nearest-index-word corrections (edit distance <= cap) for
    tokens with no exact match, so typos ('fike', 'occurence', 'macthing')
    still reach 'file', 'occurrence', 'matching'. fts_toks drops terms in
    more than half the corpus — FTS5 bm25 gives them negative idf, so they
    only push good rows out of the candidate window. resolved_toks maps each
    original token to its correction (or itself) — the fair term set for
    'all terms matched' judgments."""
    v = _vocab(c)
    search, seen = list(toks), set(toks)
    fixed = {}
    for t in toks:
        if t in v:
            continue
        best, bkey = None, None
        for w in v:
            if abs(len(w) - len(t)) > cap:
                continue
            d = _lev(t, w, cap)
            if d > cap:
                continue
            # ties go to the most frequent word, then alphabetical
            key = (d, -v[w], w)
            if bkey is None or key < bkey:
                best, bkey = w, key
        # substring pairs are confusables, not typos ('kill' must never
        # become 'skill', 'port' never 'report')
        if best is not None and t not in best and best not in t:
            fixed[t] = best
            if best not in seen:
                seen.add(best)
                search.append(best)
    n_docs = c.execute("SELECT count(*) FROM tools").fetchone()[0]

    def fts_df(t, _cache={}):
        """How many docs the FTS index actually matches for t.

        Measured on the FTS index itself rather than the raw-word vocab df:
        the index is porter-stemmed, so 'files' matches every 'file' doc —
        the vocab df of the exact word would keep 'files' in the query and
        the OR of it with the real terms would bury the right tool (ls for
        'list files') outside the candidate window."""
        if t not in _cache:
            try:
                _cache[t] = c.execute(
                    "SELECT count(*) FROM tools_fts WHERE tools_fts MATCH ?",
                    ('"%s"' % t,)).fetchone()[0]
            except sqlite3.OperationalError:
                _cache[t] = v.get(t, 0)
        return _cache[t]

    fts = [t for t in search if fts_df(t) <= n_docs / 2]
    if not fts:
        # every term is ultra-common; reverting to the full set would
        # reinstate the negative-idf query this filter exists to avoid —
        # keep just the rarest term so the query stays discriminating
        fts = [min(search, key=lambda t: (fts_df(t), t))]
    return search, fts, [fixed.get(t, t) for t in toks]


def name_hits(c, toks):
    """Rows whose name (or well-known alias) matches a token the same way
    rank_rows credits it: exact at any length, prefix for len>=4, or an
    alias ('list' -> ls). These rows must always reach the re-rank — a
    name-level hit is the strongest signal and must not depend on how
    deep BM25 buries the row (ls ranks 233rd on 'list' alone)."""
    ids = set()
    for t in toks:
        for r in c.execute("SELECT id FROM tools WHERE lower(name) = ?", (t,)):
            ids.add(r[0])
        if len(t) >= 4:
            for r in c.execute("SELECT id FROM tools WHERE lower(name) LIKE ?", (t + "%",)):
                ids.add(r[0])
    for name, alias in NAME_ALIASES.items():
        if any(_tok_in(t, [name, alias]) for t in toks):
            names = [name] + ([name + ".exe"] if os.name == "nt" else [])
            for n in names:
                r = c.execute("SELECT id FROM tools WHERE name = ?", (n,)).fetchone()
                if r:
                    ids.add(r[0])
    if not ids:
        return []
    return c.execute("SELECT * FROM tools WHERE id IN (%s)"
                     % ",".join("?" * len(ids)), sorted(ids)).fetchall()


def find_by_name(c, q):
    """Exact (case-insensitive) or prefix name lookup.

    On Windows the index stores .exe-suffixed names, so a bare name
    ('python') must also match 'python.exe'."""
    q = q.strip().lower()
    if not q:
        return None
    names = [q] + ([q + ".exe"] if os.name == "nt" else [])
    row = c.execute("SELECT * FROM tools WHERE lower(name) IN (%s)"
                    % ",".join("?" * len(names)), names).fetchone()
    if row:
        return row
    for n in names:
        row = c.execute("SELECT * FROM tools WHERE lower(name) LIKE ?", (n + "%",)).fetchone()
        if row:
            return row
    return None


# Short utilities whose name is an abbreviation, not a stem: users type the
# full word, and prefix-stemming can't bridge "cp" to "copy" (c-o-p-y does
# not start with c-p). A query token that prefix-matches the alias word
# counts as a NAME-tier hit for that tool.
NAME_ALIASES = {
    "cp": "copy",
    "mv": "move",
    "rm": "remove",
    "ln": "link",
    "ls": "list",
    "mkdir": "directory",
}


def rank_rows(rows, toks):
    """Re-rank candidates by field tier: intent fields beat description.

    Four tiers, each normalized by the number of query tokens:
      3.0  name                 — the tool's own name (or its well-known
           alias: cp = copy, mv = move, ...; the strongest single signal)
      2.0  when_to_use          — curated intent phrase; mentions of generic
           words ("file", "folder") are real intent here but must not beat
           a name-level hit
      1.0  oneliner             — concise description (curated for
           package tools, man synopsis for system tools)
      0.5  help_excerpt         — scraped man text; long pages mention
           many query words by accident and must not win on volume
    Without normalization a long doc that merely mentions more query
    words would always outscore the right tool. Ties break on the FTS5
    bm25 score (more negative = denser match), then name. Rows without
    a score (LIKE fallback) tie at 0."""
    n = len(toks) or 1
    def rank_key(r):
        try:
            s = r["score"]
        except (IndexError, KeyError):
            s = 0.0
        name = r["name"].lower()
        if name.endswith(".exe"):
            name = name[:-4]
        alias = NAME_ALIASES.get(name)
        when = (r["when_to_use"] or "").lower()
        oneliner = (r["oneliner"] or "").lower()
        excerpt = (r["help_excerpt"] or "").lower()
        n_cov = sum(1 for t in toks if _tok_in(t, [name] + ([alias] if alias else [])))
        w_cov = sum(1 for t in toks if _tok_in(t, re.findall(r"[a-z0-9]+", when)))
        o_cov = sum(1 for t in toks if _tok_in(t, re.findall(r"[a-z0-9]+", oneliner)))
        e_cov = sum(1 for t in toks if _tok_in(t, re.findall(r"[a-z0-9]+", excerpt)))
        return (-(3.0 * n_cov / n + 2.0 * w_cov / n + 1.0 * o_cov / n + 0.5 * e_cov / n),
                s, r["name"])
    return sorted(rows, key=rank_key)
