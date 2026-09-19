import sys

from howzo.proc import run, which_cmd


def test_run_captures_stdout():
    out = run([sys.executable, "-c", "print('hello howzo')"])
    assert out.strip() == "hello howzo"


def test_run_missing_command_returns_empty():
    assert run(["definitely-not-a-real-command-xyz"]) == ""


def test_run_empty_stdout_returns_empty_string():
    out = run([sys.executable, "-c", "pass"])
    assert out == ""


def test_run_never_raises_on_bad_args():
    assert run([sys.executable, "-c", "import sys; sys.exit(3)"]) == ""


def test_which_cmd_returns_name_when_missing():
    assert which_cmd("definitely-not-a-real-command-xyz") == "definitely-not-a-real-command-xyz"


def test_which_cmd_resolves_real_command():
    assert which_cmd(sys.executable) == sys.executable
