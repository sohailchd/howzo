from howzo import helptext


def test_parse_man_name_section():
    out = """NAME
       grep - print lines matching a pattern
       grep [OPTION]... PATTERNS [FILE]...

SYNOPSIS
       grep pattern file
"""
    oneliner, excerpt = helptext._parse_man(out)
    assert oneliner == "print lines matching a pattern"
    assert excerpt.startswith("NAME")
    assert "SYNOPSIS" in excerpt


def test_parse_man_strips_underline_escapes():
    # macOS man(1) emits underlined text as char+backspace+char (NAME -> N\x08N A\x08A ...)
    out = "NAME\n   N\x08NA\x08AM\x08ME\x08E - look up the NAME section\n"
    oneliner, excerpt = helptext._parse_man(out)
    assert oneliner == "look up the NAME section"
    assert "NAME - look up" in excerpt
    assert "\x08" not in excerpt


def test_parse_man_en_dash_delimiter():
    # macOS man uses an en dash in NAME sections: "name – description"
    out = "NAME\n   ifconfig – configure network interface drivers\n"
    oneliner, excerpt = helptext._parse_man(out)
    assert oneliner == "configure network interface drivers"


def test_parse_man_stray_backspace():
    oneliner, excerpt = helptext._parse_man("NAME\n   to\x08ol - does things\n")
    assert oneliner == "does things"
    assert "\x08" not in excerpt


def test_parse_man_no_name_section():
    oneliner, excerpt = helptext._parse_man("just some\nrandom text")
    assert oneliner == ""
    assert excerpt == "just some\nrandom text"


def test_parse_man_empty():
    assert helptext._parse_man("   ") == ("", "")


def test_man_oneliner_missing_tool():
    assert helptext.man_oneliner("definitely-not-a-real-command-xyz") == ("", "")


def test_capture_help_runs_script(tmp_path):
    script = tmp_path / "tool"
    script.write_text("#!/bin/sh\necho 'this is a long enough help text to pass the sixty char threshold'\n")
    script.chmod(0o755)
    out = helptext.capture_help("tool", str(script))
    assert out is not None and "sixty char" in out


def test_capture_help_missing_binary():
    assert helptext.capture_help("definitely-not-a-real-command-xyz") is None
