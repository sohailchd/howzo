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
