from howzo.render import best_help_lines, render_tool


def make_row(**kw):
    base = {"id": 1, "name": "jq", "source": "brew", "version": "1.7", "path": "",
            "oneliner": "commandline JSON processor", "when_to_use": "",
            "help_excerpt": "", "help_captured_at": None, "scanned_at": "2026-01-01"}
    base.update(kw)
    return base


def test_render_tool_basic():
    out = render_tool(make_row())
    assert out.startswith("jq  (brew, 1.7)")
    assert "commandline JSON processor" in out


def test_render_tool_no_version():
    out = render_tool(make_row(version=""))
    assert "jq  (brew)" in out


def test_render_tool_shows_when_to_use():
    out = render_tool(make_row(when_to_use="when you need json"))
    assert "when: when you need json" in out


def test_render_tool_shows_help_lines_when_query_given():
    row = make_row(help_excerpt="Usage: jq [OPTIONS] <jq filter>\n  -r raw output\n  --help show help")
    out = render_tool(row, q="raw output")
    assert "| -r raw output" in out


def test_render_tool_no_help_lines_without_query():
    row = make_row(help_excerpt="  -r raw output")
    out = render_tool(row)
    assert "|" not in out


def test_best_help_lines_empty_when_no_tokens():
    assert best_help_lines("anything at all", "a") == []


def test_best_help_lines_prefers_matching_lines():
    text = "first line with no keywords\n    --port PORT port to bind\n    --host HOST host to bind"
    lines = best_help_lines(text, "port", n=2)
    assert lines
    assert any("port" in l for l in lines)
    assert len(lines) <= 2
