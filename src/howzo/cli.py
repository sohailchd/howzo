"""howzo command-line entry point."""
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

Stdlib only, zero models, fully local. Works on macOS, Linux, and Windows."""


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(USAGE)
        return 1
    cmd, rest = args[0], args[1:]
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
    # implicit ask: howzo <query> == howzo ask <query>
    return commands.cmd_ask(args)
