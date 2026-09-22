"""Query tokenization and ranking.

Match = FTS5 BM25 + a word-boundary token-coverage re-rank in Python,
so 'kill' never matches 'skill' and 'port' never matches 'report'.
"""
import os
import re
import sqlite3

from . import config

STOP = {"a", "am", "an", "and", "are", "as", "at", "by", "can", "do", "does",
        "for", "from", "get", "got", "have", "how", "i", "in", "into", "is",
        "it", "me", "much", "my", "need", "of", "on", "or", "per", "please",
        "show", "showing", "shows", "tell", "that", "the", "there", "to", "up",
        "use", "using", "want", "was", "were", "what", "whats", "which",
        "with", "you", "your", "across"}


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

    Returns (search_toks, fts_toks, resolved_toks, typed_toks): search_toks =
    original tokens plus nearest-index-word corrections (edit distance <=
    cap) for tokens with no exact match, so typos ('fike', 'occurence',
    'macthing') still reach 'file', 'occurrence', 'matching'. typed_toks are
    the words that may earn the name tier: what the user typed plus the
    spellings its typos were corrected to ('mkder' -> mkdir is the user's
    word, misspelled; 'dir' -> directory is howzo's own inference).
    fts_toks drops terms in more than half the corpus — FTS5 bm25 gives them
    negative idf, so they only push good rows out of the candidate window.
    resolved_toks maps each original token to its correction (or itself) —
    the fair term set for 'all terms matched' judgments.

    A word in TERM_ALIASES expands to the word the index actually uses:
    users say 'ram', manuals say 'memory', and no stem rule can bridge two
    unrelated words. A three-letter FRAGMENT does the same, decided from the
    index itself (see _fragment_word): 'mem' is a word in one row's text but
    'memory' is in 70, so the query is really about memory. A fragment one
    edit away from its expansion is a typo of it ('fin' -> find) and counts
    as a word the user typed; a real abbreviation does not (see typed_toks)."""
    v = _vocab(c)
    n_docs = c.execute("SELECT count(*) FROM tools").fetchone()[0]
    search, seen = list(toks), set(toks)
    fixed = {}
    typed = list(toks)   # name-tier eligible: the user's own (corrected) words
    for t in toks:
        w = TERM_ALIASES.get(t)
        if w is None:
            w = _fragment_word(v, t, n_docs)
            if w is not None and _lev(t, w, cap) <= cap:
                # 'fin' -> 'find' is one edit from the word they typed: that
                # is the word they meant, misspelled. 'mem' -> 'memory' is
                # not — it is an abbreviation howzo inferred (see typed).
                typed.append(w)
        if w and w not in seen:
            seen.add(w)
            search.append(w)
            fixed[t] = w
    for t in toks:
        if t in v or t in fixed:
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
            typed.append(best)   # a corrected typo is the word they meant
            if best not in seen:
                seen.add(best)
                search.append(best)

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
    return search, fts, [fixed.get(t, t) for t in toks], typed


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
    for name, alias in NAME_ALIASES.items():
        if any(t == name or t == alias for t in toks):
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
    """Exact (case-insensitive) name lookup, plus the two cases where typing
    less than the installed name is legitimate:

      - Windows stores .exe-suffixed names, so 'python' must find 'python.exe'
      - build managers install versioned binaries, so 'python' must find
        'python3.13' and 'findrule' must find 'findrule5.34'

    Anything else that merely starts with the query is a different tool:
    'search' is not 'searchdiagnose' and 'port' is not 'portaudio'. This runs
    before any ranking, so a loose prefix here answers with the wrong tool
    outright."""
    q = q.strip().lower()
    if not q:
        return None
    names = [q] + ([q + ".exe"] if os.name == "nt" else [])
    row = c.execute("SELECT * FROM tools WHERE lower(name) IN (%s)"
                    % ",".join("?" * len(names)), names).fetchone()
    if row:
        return row
    for n in names:
        pattern = re.compile(re.escape(n) + r"[0-9.]+\Z")
        for r in c.execute("SELECT * FROM tools WHERE lower(name) LIKE ?"
                           " ORDER BY name", (n + "%",)):
            if pattern.match((r["name"] or "").lower()):
                return r
    return None


# Short utilities whose name is an abbreviation, not a stem: users type the
# full word, and prefix-stemming can't bridge "cp" to "copy" (c-o-p-y does
# not start with c-p). A query token that IS the alias word counts as a
# NAME-tier hit for that tool.
#
# Only verbs belong here. A noun the user types ("directory", "folder") is a
# topic, not a claim about a tool's name: with "mkdir": "directory" in this
# table, a typed "delete directory" answered mkdir, whose real evidence is its
# prose ("create a new folder or directory") - which is exactly what it should
# be scored on. mkdir still wins "make directory" on that prose.
NAME_ALIASES = {
    "cp": "copy",
    "mv": "move",
    "rm": "remove",
    "ln": "link",
    "ls": "list",
}

# Query words that name a resource under a name the index never uses:
# 'ram' is Random Access Memory — unrelated spelling to 'memory', so no
# prefix/stem/typo rule can reach it, and du (whose intent prose is full of
# the generic word 'usage') wins the query instead of the tools that report
# memory. Maps a query token to the word the manuals use.
TERM_ALIASES = {
    "ram": "memory",
}

# A three-letter query word whose own document frequency is dwarfed by a
# longer word that starts with it is a fragment of that word, not a word:
# 'mem' is in one row's text while 'memory' is in 70 ('add', by contrast,
# is in 108 rows and 'address' in 92 — a real word, never expanded).
FRAGMENT_RATIO = 4
FRAGMENT_MIN_DF = 3         # a word in fewer rows is not a word manuals use
FRAGMENT_MIN_SHARE = 100    # ...nor one the corpus barely uses (1% of it)


def _fragment_word(v, tok, n_docs):
    """The word a 3-letter query token abbreviates, or None.

    Read from the index's own word frequencies instead of a hand-written
    list, so anything the manuals abbreviate the same way resolves on any
    machine: 'mem' -> 'memory', 'dir' -> 'directory', 'env' -> 'environment',
    'man' -> 'manual'. Both guards matter: the family word must be common
    enough to be a word rather than a tool name (a name like 'imgdir' must
    not win for 'img'), and the fragment itself must be rare against it —
    otherwise 'add' would expand to 'address' and arp outrank alias."""
    if len(tok) != 3:
        return None
    floor = max(FRAGMENT_MIN_DF, n_docs // FRAGMENT_MIN_SHARE)
    fam = [(d, w) for w, d in v.items()
           if w != tok and w.startswith(tok) and d >= floor]
    if not fam:
        return None
    d, w = max(fam)
    return w if v.get(tok, 0) * FRAGMENT_RATIO < d else None


def rank_rows(rows, toks, platform=None, name_toks=None):
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
    a score (LIKE fallback) tie at 0.

    name_toks (default: toks) are the words the user meant — what they typed
    plus the spelling a typo was corrected to (expand_tokens returns them) —
    and only those can earn the name tier. An alias or fragment expansion is
    howzo's inference about the topic, not a claim about a tool's name:
    expanding 'dir' to 'directory' must not let mkdir (whose alias is
    'directory') beat rm for 'delete dir', while 'mkder' -> mkdir still can.

    Platform is a PRIMARY sort key, not a score fudge: every native row
    (no platform, 'all', or this machine's platform) sorts ahead of every
    foreign row, whatever its tier score. A score multiplier was tried and
    fails — an exact name hit on a foreign row (ip on macOS) survives any
    sane penalty and outranks the machine's real tool. Foreign references
    are still returned (ranked among themselves), so a Mac user asking
    about a Windows command still gets the answer — just after every
    answer that applies to their machine.
    """
    n = len(toks) or 1
    typed = toks if name_toks is None else name_toks
    cur = platform or config.platform_name()

    def rank_key(r):
        try:
            s = r["score"]
        except (IndexError, KeyError):
            s = 0.0
        try:
            p = (r["platform"] or "").lower()
        except (IndexError, KeyError):
            p = ""
        group = 1 if (p and p != "all" and p != cur) else 0
        name = r["name"].lower()
        if name.endswith(".exe"):
            name = name[:-4]
        alias = NAME_ALIASES.get(name)
        when = (r["when_to_use"] or "").lower()
        oneliner = (r["oneliner"] or "").lower()
        excerpt = (r["help_excerpt"] or "").lower()
        # A tool is claimed by its own name or by a curated alias - never by a
        # word that merely starts the same way. Prefix claims are how 'search'
        # answered searchdiagnose, 'check' answered checkgid and 'memory'
        # answered memory_pressure. With them gone, the curated data has to say
        # what those tools are for (see howzo/seed.py).
        n_cov = sum(1 for t in typed if t == name or (alias and t == alias))
        w_cov = sum(1 for t in toks if _tok_in(t, re.findall(r"[a-z0-9]+", when)))
        o_cov = sum(1 for t in toks if _tok_in(t, re.findall(r"[a-z0-9]+", oneliner)))
        e_cov = sum(1 for t in toks if _tok_in(t, re.findall(r"[a-z0-9]+", excerpt)))
        tier = 3.0 * n_cov / n + 2.0 * w_cov / n + 1.0 * o_cov / n + 0.5 * e_cov / n
        return (group, -tier, s, r["name"])
    return sorted(rows, key=rank_key)
