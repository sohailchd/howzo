"""howzo command-line entry point."""
import sqlite3
import sys

from . import commands
from .config import db_path
from .mcp import cmd_mcp

USAGE = """howzo - knows your machine. Ask "how do I X" in English; get the installed tool + command.

Commands:
  howzo <query>          just type your question (same as ask)
  howzo scan [--deep]    rebuild inventory (brew/npm/pipx/uv/scripts/system). --deep also captures --help
  howzo ask "query"
  howzo whatis <tool>
  howzo deep <tool>      capture --help for one tool
  howzo add <name> "desc"  register a tool the scanner can't see (internal CLIs, npx aliases)
  howzo list [--source S]
  howzo mcp              run as a stdio MCP server (exposes howzo_ask / howzo_whatis / howzo_list)
  howzo db               show database path
  howzo --version        show howzo version
  howzo --help           show this help

Stdlib only, zero models, fully local. Works on macOS, Linux, and Windows."""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(USAGE)
        return 1
    if args[0] in ("--version", "-V"):
        from . import __version__
        print(f"howzo {__version__}")
        return 0
    if args[0] in ("--help", "-h"):
        print(USAGE)
        return 0
    cmd, rest = args[0], args[1:]
    try:
        if cmd == "scan":
            return commands.cmd_scan(rest)
        if cmd == "ask":
            return commands.cmd_ask(rest)
        if cmd == "whatis":
            return commands.cmd_whatis(rest)
        if cmd == "deep":
            return commands.cmd_deep(rest)
        if cmd == "add":
            return commands.cmd_add(rest)
        if cmd == "list" and (not rest or rest[0].startswith("-")):
            return commands.cmd_list(rest)
        if cmd == "mcp":
            return cmd_mcp(rest)
        if cmd == "db":
            print(db_path())
            return 0
    except sqlite3.DatabaseError as e:
        msg = str(e).lower()
        if "locked" in msg or "busy" in msg:
            print("howzo: database is busy (another howzo is running?); retry in a few seconds",
                  file=sys.stderr)
        else:
            print(f"howzo: database error: {e}", file=sys.stderr)
        return 1
    # implicit ask: howzo <query> == howzo ask <query>
    return commands.cmd_ask(args)
