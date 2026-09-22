"""Intent benchmark: the measurement contract for matching work.

Why this exists: every matching fix so far was verified by ad-hoc batteries, so
the same class of miss kept returning in a new shape. Here the judgments are
explicit and independent, because one "accept" set cannot express "htop must be
there AND du must not":

  ok_top1     any of these is a correct first answer — several are normal
              ('wget' for 'curl' is not a regression)
  need_topk   must appear in the top 3
  need_any_topk  at least one of these must appear in the top 3 (the intent is
              served by a family of tools; asserting one blessed name would test
              the author's taste, not the product)
  forbid_topk must NOT appear in the top 3; every entry cites an observed miss
  category    so an aggregate score cannot mask a category going backwards

A case that today's code cannot satisfy carries ``expected_fail`` with the
defect it records: it is counted on the scoreboard, it must not violate a
``forbid_topk`` silently, and it is expected to flip to passing when the
milestone that fixes it lands (see docs/design/matching-rebuild.md).

The fixture is the production seed (the same curated data a real scan merges)
plus deliberate distractors — a name that merely prefixes a common query word
(``searchdiagnose`` for "search"), a class that has burned us twice.

Run the scoreboard:  uv run pytest tests/test_benchmark.py -q -s
"""
import json
import os
import re

import pytest

from howzo import seed
from howzo.commands import cmd_ask
from howzo.db import upsert

# Distractors: present so the name-prefix hazard is measured, not discovered.
# 'searchdiagnose' shares a prefix with the word "search", 'findrule' with
# "find" — both are real macOS tools that have stolen answers before.
DISTRACTORS = [
    ("searchdiagnose", "system", "diagnose search issues"),
    ("findrule", "system", "command line wrapper to File::Find::Rule"),
    ("DirectoryService", "system", "macOS directory services command"),
    ("cvaffinity", "system", "manage affinity settings on a filesystem"),
    ("ioalloccount", "system", "summarize IOKit memory usage"),
    ("portaudio", "brew", "portable cross-platform audio library"),
]


class Case:
    """One canonical question and what a competent sysadmin expects."""

    def __init__(self, query, category, ok_top1=(), need_topk=(), need_any_topk=(),
                 forbid_topk=(), expected_fail=None, note=""):
        self.query = query
        self.category = category
        self.ok_top1 = set(ok_top1)
        self.need_topk = set(need_topk)
        self.need_any_topk = set(need_any_topk)
        self.forbid_topk = set(forbid_topk)
        self.expected_fail = expected_fail
        self.note = note

    @property
    def id(self):
        return self.query


CASES = [
    # ---- memory / cpu (the reported class) ------------------------------
    Case("cpu usage", "processes", ok_top1={"top", "ps", "htop"},
         need_any_topk={"top", "ps", "htop"}, forbid_topk={"du", "iftop"},
         note="the miss that started this rebuild: du repeated a generic word across three fields and won"),
    Case("mem usage", "memory", ok_top1={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         need_any_topk={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         forbid_topk={"du", "iftop", "df"},
         note="the requirement is a memory tool, not one blessed name; the report that started this was du winning"),
    Case("ram usage", "memory", ok_top1={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         need_any_topk={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         forbid_topk={"du", "df", "iftop"}),
    Case("memory usage", "memory", ok_top1={"top", "ps", "memory_pressure", "htop", "vm_stat"},
         need_any_topk={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         forbid_topk={"du", "iftop", "df"}),
    Case("how to check memory usage", "memory",
         ok_top1={"top", "ps", "memory_pressure", "htop", "vm_stat"},
         need_any_topk={"top", "ps", "memory_pressure", "htop", "vm_stat"},
         forbid_topk={"du"},
         note="names a family, not one tool: top, ps, htop and memory_pressure all report "
              "memory, and once the pack described more of them they traded places on bm25. "
              "Requiring one specific viewer would test vocabulary, not correctness"),
    Case("how to check cpu temperature", "system-info", ok_top1={"pmset", "sensors"},
         need_any_topk={"pmset", "sensors"}, forbid_topk={"shasum", "checkgid", "checkuser"},
         note="was answers shasum/checkgid: 'check' and 'cpu' matched obscure tool names first. "
              "The expectation was also wrong: it used to require 'top', but a process viewer "
              "reports utilisation, not temperature. The tools that do are pmset on macOS and "
              "sensors on Linux, so the case now asserts one of those instead"),

    # ---- disk ------------------------------------------------------------
    Case("disk usage", "disk", ok_top1={"du", "df"}, need_topk={"du"}),
    Case("how to check disk space", "disk", ok_top1={"df", "du"}, need_topk={"df"}),
    Case("how much disk space is left", "disk", ok_top1={"df"}, need_topk={"df"}),
    Case("how to see disk usage by folder", "disk", ok_top1={"du"}, need_topk={"du"}),

    # ---- files and text --------------------------------------------------
    Case("list files", "files", ok_top1={"ls"}, need_topk={"ls"}),
    Case("list files in a directory", "files", ok_top1={"ls"}, need_topk={"ls"}),
    Case("dir contents", "files", ok_top1={"ls"}, need_topk={"ls"}),
    Case("copy file to folder", "files", ok_top1={"cp"}, need_topk={"cp"}),
    Case("rename a file", "files", ok_top1={"mv"}, need_topk={"mv"}),
    Case("delete a file", "files", ok_top1={"rm"}, need_topk={"rm"}),
    Case("content of the file", "files", ok_top1={"cat"}, need_topk={"cat"}),
    Case("how to count lines in a file", "text", ok_top1={"wc"}, need_topk={"wc"}),
    Case("how to see the first lines of a file", "text", ok_top1={"head"}, need_topk={"head"}),
    Case("how to sort a file", "text", ok_top1={"sort"}, need_topk={"sort"}),
    Case("how to search inside files", "search", ok_top1={"grep", "rg", "ack"},
         need_topk={"grep"}, forbid_topk={"searchdiagnose", "mdfind"},
         note="was a known miss: 'find' won because grep's intent text never said "
              "'inside'. It says it now, and 'match' stayed in the sentence - dropping "
              "that word was what pushed grep out of 'find macthing occurence in fike'. "
              "mdfind is forbidden because Spotlight answers by index, not by reading "
              "the file the way grep does"),

    # ---- name eligibility (a typed noun is not a name claim) -------------
    Case("delete directory", "files", ok_top1={"rm", "rmdir"}, need_topk={"rmdir"},
         forbid_topk={"mkdir"}),
    Case("list directory", "files", ok_top1={"ls"}, need_topk={"ls"}),
    Case("make directory", "files", ok_top1={"mkdir"}, need_topk={"mkdir"},
         note="was a known miss: the tool 'make' took the name tier on the query's verb. "
              "mkdir's intent now carries 'make' too, so it matches both concepts and "
              "outranks the name claim - no scorer change was needed"),
    Case("create a directory", "files", ok_top1={"mkdir"}, need_topk={"mkdir"},
         note="passes: no tool is named 'create', so the verb cannot steal the tier"),
    Case("directory creation", "files", ok_top1={"mkdir"}, need_topk={"mkdir"},
         note="the same intent under a noun: 'creation' has to reach mkdir's 'create a new "
              "folder or directory' through the suffix, not the prefix"),

    # ---- the front door: a bare word must not resolve by prefix ----------
    Case("search", "search", ok_top1={"grep", "rg", "find"}, forbid_topk={"searchdiagnose"}),
    Case("port", "ports", ok_top1={"lsof", "netstat", "nc", "ss"}, forbid_topk={"portaudio"}),

    # ---- processes -------------------------------------------------------
    Case("kill a process", "processes", ok_top1={"kill"}, need_topk={"kill"}),
    Case("how to kill a process by name", "processes", ok_top1={"killall", "pkill", "kill"},
         need_topk={"killall", "pkill", "kill"}, forbid_topk={"kill.d", "kill-port"}),
    Case("how to list running processes", "processes", ok_top1={"ps", "top"}, need_topk={"ps"}),

    # ---- network ---------------------------------------------------------
    Case("check internet connection", "network",
         ok_top1={"networkQuality", "ping", "nc", "curl", "dig", "traceroute", "mtr"},
         need_any_topk={"networkQuality", "ping", "nc", "curl", "mtr", "netstat"},
         forbid_topk={"shasum", "md5", "md5sum", "df", "cmp", "uptime", "free"},
         note="reported live: 'check' is a verb every tool's prose uses ('verify an integrity "
              "checksum'), and it dragged in shasum/checkgid. The query's content words are "
              "internet/connection, and rarity weighting is what lets them win"),
    Case("how to see open ports", "ports", ok_top1={"lsof", "netstat", "nc", "ss"},
         need_topk={"lsof", "netstat"}, forbid_topk={"open"},
         note="'open' is a file-opening tool on macOS; 'open ports' is not about it"),
    Case("which port is open", "ports", ok_top1={"lsof", "netstat", "nc", "ss"},
         forbid_topk={"open"},
         note="was a known miss: netstat was already first, and 'open' (the file opener) "
              "took the third slot on the verb. lsof's intent now says 'open ports', so it "
              "matches both concepts and 'open' is gone - a forbid violation, not a "
              "missing correct answer, which is why forbidden answers have their own gate"),
    Case("how to find ip address", "network", ok_top1={"ifconfig", "ip"}, need_topk={"ifconfig"}),

    # ---- reading the machine's own hardware ------------------------------
    # Reported from a Linux box: "find the processor name" answered top, lsof,
    # find - a process viewer, an open-files tool, and a file search - because
    # no entry described reading the chip's identity, so the generic words
    # "find" and "name" decided it. Reproduced identically on macOS.
    Case("find the processor name", "system-info",
         ok_top1={"lscpu", "dmidecode", "lshw", "inxi", "system_profiler", "sysctl"},
         need_any_topk={"lscpu", "dmidecode", "lshw", "inxi", "system_profiler", "sysctl"},
         forbid_topk={"top", "ps", "htop", "lsof", "pgrep"},
         note="the verb 'find' is a tool name and 'processor' was in no entry at all. "
              "The forbid covers the process and file tools that answered it; the file-search "
              "tool itself may still hold the third slot, because only two hardware tools are "
              "native to any one platform and foreign rows sort last"),
    Case("what cpu do i have", "system-info",
         need_any_topk={"lscpu", "dmidecode", "lshw", "inxi", "system_profiler", "sysctl"},
         note="answered top/ps/htop, which mention cpu in their prose and know nothing about "
              "the chip. Only a hardware tool in the top-3 is asserted, not top-1: after "
              "stopwords this query carries ONE concept, so every tool whose text says cpu "
              "scores identically and a long process man page wins the tie. Separating them "
              "needs the phrase layer, which is phase 3 of the research note - on a real "
              "corpus system_profiler lands third, and that is the honest ceiling here"),
    Case("how many cpu cores", "system-info",
         ok_top1={"nproc", "lscpu", "sysctl", "system_profiler", "inxi"},
         need_any_topk={"nproc", "lscpu", "sysctl", "system_profiler"}),
    Case("cpu model", "system-info",
         ok_top1={"lscpu", "dmidecode", "system_profiler", "sysctl", "lshw", "inxi"},
         need_any_topk={"lscpu", "system_profiler", "sysctl", "dmidecode"}),

    # ---- archives / images / env ----------------------------------------
    Case("how to compress a folder", "compression", ok_top1={"zip", "tar", "gzip"}, need_topk={"zip"}),
    Case("how to unzip a file", "compression", ok_top1={"unzip"}, need_topk={"unzip"}),
    Case("how to archive a folder", "archives", ok_top1={"tar", "zip"}, need_topk={"tar"}),
    Case("how to convert an image to pdf", "images", ok_top1={"sips", "convert"}, need_topk={"sips"}),
    Case("show environment variables", "shell", ok_top1={"env", "printenv", "export"}, need_topk={"env"}),
    Case("print without newline", "text", ok_top1={"printf"}, need_topk={"printf"},
         note="reported live: answered npx ('run a node package without installing it') - the "
              "query's subject was print/newline, and 'without' has to stop being a topic"),

    # ---- typos and fragments --------------------------------------------
    Case("fin file", "search", ok_top1={"find"}, need_topk={"find"},
         note="one edit from 'find': a typo of the user's word, not an abbreviation"),
    Case("mem usahe", "memory", ok_top1={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         need_any_topk={"top", "ps", "htop", "memory_pressure", "vm_stat"},
         forbid_topk={"du", "iftop", "df"},
         note="a typo must not change which tools the generic word drags in"),
    Case("find macthing occurence in fike", "search", ok_top1={"find", "grep"},
         need_topk={"find", "grep"},
         note="typos AND a fragment: 'fike' -> file, 'occurence' -> occurrence"),
    Case("how to view a json file", "json", ok_top1={"jq"}, need_topk={"jq"}),
]


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    """A benchmark index: the production seed plus the named distractors."""
    from howzo.db import db
    mp = pytest.MonkeyPatch()
    mp.setenv("HOWZO_DB", str(tmp_path_factory.mktemp("bench") / "howzo.db"))
    c = db()
    for name, source, one in DISTRACTORS:
        upsert(c, name, source, "", "", one)
    seed.apply_seed(c)
    c.commit()
    yield c
    c.close()
    mp.undo()


def _top(capsys, query, k=3):
    assert cmd_ask(query.split()) == 0, "cmd_ask failed for: %s" % query
    out = capsys.readouterr().out
    return [name for name, _tag in re.findall(r"^(\S+)\s+\(([^)]*)\)$", out, re.M)][:k]


def _judge(case, names):
    """None when the case passes, else the reason it failed."""
    # An empty answer is a failure whatever the case asks for. Without this,
    # a case that names only a correct top-1 (no need_topk) passes vacuously
    # when the command prints nothing at all, so "found nothing" and "found the
    # right tool" score the same.
    if not names:
        return "no answer at all"
    if case.ok_top1 and names[0] not in case.ok_top1:
        return "top1 is %r, expected one of %s" % (names[0], sorted(case.ok_top1))
    missing = case.need_topk - set(names)
    if missing:
        return "missing from top-3: %s" % sorted(missing)
    if case.need_any_topk and not (case.need_any_topk & set(names)):
        return "none of %s in top-3" % sorted(case.need_any_topk)
    bad = case.forbid_topk & set(names)
    if bad:
        return "forbidden in top-3: %s" % sorted(bad)
    return None


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_benchmark(bench, capsys, case):
    names = _top(capsys, case.query)
    reason = _judge(case, names)
    if reason and case.expected_fail:
        pytest.xfail("%s [%s]" % (reason, case.expected_fail))
    assert reason is None, "%s -> %s" % (case.query, reason)


def test_scoreboard(bench, capsys):
    """Print the scoreboard and compare it with the recorded baseline.

    The baseline is the contract: a case that passed when the baseline was
    recorded may not quietly start failing (an aggregate score would hide it).
    """
    path = os.path.join(os.path.dirname(__file__), "benchmark_baseline.json")
    with open(path) as fh:
        baseline = json.load(fh)
    assert baseline["cases"] == len(CASES), (
        "the question set changed; re-record the baseline deliberately "
        "(tools/record_baseline.py) and say why in the commit message")
    assert baseline["seed_entries"] == len(seed.SEED)

    failing, passing = [], []
    forbid_violations = []
    for case in CASES:
        names = _top(capsys, case.query)
        reason = _judge(case, names)
        if reason:
            failing.append(case.query)
            if case.forbid_topk & set(names):
                forbid_violations.append(case.query)
        else:
            passing.append(case.query)
    known = {c.query for c in CASES if c.expected_fail}
    print("\nbenchmark: %d/%d passing, %d known misses, %d forbidden answers"
          % (len(passing), len(CASES), len(failing), len(forbid_violations)))
    counts = {}
    for cat in sorted({c.category for c in CASES}):
        total = [c for c in CASES if c.category == cat]
        ok = [c for c in total if c.query in passing]
        counts[cat] = len(ok)
        print("  %-12s %d/%d" % (cat, len(ok), len(total)))

    regressed = [q for q in baseline["passing"] if q in failing]
    assert not regressed, "cases that passed in the baseline now fail: %s" % regressed
    assert set(failing) == known, (
        "known misses changed: now failing %s, recorded %s — fix it or update the "
        "baseline deliberately" % (sorted(set(failing) - known), sorted(known - set(failing))))
    # Gated, not just printed: an aggregate score hides one category going
    # backwards while another improves.
    for cat, was in baseline["categories"].items():
        assert counts.get(cat, 0) >= was, (
            "category %r went backwards: %d/%d passing, %d when the baseline was recorded"
            % (cat, counts.get(cat, 0), len([c for c in CASES if c.category == cat]), was))
    # Forbidden answers get their own gate rather than riding on the top-1
    # check. Two of the three failing cases fail this way - the right tool is
    # already first, and a wrong tool sits at rank three - so a change that
    # keeps the right answer but drags in a wrong one would otherwise pass
    # unnoticed while the known-miss set stayed the same size.
    new_forbidden = sorted(set(forbid_violations) - set(baseline["forbidden_answers"]))
    assert not new_forbidden, (
        "forbidden answers where the baseline had none: %s" % new_forbidden)
