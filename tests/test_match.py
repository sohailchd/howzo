from howzo import match


class TestQueryTokens:
    def test_basic(self):
        assert match.query_tokens("how do I rotate a pdf") == ["rotate", "pdf"]

    def test_dedup_preserves_order(self):
        assert match.query_tokens("kill kill kill") == ["kill"]

    def test_capped_at_ten(self):
        toks = match.query_tokens(" ".join(f"word{i}" for i in range(20)))
        assert len(toks) == 10

    def test_single_char_dropped(self):
        assert match.query_tokens("a b c kill") == ["kill"]

    def test_all_stopwords(self):
        assert match.query_tokens("how to") == []


class TestFtsQuery:
    def test_none_when_no_tokens(self):
        assert match.fts_query("the") is None

    def test_quoted_or_expression(self):
        assert match.fts_query("kill port") == '"kill" OR "port"'


class TestCoverage:
    def test_kill_does_not_match_skill(self):
        row = {"name": "skill", "oneliner": "manage skills", "when_to_use": "", "help_excerpt": ""}
        assert match.coverage(row, ["kill"]) == 0

    def test_port_does_not_match_report(self):
        row = {"name": "report", "oneliner": "build reports", "when_to_use": "", "help_excerpt": ""}
        assert match.coverage(row, ["port"]) == 0

    def test_exact_words_count(self):
        row = {"name": "kill", "oneliner": "kill a process", "when_to_use": "", "help_excerpt": ""}
        assert match.coverage(row, ["kill", "process"]) == 2

    def test_has_word_boundaries(self):
        assert match.has_word("skillful", "kill") is False
        assert match.has_word("kill -9 the process", "kill") is True
        assert match.has_word("port 8080", "port") is True
        assert match.has_word("report port", "port") is True


class TestRankRows:
    def test_full_coverage_wins(self):
        full = {"name": "lsof", "oneliner": "list open files and network ports",
                "when_to_use": "", "help_excerpt": "", "score": 1.0}
        partial = {"name": "lo", "oneliner": "lists directories",
                   "when_to_use": "", "help_excerpt": "", "score": 0.5}
        rows = match.rank_rows([partial, full], ["ports"])
        assert rows[0]["name"] == "lsof"

    def test_scoreless_rows_still_rank(self):
        a = {"name": "aaa", "oneliner": "open ports", "when_to_use": "", "help_excerpt": ""}
        b = {"name": "bbb", "oneliner": "unrelated", "when_to_use": "", "help_excerpt": ""}
        rows = match.rank_rows([b, a], ["ports"])
        assert rows[0]["name"] == "aaa"


class TestFindByName:
    def test_exact_and_prefix(self, c):
        from howzo.db import upsert
        upsert(c, "jq", "brew", "1.7", "", "json processor")
        c.commit()
        assert match.find_by_name(c, "JQ")["name"] == "jq"
        assert match.find_by_name(c, "j")["name"] == "jq"
        assert match.find_by_name(c, "qqq") is None
        assert match.find_by_name(c, "  ") is None

    def test_curated_when_to_use_beats_denser_scrape(self):
        # same coverage; the row with query tokens in its curated
        # when_to_use ranks above one that only matches in scraped text
        curated = {"name": "ifconfig", "oneliner": "configure network interface parameters",
                   "when_to_use": "find or change your ip address", "help_excerpt": "", "score": -10.0}
        scraped = {"name": "logresolve", "oneliner": "resolve ip-addresses to hostnames",
                   "when_to_use": "", "help_excerpt": "host-to-find, ip addresses", "score": -15.0}
        rows = match.rank_rows([scraped, curated], ["find", "ip", "address"])
        assert rows[0]["name"] == "ifconfig"


class TestLev:
    def test_distances(self):
        from howzo.match import _lev
        assert _lev("fike", "file") == 1
        assert _lev("macthing", "matching") == 1
        assert _lev("occurence", "occurrence") == 1
        assert _lev("kitten", "sitting", cap=3) == 3


class TestExpandTokens:
    def test_typo_correction(self, c):
        from howzo.db import upsert
        upsert(c, "grep", "system", "", "", "print lines matching a pattern")
        c.execute("UPDATE tools SET help_excerpt='print selected lines from a file, first occurrence of a match' WHERE name='grep'")
        c.commit()
        search, fts, resolved = match.expand_tokens(c, match.query_tokens("find macthing occurence in fike"))
        assert "matching" in search and "file" in search and "occurrence" in search
        assert set(fts) <= set(search)
        assert resolved == ["find", "matching", "occurrence", "file"]

    def test_exact_tokens_untouched(self, c):
        from howzo.db import upsert
        upsert(c, "kill", "system", "", "", "terminate or signal a process")
        c.commit()
        search, fts, resolved = match.expand_tokens(c, match.query_tokens("kill a process"))
        assert search == ["kill", "process"]
        assert resolved == ["kill", "process"]
        assert fts

    def test_ties_go_to_more_frequent_word(self, c):
        # 'fike' is one edit from both 'file' and 'fire'; the word that
        # appears in more docs wins the tie. The corpus is big enough that
        # 'file' stays below the 50% ultra-common cutoff.
        from howzo.db import upsert
        upsert(c, "file", "system", "", "", "create and write files")
        upsert(c, "firewall", "system", "", "", "fire traffic filters")
        upsert(c, "other", "system", "", "", "something with a file in it")
        upsert(c, "alpha", "system", "", "", "sort lists alphabetically")
        upsert(c, "beta", "system", "", "", "measure memory bandwidth")
        c.commit()
        search, fts, resolved = match.expand_tokens(c, ["fike"])
        assert "file" in search and "fire" not in search
        assert "file" in fts

    def test_ultra_common_terms_dropped_from_fts(self, c):
        # a term in >50% of the corpus gets negative bm25 idf — it must
        # not be in the FTS query (it only pushes good rows out of the
        # window), but it stays in the search set for coverage
        from howzo.db import upsert
        for name in ("aaa", "bbb", "ddd", "eee"):
            upsert(c, name, "system", "", "", "file words here")
        upsert(c, "ccc", "system", "", "", "pattern only")
        upsert(c, "fff", "system", "", "", "nothing here at all")
        c.commit()
        search, fts, _ = match.expand_tokens(c, ["file", "pattern"])
        assert "file" in search and "pattern" in search
        assert fts == ["pattern"]  # 'file' (4/6 docs) dropped, 'pattern' (1/6) kept

    def test_ultra_common_all_keeps_rarest(self, c):
        # when EVERY term is ultra-common, reverting to the full set would
        # reinstate the negative-idf query — keep just the rarest term
        from howzo.db import upsert
        for name in ("aaa", "bbb", "ddd", "eee"):
            upsert(c, name, "system", "", "", "file word here")
        upsert(c, "ccc", "system", "", "", "alpha beta gamma")
        upsert(c, "fff", "system", "", "", "nothing here at all")
        c.commit()
        search, fts, _ = match.expand_tokens(c, ["file", "word"])
        assert search == ["file", "word"]
        assert fts == ["file"]  # both in 4/6 docs; tie broken alphabetically
