"""Labeled recall eval: canonical queries against a fixture corpus.

Guards the matching pipeline end-to-end (tokenize -> typo correction ->
FTS window -> field-tier ranking -> render): changing weights, matcher
logic, or hints must not regress these recall expectations. The corpus
uses real man-page oneliners and production hints are applied via
apply_hints, exactly like a real scan. Top-1 is asserted only where the
intent is unambiguous; otherwise membership in the top-3.
"""
import re

import pytest

from howzo import hints
from howzo.commands import cmd_ask
from howzo.db import upsert

CORPUS = [
    # network (ifconfig et al. get production hints)
    ("ifconfig", "configure network interface parameters"),
    ("ip", "show ip addresses and interfaces (Linux)"),
    ("arp", "manipulate ARP tables"),
    ("netstat", "report on network connections"),
    ("route", "manipulate network routing tables"),
    # text
    ("grep", "print lines that match a pattern"),
    ("awk", "pattern-directed language"),
    ("sed", "stream editor"),
    ("find", "walk a file hierarchy"),
    # disk
    ("df", "display free disk space"),
    ("du", "display disk usage statistics"),
    # processes
    ("ps", "process status"),
    ("top", "display sorted information about processes"),
    ("kill", "terminate or signal a process"),
    ("killall", "kill all processes that match a specification"),
    # images / archives
    ("sips", "scriptable image processing system"),
    ("zip", "package and compress (archive) files"),
    ("gzip", "compression/decompression tool using Lempel-Ziv"),
    ("tar", "manipulate tape archives"),
    # files
    ("ls", "list directory contents"),
    ("cat", "concatenate files and print"),
    ("head", "output the first part of files"),
    ("tail", "output the last part of files"),
    ("sort", "sort, check and compare lines"),
    ("uniq", "report or omit repeated lines"),
    ("wc", "print line, word, and byte counts"),
    ("cut", "select and print any part of lines"),
    ("xargs", "execute utility with arguments built from standard input"),
    # misc
    ("jq", "command-line JSON processor"),
    ("curl", "transfer a URL"),
    ("ssh", "OpenSSH remote login client"),
    ("git", "control version control"),
    ("which", "locate a command"),
    ("man", "an interface to the reference manual"),
    # extra vocabulary so typo corrections have targets (like live man text
    # does — a small corpus would otherwise correct nothing)
    ("mdfind", "finds files matching a given query"),
    ("findrule", "command line wrapper to File::Find::Rule"),
    ("opensnoop", "snoop file opens as they occur"),
]

# man excerpts for a few tools, mirroring what a real scan indexes for
# system tools (the excerpt tier is where 'sed'-style intent lives)
EXCERPTS = {
    "grep": "grep - print lines that match a pattern\n  grep [OPTIONS] PATTERN [FILE ...]\n  "
            "print selected lines from a file, first occurrence of a match",
    "sed": "sed - stream editor\n  sed [-f script-file] [script] [input ...]\n  "
           "edit each line according to a script, using the pattern space",
}

# (query, expected_top1 or None, tools that must appear in the top-3)
CASES = [
    # ifconfig (macOS) and ip (Linux) are both right answers; the fixture
    # carries both, and they tie — assert membership, not order
    ("how to find ip address", None, {"ifconfig", "ip"}),
    ("kill a process", "kill", {"kill"}),
    ("how to check disk space", "df", {"df"}),
    ("how to list running processes", "ps", {"ps", "top"}),
    ("how to convert an image to pdf", "sips", {"sips"}),
    # NOTE: "how to compress a file" is deliberately not a guard case: the
    # intent is ambiguous (zip vs gzip vs tar) and in this small corpus the
    # word 'file' still discriminates (live it sits in >50% of rows and
    # cancels out), so the ranking here doesn't track the real corpus.
    ("find macthing occurence in fike", None, {"grep", "find"}),
    ("how to view a json file", None, {"jq"}),
    ("how to download a file", "curl", {"curl"}),
    ("how to see the first lines of a file", "head", {"head"}),
    ("how to count lines in a file", "wc", {"wc"}),
    # sed's intent words live only in its man page and it trails the curated
    # hints in a small corpus; grep's top-1 is the stable guard
    ("how to filter lines with a pattern", "grep", {"grep"}),
    ("how to connect to a remote server", "ssh", {"ssh"}),
    ("how to archive a folder", None, {"tar", "zip"}),
]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """A scan-like fixture index: real oneliners + production hints."""
    from howzo.db import db
    mp = pytest.MonkeyPatch()  # module scope can't use function-scoped monkeypatch
    mp.setenv("HOWZO_DB", str(tmp_path_factory.mktemp("eval") / "howzo.db"))
    c = db()
    for name, one in CORPUS:
        upsert(c, name, "system", "", "", one)
    for name, excerpt in EXCERPTS.items():
        c.execute("UPDATE tools SET help_excerpt=? WHERE name=?", (excerpt, name))
    hints.apply_hints(c)
    c.commit()
    yield c
    c.close()
    mp.undo()


def _ask_tools(c, capsys, query):
    assert cmd_ask(query.split()) == 0, f"cmd_ask failed for: {query}"
    out = capsys.readouterr().out
    return re.findall(r"^(\S+)\s+\(\w+\)$", out, re.M)[:3]


@pytest.mark.parametrize("query, top1, in_top3", CASES)
def test_recall(corpus, capsys, query, top1, in_top3):
    names = _ask_tools(corpus, capsys, query)
    assert names, f"no results for: {query}"
    for t in in_top3:
        assert t in names, f"{t!r} not in top-{len(names)} for {query!r} -> {names}"
    if top1:
        assert names[0] == top1, f"top1 for {query!r} is {names[0]!r}, expected {top1!r}"
