"""Bundled seed: what it inserts, what it must never clobber, how it ranks."""
from howzo import seed
from howzo.db import upsert
from howzo.match import find_by_name, rank_rows
from howzo.render import render_tool


def test_seed_is_well_formed_and_covers_the_core_tools():
    names = [e[0] for e in seed.SEED]
    assert len(names) == len(set(names)), "duplicate seed name"
    assert 200 <= len(seed.SEED) <= 260
    for required in ("cat", "grep", "jq", "tar", "docker", "ipconfig", "Get-ChildItem"):
        assert seed.entry(required) is not None, required
    for name, platform, oneliner, when in seed.SEED:
        assert platform in ("all", "macos", "linux", "windows"), name
        assert oneliner and when, name
        assert len(when.split()) >= 4, name


def test_missing_tool_is_inserted_as_a_seed_row(c):
    seed.apply_seed(c, platform="macos")
    row = c.execute("SELECT * FROM tools WHERE name='cat'").fetchone()
    assert row["source"] == "seed"
    assert row["platform"] == "all"
    assert row["oneliner"] == seed.entry("cat")[2]
    assert row["when_to_use"] == seed.entry("cat")[3]
    assert row["path"] == "" and row["version"] == ""


def test_every_platform_is_indexed(c):
    # a macOS user may still look up a Windows-only command: the row exists,
    # tagged with the platform it belongs to
    seed.apply_seed(c, platform="macos")
    by_name = {r["name"]: r["platform"] for r in c.execute("SELECT name, platform FROM tools")}
    assert by_name["Get-ChildItem"] == "windows"
    assert by_name["apt"] == "linux"
    assert by_name["sips"] == "macos"
    assert by_name["ls"] == "all"


def test_local_row_wins_and_is_never_clobbered(c):
    upsert(c, "cat", "system", "", "/bin/cat", "concatenate files")
    c.execute("UPDATE tools SET when_to_use='user says so' WHERE name='cat'")
    c.commit()
    seed.apply_seed(c, platform="macos")
    assert c.execute("SELECT COUNT(*) FROM tools WHERE name='cat'").fetchone()[0] == 1
    row = c.execute("SELECT * FROM tools WHERE name='cat'").fetchone()
    assert row["source"] == "system"
    assert row["platform"] is None            # a local row is not a seed row
    assert row["path"] == "/bin/cat"
    assert row["oneliner"] == "concatenate files"
    assert row["when_to_use"] == "user says so"
    assert find_by_name(c, "cat")["source"] == "system"


def test_seed_fills_only_empty_local_fields(c):
    upsert(c, "mv", "system", "", "/bin/mv", "")
    c.commit()
    seed.apply_seed(c, platform="macos")
    row = c.execute("SELECT * FROM tools WHERE name='mv'").fetchone()
    assert row["source"] == "system"          # never relabelled as seed
    assert row["oneliner"] == seed.entry("mv")[2]
    assert row["when_to_use"] == seed.entry("mv")[3]


def test_foreign_platform_entry_does_not_fill_a_local_row(c):
    # macOS has its own low-level /usr/sbin/ipconfig; the Windows hint must
    # not be applied to it (it would pull the wrong tool up for "my ip")
    upsert(c, "ipconfig", "system", "", "/usr/sbin/ipconfig",
           "view and control IP configuration state")
    c.commit()
    seed.apply_seed(c, platform="macos")
    assert c.execute("SELECT when_to_use FROM tools WHERE name='ipconfig'").fetchone()[0] == ""
    seed.apply_seed(c, platform="windows")
    assert c.execute("SELECT when_to_use FROM tools WHERE name='ipconfig'"
                     ).fetchone()[0] == seed.entry("ipconfig")[3]


def test_platform_penalty_prefers_the_native_tool(c):
    seed.apply_seed(c, platform="macos")
    rows = c.execute("SELECT * FROM tools WHERE name IN ('mv','rename')").fetchall()
    toks = ["rename", "file"]
    assert [r["name"] for r in rank_rows(rows, toks, platform="macos")] == ["mv", "rename"]
    # on Windows the same rows flip: the native cmd builtin wins
    assert [r["name"] for r in rank_rows(rows, toks, platform="windows")] == ["rename", "mv"]


def test_platform_penalty_ignores_all_and_missing_platforms(c):
    seed.apply_seed(c, platform="macos")
    rows = c.execute("SELECT * FROM tools WHERE name IN ('mv','apt')").fetchall()
    # 'all' (mv) is native everywhere; a foreign row (apt) is halved but still
    # present — never removed from the result set
    ranked = rank_rows(rows, ["move", "file"], platform="macos")
    assert {r["name"] for r in ranked} == {"mv", "apt"}
    assert ranked[0]["name"] == "mv"


def test_seed_rows_render_distinctly(c):
    seed.apply_seed(c, platform="macos")
    row = c.execute("SELECT * FROM tools WHERE name='type'").fetchone()
    assert render_tool(row).startswith("type  (seed, windows)")
    local = c.execute("SELECT * FROM tools WHERE name='ip'").fetchone()
    assert render_tool(local).startswith("ip  (seed, linux)")
    upsert(c, "jq", "brew", "1.7", "", "commandline JSON processor")
    c.commit()
    installed = c.execute("SELECT * FROM tools WHERE name='jq'").fetchone()
    assert render_tool(installed).startswith("jq  (brew, 1.7)")


def test_foreign_row_never_outranks_native_even_with_name_hit(c):
    # regression (0.3.0 review): 'how do I see my ip' on macOS returned the
    # linux seed row 'ip' before ifconfig — an exact name hit (tier 3.0)
    # survived any multiplicative penalty. Platform must be a primary sort
    # key: every native row sorts ahead of every foreign row.
    seed.apply_seed(c, platform="macos")
    rows = c.execute("SELECT * FROM tools WHERE name IN ('ifconfig', 'ip')").fetchall()
    ranked = rank_rows(rows, ["see", "ip"], platform="macos")
    assert [r["name"] for r in ranked] == ["ifconfig", "ip"]


def test_upsert_clears_stale_seed_platform(c):
    # regression (0.3.0 review): seed inserts 'convert (seed, linux)'; when
    # the user later brews ImageMagick the upsert must strip the foreign tag,
    # or the locally installed tool is ranked as foreign forever.
    from howzo.db import upsert
    seed.apply_seed(c, platform="macos")
    upsert(c, "convert", "brew", "7", "/opt/homebrew/bin/convert", "convert between image formats")
    row = c.execute("SELECT * FROM tools WHERE name='convert'").fetchone()
    assert row["source"] == "brew"
    assert (row["platform"] or "") == ""
    # apply_seed's local branch also self-heals a row that got tagged
    c.execute("UPDATE tools SET platform='linux' WHERE name='convert'")
    c.commit()
    seed.apply_seed(c, platform="macos")
    row = c.execute("SELECT platform FROM tools WHERE name='convert'").fetchone()
    assert (row[0] or "") == ""
