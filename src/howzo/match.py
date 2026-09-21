"""Query tokenization and ranking.

Match = FTS5 BM25 + a word-boundary token-coverage re-rank in Python,
so 'kill' never matches 'skill' and 'port' never matches 'report'.
"""
import re

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


def coverage(row, toks):
    """How many distinct query tokens appear in this row (word-boundary match)."""
    hay = " ".join(filter(None, [row["name"], row["oneliner"], row["when_to_use"],
                                row["help_excerpt"]])).lower()
    return sum(1 for t in toks if re.search(r"(?<![a-z0-9])" + re.escape(t), hay))


def has_word(hay, tok):
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(tok), hay.lower()))


def find_by_name(c, q):
    """Exact (case-insensitive) or prefix name lookup."""
    q = q.strip().lower()
    if not q:
        return None
    row = c.execute("SELECT * FROM tools WHERE lower(name)=?", (q,)).fetchone()
    if row:
        return row
    return c.execute("SELECT * FROM tools WHERE lower(name) LIKE ?", (q + "%",)).fetchone()


def rank_rows(rows, toks):
    """Re-rank candidates: token-coverage bonus + field boost + BM25.

    Tokens found in high-signal fields (name, when_to_use — curated, not
    scraped) count extra, so a curated 'when to use' description wins over
    a shorter doc that merely mentions the same words more densely.
    Rows without a bm25 score still rank by coverage."""
    def rank_key(r):
        try:
            s = r["score"]
        except (IndexError, KeyError):
            s = 0.0
        title = " ".join(filter(None, [r["name"], r["when_to_use"]])).lower()
        title_cov = sum(1 for t in toks if re.search(r"(?<![a-z0-9])" + re.escape(t), title))
        return (-(2 * coverage(r, toks) + 1.5 * title_cov + 0.01 * max(0, -s)), r["name"])
    return sorted(rows, key=rank_key)
