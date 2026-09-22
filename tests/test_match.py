import pytest

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

    def test_inferred_word_earns_no_name_tier(self):
        # 'dir' expands to 'directory', which is mkdir's alias: the expansion
        # is evidence about the topic, not a claim that the user typed mkdir,
        # so it must not outrank rm for "delete dir"
        mkdir = {"name": "mkdir", "oneliner": "make directories",
                 "when_to_use": "", "help_excerpt": ""}
        rm = {"name": "rm", "oneliner": "remove directory entries",
              "when_to_use": "delete a file or folder, remove files and directories",
              "help_excerpt": ""}
        rows = match.rank_rows([mkdir, rm], ["delete", "dir", "directory"],
                               name_toks=["delete", "dir"])
        assert [r["name"] for r in rows] == ["rm", "mkdir"]

    def test_typed_verb_alias_still_earns_the_name_tier(self):
        # 'copy' is a curated verb alias: a typed 'copy' claims cp by name
        cp = {"name": "cp", "oneliner": "copy files",
              "when_to_use": "", "help_excerpt": ""}
        rsync = {"name": "rsync", "oneliner": "a fast file-copying tool",
                 "when_to_use": "copy files between hosts", "help_excerpt": ""}
        rows = match.rank_rows([rsync, cp], ["copy"], name_toks=["copy"])
        assert rows[0]["name"] == "cp"

    def test_typed_noun_is_a_topic_not_a_name_claim(self):
        # 'directory' is a noun the user typed - it must not claim mkdir, whose
        # real evidence is its prose. Without this, "delete directory" answered
        # mkdir instead of rm/rmdir.
        mkdir = {"name": "mkdir", "oneliner": "make directories",
                 "when_to_use": "create a new folder or directory", "help_excerpt": ""}
        rm = {"name": "rm", "oneliner": "remove directory entries",
              "when_to_use": "delete a file or folder, remove files and directories",
              "help_excerpt": ""}
        rows = match.rank_rows([mkdir, rm], ["delete", "directory"],
                               name_toks=["delete", "directory"])
        assert rows[0]["name"] == "rm"

    def test_name_prefix_is_not_a_name_claim(self):
        """'search' must not claim searchdiagnose by sharing a prefix."""
        diag = {"name": "searchdiagnose", "oneliner": "diagnose search issues",
                "when_to_use": "", "help_excerpt": ""}
        grep = {"name": "grep", "oneliner": "print lines matching a pattern",
                "when_to_use": "search inside files, filter lines", "help_excerpt": ""}
        rows = match.rank_rows([diag, grep], ["search", "files"],
                               name_toks=["search", "files"])
        assert rows[0]["name"] == "grep"

    def test_scoreless_rows_still_rank(self):
        a = {"name": "aaa", "oneliner": "open ports", "when_to_use": "", "help_excerpt": ""}
        b = {"name": "bbb", "oneliner": "unrelated", "when_to_use": "", "help_excerpt": ""}
        rows = match.rank_rows([b, a], ["ports"])
        assert rows[0]["name"] == "aaa"


class TestFindByName:
    def test_exact_only(self, c):
        from howzo.db import upsert
        upsert(c, "jq", "brew", "1.7", "", "json processor")
        c.commit()
        assert match.find_by_name(c, "JQ")["name"] == "jq"
        assert match.find_by_name(c, "qqq") is None
        assert match.find_by_name(c, "  ") is None

    def test_a_prefix_is_not_a_different_tool(self, c):
        # 'search' must not resolve to 'searchdiagnose': this path runs before
        # ranking, so a loose prefix answers with the wrong tool outright
        from howzo.db import upsert
        upsert(c, "searchdiagnose", "system", "", "", "diagnose search issues")
        upsert(c, "portaudio", "brew", "", "", "audio library")
        c.commit()
        assert match.find_by_name(c, "search") is None
        assert match.find_by_name(c, "sea") is None
        assert match.find_by_name(c, "port") is None
        assert match.find_by_name(c, "searchdiagnose")["name"] == "searchdiagnose"

    def test_versioned_binaries_still_resolve(self, c):
        # build managers install versioned names; typing the base name is right
        from howzo.db import upsert
        upsert(c, "python3.13", "brew", "", "", "python interpreter")
        upsert(c, "findrule5.34", "system", "", "", "File::Find::Rule wrapper")
        c.commit()
        assert match.find_by_name(c, "python")["name"] == "python3.13"
        assert match.find_by_name(c, "findrule")["name"] == "findrule5.34"
        assert match.find_by_name(c, "python3.14") is None

    def test_windows_exe_suffix(self, c, monkeypatch):
        # Windows indexes store .exe-suffixed names; a bare name must find them
        from howzo.db import upsert
        upsert(c, "python.exe", "script", "", "C:/Python/python.exe", "python interpreter")
        c.commit()
        monkeypatch.setattr(match.os, "name", "nt")
        assert match.find_by_name(c, "python")["name"] == "python.exe"
        assert match.find_by_name(c, "python.exe")["name"] == "python.exe"
        assert match.find_by_name(c, "pythonx") is None

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
        search, fts, resolved, typed = match.expand_tokens(c, match.query_tokens("find macthing occurence in fike"))
        assert "matching" in search and "file" in search and "occurrence" in search
        assert set(fts) <= set(search)
        assert resolved == ["find", "matching", "occurrence", "file"]
        # a corrected typo is still the user's word: it may earn the name tier
        assert {"matching", "occurrence", "file"} <= set(typed)

    def test_exact_tokens_untouched(self, c):
        from howzo.db import upsert
        upsert(c, "kill", "system", "", "", "terminate or signal a process")
        c.commit()
        search, fts, resolved, typed = match.expand_tokens(c, match.query_tokens("kill a process"))
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
        search, fts, resolved, typed = match.expand_tokens(c, ["fike"])
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
        search, fts, *_ = match.expand_tokens(c, ["file", "pattern"])
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
        search, fts, *_ = match.expand_tokens(c, ["file", "word"])
        assert search == ["file", "word"]
        assert fts == ["file"]  # both in 4/6 docs; tie broken alphabetically


class TestFragmentWord:
    """A rare 3-char word resolves to the word the manuals spell out."""

    @staticmethod
    def _corpus(c, words_per_doc):
        from howzo.db import upsert
        for i, text in enumerate(words_per_doc):
            upsert(c, "tool%d" % i, "system", "", "", text)
        c.commit()

    def test_rare_fragment_resolves(self, c):
        # 'mem' in 0 docs, 'memory' in 6: the user means memory
        self._corpus(c, ["memory %d" % i for i in range(6)])
        search, _fts, resolved, typed = match.expand_tokens(c, ["mem"])
        assert "memory" in search
        assert resolved == ["memory"]
        # inferred, so it searches but cannot claim a tool's name
        assert typed == ["mem"]

    def test_one_edit_from_the_word_is_a_typo_not_an_abbreviation(self, c):
        # 'fin' is one edit from 'find', so it is find misspelled and earns
        # the name tier; 'mem' -> 'memory' is three edits away, an inference
        self._corpus(c, ["find %d" % i for i in range(6)])
        search, _fts, resolved, typed = match.expand_tokens(c, ["fin"])
        assert resolved == ["find"]
        assert "find" in search and "find" in typed

    def test_common_word_never_resolves(self, c):
        # 'add' (6 docs) is a real word, not a fragment of 'address' (6):
        # expanding it made arp outrank alias for "add alias"
        self._corpus(c, ["add address %d" % i for i in range(6)])
        search, _fts, resolved, _typed = match.expand_tokens(c, ["add"])
        assert search == ["add"]
        assert resolved == ["add"]

    def test_family_word_must_be_common(self, c):
        # a tool *name* that merely starts with the fragment is not a word
        # the manuals use: 'img' must not expand to 'imgdir'
        self._corpus(c, ["imgdir %d" % i for i in range(2)])
        search, _fts, resolved, _typed = match.expand_tokens(c, ["img"])
        assert search == ["img"]

    def test_four_char_fragments_untouched(self, c):
        # len >= 4 already prefix-matches prose, so nothing to resolve
        self._corpus(c, ["memory %d" % i for i in range(6)])
        search, _fts, _resolved, _typed = match.expand_tokens(c, ["memo"])
        assert search == ["memo"]

    def test_query_keeps_the_fragment_too(self, c):
        # both forms are searched: the fragment may be literal in some row
        self._corpus(c, ["memory %d" % i for i in range(6)]
                        + ["unrelated %d" % i for i in range(6)])
        search, fts, _resolved, _typed = match.expand_tokens(c, ["mem", "usage"])
        assert search == ["mem", "usage", "memory"]
        assert "memory" in fts


class TestConfusableInvariant:
    """Short tokens never reach names they are a prefix of."""

    def test_three_char_token_only_matches_exact_words(self):
        assert match.has_word("pdftohtml converts to html", "pdf") is False
        assert match.has_word("convert a pdf", "pdf") is True

    def test_kill_never_matches_skill(self):
        assert match.has_word("manage skills", "kill") is False
