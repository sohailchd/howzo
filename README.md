# howzo

**Knows your machine.** Ask "how do I X" in English → get the tool that is actually installed on *this* machine, plus a runnable command.

howzo is a free, local, **zero-model** command router. It indexes the tools that are actually installed on your box — brew, npm, pipx, uv, system binaries, your own scripts — and answers plain-English questions by matching against that inventory. No accounts, no API keys, no telemetry, and no network access when answering.

## Why

Generic command helpers (ShellGPT, mang.sh, Atuin) index a static corpus of popular commands. howzo indexes *your machine* instead — the exact tools, versions, and help text you actually have. If it's installed, howzo knows it; if it isn't, howzo doesn't waste your time suggesting it.

## Install

Requires Python 3.9+. Runtime dependencies: **none** (stdlib only).

### macOS / Linux

```sh
pipx install howzo        # or: uv tool install howzo
```

macOS also has a Homebrew formula (tap required):

```sh
brew tap sohailchd/howzo && brew install howzo
```

### Windows

```powershell
py -m pipx install howzo  # or: uv tool install howzo
```

> On Windows tools are indexed by name from `PATH` (plus package metadata
> and `--help` capture) — there is no `man`, so descriptions are thinner
> than on macOS/Linux.

### From source

```sh
git clone https://github.com/sohailchd/howzo.git
pipx install --editable howzo    # or: uv tool install --editable howzo
```

### First run

```sh
howzo scan     # one-time: build your machine's inventory (~2 min)
```

Rescans are safe: captured help text, `when_to_use` notes, custom entries, and mined npx packages are preserved. Man pages are cached per binary revision (path + mtime), so a rescan only re-fetches what changed — seconds of work instead of re-reading 1,500 man pages.

## Usage

```console
$ howzo "how do I rotate a pdf"
pdfq  (pipx, 1.0)
  rotate and convert pdf files

$ howzo whatis crwl
crwl  (pipx, 0.3.1)
  (binary of pipx crawl4ai)

$ howzo kill a process on port 8080
lsof  (brew, 9.9)
  list open files and network connections
```

### Commands

| Command | What it does |
|---|---|
| `howzo <query>` | Ask in plain English (implicit `ask`) |
| `howzo scan [--deep]` | Rebuild inventory; `--deep` also captures `--help` text for every tool |
| `howzo ask "query"` | Same as `<query>` |
| `howzo whatis <tool>` | Reverse lookup: what is this tool for? |
| `howzo deep <tool>` | Capture `--help`/man for one tool on demand |
| `howzo add <name> "desc"` | Register a tool the scanner can't see (internal CLIs, aliases) |
| `howzo list [--source S]` | Browse the inventory |
| `howzo mcp` | Run as a stdio MCP server |
| `howzo db` | Show the database path |

## What it indexes

| Source | What's indexed |
|---|---|
| brew | formulae + versions + descriptions (`brew info`) |
| npm | global packages + their installed binaries |
| pipx | packages + the binaries they provide (e.g. `crwl` → crawl4ai) |
| uv | `uv tool` installs |
| scripts | executables in `~/bin` and `~/.local/bin` (one-liner from the script header) |
| system (Unix) | `/usr/bin` + `/usr/sbin` + `/usr/local/bin` binaries, described via man pages |
| path (Windows) | executables found on `PATH` (System32, Program Files, …) |
| npx | `npx`/`bunx`/`pnpm dlx` packages mined from your shell history (zsh, bash, PowerShell) |
| custom | anything you add with `howzo add` |
| seed | ~230 curated top commands for macOS / Linux / Windows (incl. PowerShell cmdlets), bundled with howzo — so the classic tools are answerable on day one, on every platform |

A typical machine indexes ~1,500 tools. Seed rows are reference entries for tools that aren't installed *here*; they render distinctly — `mv  (seed, windows)` — and are ranked below your machine's own tools.

## How it works

- **SQLite + FTS5** at `~/.local/share/howzo/howzo.db` (Windows: `%LOCALAPPDATA%\howzo`), one row per tool: name, source, version, oneliner, when-to-use, help excerpt.
- **Match = BM25 + word-boundary token-coverage re-rank** in Python, tiered by field (name > when-to-use > oneliner > man excerpt). Short words resolve to the ones the manuals use: a 3-letter word that is much rarer in your index than the word it starts expands to that word (`mem` → memory, `dir` → directory, `man` → manual), and a tiny synonym map covers names that share no spelling (`ram` → memory). Typos are corrected with Damerau-Levenshtein against the index vocabulary. No models, no embeddings — `kill` never matches `skill`, `port` never matches `report`, `pdf` never matches `pdftohtml`.
- **Curated seed layer**: man pages under-describe what tools are *for* (`cat`'s page says "concatenate files", so "content of the file" could never reach it). howzo bundles ~230 hand-written "when to use" entries for the top macOS/Linux/Windows commands and merges them in at scan time — filling gaps only, never overwriting your machine's real data.
- **~20–30 MB RAM**, and answering is fully offline. The network is only touched while scanning, to fetch package descriptions from npm/PyPI.
- Set `HOWZO_DB` to a directory or to a full path to relocate the database (the test suite points it at a temp file).

## MCP

howzo runs as a stdio MCP server exposing `howzo_ask`, `howzo_whatis`, and `howzo_list`:

```json
{
  "mcpServers": {
    "howzo": { "command": "howzo", "args": ["mcp"] }
  }
}
```

## Development

```sh
git clone https://github.com/sohailchd/howzo.git && cd howzo
uv venv .venv
VIRTUAL_ENV=$PWD/.venv uv pip install -e ".[dev]"   # or: pip install -e ".[dev]"
pytest
```

Layout:

```
src/howzo/
├── cli.py        # entry point + dispatch
├── commands.py   # scan / ask / whatis / deep / add / list
├── config.py     # platform constants, DB path (HOWZO_DB override)
├── proc.py       # subprocess helpers (cross-platform)
├── db.py         # SQLite + FTS5 schema, upsert
├── match.py      # tokenization, FTS query, BM25 + coverage re-rank
├── seed.py       # curated cross-platform command knowledge base
├── render.py     # output formatting
├── helptext.py   # man pages, --help capture
├── mcp.py        # MCP stdio server
└── scan/         # one module per source: brew, npm, pipx, uv, scripts, system, path, npx
tests/            # pytest suite (runs against temp DBs, no network)
```

## License

MIT — see [LICENSE](LICENSE).
