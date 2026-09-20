# ContextSlim AI

**An MCP server that lets an AI compress and save its own working memory.**

Long AI sessions degrade. The model re-reads the entire history on every turn,
so quality drops, latency rises, and you pay for turn 1 fifty times. ContextSlim
fixes this at the protocol layer: the assistant checks its own context health,
compresses the session into a structured **Context Capsule**, and a brand-new
chat boots from that capsule with full working memory and none of the token debt.

```
DETECT ──────────► EXTRACT ─────────► STORE ──────────► RESTORE
check_context_     extract_session_    local SQLite,     load_capsule()
health()           state()             8-char id         in a fresh chat
```

---

## Contents

- [What it does](#what-it-does)
- [The Context Capsule](#the-context-capsule)
- [Install](#install)
- [Connect it to Claude Desktop](#connect-it-to-claude-desktop)
- [Reinstall on a new machine](#reinstall-on-a-new-machine)
- [Configuration](#configuration)
- [The eight tools](#the-eight-tools)
- [Compression modes](#compression-modes)
- [REST API](#rest-api)
- [Architecture](#architecture)
- [Testing](#testing)
- [Portability](#portability)
- [Licence](#licence)

---

## What it does

| Layer | Feature | What it gives you |
|---|---|---|
| 1 | Multi-format file processor | PDF, DOCX, XLSX, CSV, TXT, MD → clean Markdown |
| 1 | MarkItDown pipeline | Structure preserved (headings, tables, lists), HTML noise stripped |
| 1 | Raw text minifier | Free 5–15% token cut before anything reaches a model |
| 2 | `extract_session_state()` | Compress a session into a stored capsule |
| 2 | `load_capsule()` | Restore a session into a fresh chat |
| 2 | `list_capsules()` | Browse saved sessions |
| 2 | `get_stats()` | Aggregate tokens processed and saved |
| 2 | `check_context_health()` | HEALTHY / WARNING / CRITICAL, so the AI self-triggers |
| 2 | `update_capsule()` | Fold new progress into an existing capsule, versioned |
| 2 | `search_capsules()` | Find sessions by keyword |
| 2 | `export_capsule()` | `.txt` for other assistants, `.json` for tooling |
| 3 | Token metrics | raw → compressed → reduction%, on every operation |
| 3 | Mode selector | `slim` (free, offline) vs `deep` (Gemini Flash or Claude Haiku) |

Everything is local. No cloud service, no account, no telemetry: capsules live in
a SQLite file on your own machine.

---

## The Context Capsule

Not a summary — a save file with six fixed sections, each with a job:

```
## PROJECT          what is being built
## COMPLETED        work already finished, so it is never redone
## DECISIONS        choices made, and what was rejected
## CURRENT STATE    where the session stopped
## NEXT OBJECTIVE   the single next action
## CONSTRAINTS      rules the assistant must not violate
```

`load_capsule()` wraps that in a restore prompt telling the model to treat the
contents as established fact, honour the constraints, and continue from the next
objective.

---

## Install

Requires **Python 3.10+** (macOS ships 3.9, which is too old — get a newer one
from [python.org/downloads](https://www.python.org/downloads/)).

**Quit Claude Desktop first.** It rewrites its own config file when it exits,
so anything written while it is running is discarded. The installer checks for
this and refuses rather than writing something that will vanish.

Then, two commands:

```bash
pip install git+https://github.com/sentinalY/contextslim.git
contextslim install
```

That's it. `contextslim install` finds Claude Desktop's config file on your OS,
adds this server using the exact interpreter it was installed into, backs up
the previous file, and leaves any other MCP servers you have untouched.

Reopen Claude Desktop and ask:

> "check my context health with a token count of 94000"

A `CRITICAL` reply means it is connected.

### Working on the code instead

```bash
git clone https://github.com/sentinalY/contextslim.git
cd contextslim

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
pytest -q                          # 276 tests, all offline
python scripts/demo.py             # the whole pipeline, no API key needed
contextslim install
```

### Installer options

```bash
contextslim install --dry-run      # show what would change, write nothing
contextslim install --name slim2   # register under a different name
contextslim install --config PATH  # point at a specific config file
contextslim install --force        # write even if Claude Desktop is running
contextslim uninstall              # remove the entry again
contextslim --info                 # resolved paths, provider, capabilities
```

### Windows notes

- Use `py -3.13 -m venv .venv`, then `.venv\Scripts\activate` (not `bin`)
- If PowerShell blocks the activate script:
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`
- Claude Desktop hides in the system tray — right-click its icon and choose
  **Quit** before installing; closing the window is not enough

---

## Connect it to Claude Desktop

`contextslim install` does this for you. This section is for anyone who wants
to know what it writes, or who prefers editing the file by hand.

| OS | Config file |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "contextslim": {
      "command": "/absolute/path/to/contextslim/.venv/bin/python",
      "args": ["-m", "contextslim"]
    }
  }
}
```

On Windows the command is `C:\\path\\to\\contextslim\\.venv\\Scripts\\python.exe`
— **double backslashes**, since JSON treats a single `\` as an escape character.
Getting this wrong is the most common reason an MCP server never appears.

An API key is optional and belongs in the project's `.env` rather than in this
file, so it never ends up in a config you might share:

```bash
echo 'GEMINI_API_KEY=your-key-here' > .env      # .env is git-ignored
```

Without a key, deep mode falls back to slim and everything else works unchanged.

Restart Claude Desktop. The eight tools appear automatically. The same config
shape works for Cursor, Cline and Continue.

Then, in a chat:

> "Compress this session."
> → *Session saved. Open a new chat and say: load capsule A3F2K9B1*

> *(new chat)* "load capsule A3F2K9B1"
> → *Session restored. Next objective: implement the JWT refresh endpoint.*

---

## Reinstall on a new machine

Setting up again after a wipe, or on a second computer, is six steps.

```bash
# 1. Python 3.10+ (macOS ships 3.9, which is too old for fastmcp)
python3 --version
#    If below 3.10, install from python.org/downloads/macos (the .pkg installer,
#    NOT the source tarball) and use python3.13 below.

# 2. Clone
cd ~/Desktop
git clone https://github.com/sentinalY/contextslim.git
cd contextslim

# 3. Virtual environment and dependencies
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Confirm it works before wiring anything up
pytest -q                 # expect: all tests passing
python scripts/demo.py    # full pipeline, offline, no key needed

# 5. Optional: a key for deep mode. Slim mode needs nothing.
cp .env.example .env
nano .env                 # paste your key after GEMINI_API_KEY=

# 6. Register with Claude Desktop — QUIT THE APP FIRST (see below)
```

**Step 6 in detail.** Claude Desktop stores its own state in
`claude_desktop_config.json` and rewrites the whole file when it exits, so an
edit made while the app is running gets silently discarded. Quit it first:

```bash
osascript -e 'quit app "Claude"'
pgrep -x Claude || echo CLOSED          # must print CLOSED before continuing

python -c "import json,shutil;from pathlib import Path;p=Path.home()/'Library/Application Support/Claude/claude_desktop_config.json';shutil.copy(p,str(p)+'.backup');d=json.loads(p.read_text());d.setdefault('mcpServers',{})['contextslim']={'command':str(Path.home()/'Desktop/contextslim/.venv/bin/python'),'args':['-m','contextslim']};p.write_text(json.dumps(d,indent=2));print('WROTE OK')"

open -a Claude
```

Then ask Claude "check my context health with a token count of 94000". A
`CRITICAL` reply means the server is connected.

**What does not come from the repo.** Two things are deliberately excluded and
must be handled separately:

| Item | Location | Why it is not in git |
|---|---|---|
| API key | `.env` | Secrets never belong in a repository |
| Your saved capsules | `~/Library/Application Support/contextslim/contextslim.db` | Personal session data, not source code |

To carry your capsules to a new machine, copy that one `.db` file across after
step 3. To move a single session instead, use `export_capsule()` before the
wipe and keep the `.txt` or `.json` file.

**Troubleshooting.**

| Symptom | Cause | Fix |
|---|---|---|
| Tools missing in Claude Desktop | Config written while the app was running | Quit the app, rewrite, reopen |
| `404 ... model is no longer available` | Google retired that model id | The error names the replacement; set `CONTEXTSLIM_GEMINI_MODEL` |
| `503 UNAVAILABLE` | Upstream busy | Retried automatically; if it persists, wait and rerun |
| Deep mode silently gives slim output | No key, or the wrong provider's key | Run `contextslim --info` and check `deep_mode_available` |
| `editable mode requires a setuptools-based build` | Python 3.9 with an old pip | Install Python 3.10+ and rebuild the venv |

## Configuration

Copy `.env.example` to `.env` and edit, or set real environment variables —
env vars win. Nothing is hardcoded and no secret lives in the repo.

| Variable | Default | Purpose |
|---|---|---|
| `CONTEXTSLIM_DEEP_PROVIDER` | `gemini` | Deep-mode backend: `gemini` or `anthropic` |
| `GEMINI_API_KEY` | *(unset)* | Enables deep mode via Gemini. Absent → slim fallback |
| `ANTHROPIC_API_KEY` | *(unset)* | Enables deep mode via Claude Haiku |
| `CONTEXTSLIM_HOME` | OS user-data dir | Base directory for all runtime data |
| `CONTEXTSLIM_DB_PATH` | `<home>/contextslim.db` | SQLite file |
| `CONTEXTSLIM_EXPORT_DIR` | `<home>/exports` | Where `export_capsule()` writes |
| `CONTEXTSLIM_GEMINI_MODEL` | `gemini-3.6-flash` | Model used when provider is `gemini` |
| `CONTEXTSLIM_ANTHROPIC_MODEL` | `claude-haiku-4-5` | Model used when provider is `anthropic` |
| `CONTEXTSLIM_DEEP_MAX_TOKENS` | `2000` | Output cap for deep mode |
| `CONTEXTSLIM_DEEP_MAX_ATTEMPTS` | `3` | Tries before falling back on transient errors |
| `CONTEXTSLIM_DEEP_RETRY_BACKOFF_SECONDS` | `1.0` | Base delay, doubled each retry |
| `CONTEXTSLIM_DEEP_RATE_LIMIT_PER_MINUTE` | `20` | Cost guard on deep calls |
| `CONTEXTSLIM_SLIM_SENTENCES` | `14` | Sentence budget for slim mode |
| `CONTEXTSLIM_TOKEN_ENCODING` | `cl100k_base` | tiktoken encoding |
| `CONTEXTSLIM_HEALTH_WARNING_TOKENS` | `60000` | WARNING threshold |
| `CONTEXTSLIM_HEALTH_CRITICAL_TOKENS` | `80000` | CRITICAL threshold |
| `CONTEXTSLIM_CONTEXT_WINDOW_TOKENS` | `200000` | Window used for the % figure |
| `CONTEXTSLIM_MAX_FILE_MB` | `25` | Largest ingestible file |
| `CONTEXTSLIM_LOG_LEVEL` | `INFO` | Logs go to stderr only |

Default data directory: `~/Library/Application Support/contextslim` (macOS),
`~/.local/share/contextslim` (Linux), `%LOCALAPPDATA%\ContextSlim\contextslim`
(Windows). It is created on first use.

---

## The eight tools

### `extract_session_state(chat_history, mode, project, title, file_paths)`
Compresses a session and stores it. Returns `session_id`, before/after token
metrics and the capsule. `file_paths` additionally ingests documents.

### `load_capsule(session_id)`
Restores a session by its 8-character id and returns a `restore_prompt`.

### `list_capsules(limit, project)`
Saved sessions, newest first, with reduction % and next objective.

### `get_stats()`
Total sessions, tokens processed, tokens saved, overall efficiency, split by mode.

### `check_context_health(token_count | chat_history)`
Returns `HEALTHY`, `WARNING` or `CRITICAL` plus a recommendation. This is what
lets the assistant trigger compression on its own, before quality drops.

### `update_capsule(session_id, chat_history, mode, note, file_paths)`
Merges new progress into an existing capsule and bumps its version. The previous
version is archived, so a capsule becomes a living project memory.

### `search_capsules(query, limit)`
Keyword search across capsule text, title and project, with excerpts.

### `export_capsule(session_id, format, destination)`
`txt` (paste into ChatGPT/Gemini) or `json` (structured handoff).

Tools never raise across the protocol. Failures come back as
`{"ok": false, "error": {"code": ..., "message": ...}}` so the model can read the
problem and react.

---

## Compression modes

| | slim | deep |
|---|---|---|
| Engine | sumy LSA, extractive | Gemini Flash or Claude Haiku, abstractive |
| Cost | free | one small API call |
| Network | none | required |
| Determinism | identical output every run | model-dependent |
| Best at | routine checkpoints | decisions and constraints, messy sessions |

Slim ships its own regex tokenizer, so it needs **no NLTK downloads** and works
on a fresh clone with no network.

### Deep-mode providers

The model vendor is a configuration choice, not an architectural one. The
compressor owns the prompt, chunking, JSON parsing, rate limiting and fallback;
a provider class owns the API call, and nothing else imports a vendor SDK.

```bash
CONTEXTSLIM_DEEP_PROVIDER=gemini      # default — free tier available
CONTEXTSLIM_DEEP_PROVIDER=anthropic   # Claude Haiku, as named in the product doc
```

Each provider reads its own key (`GEMINI_API_KEY` / `ANTHROPIC_API_KEY`), so a
key for one never makes the other look available. Adding a third provider means
one new class in `compression/providers/` and one registry entry.

Deep mode has four rails:

1. No key, API error or unparseable output falls back to slim with the reason
   reported — never silently, and the message names the exact environment
   variable to set.
2. Transient upstream failures (503 "high demand", 429 rate limits) are retried
   with exponential backoff first. Permanent rejections — a bad key, a retired
   model — are never retried, since repeating those only wastes time.
3. A local rate limiter caps calls per minute so cost cannot run away.
4. Very long sessions are chunked and merged rather than truncated.

Model ids do get retired. When that happens the API says so and names the
replacement; changing `CONTEXTSLIM_GEMINI_MODEL` is the entire fix, with no
code change — which is why the model was never hardcoded.

---

## REST API

MCP is the product, but a REST surface exists for non-MCP callers:

```bash
uvicorn contextslim.api:app --reload      # docs at /docs
```

| Method | Path | Tool equivalent |
|---|---|---|
| `POST` | `/capsules` | `extract_session_state` |
| `GET` | `/capsules` | `list_capsules` |
| `GET` | `/capsules/search?q=` | `search_capsules` |
| `GET` | `/capsules/{id}` | `load_capsule` |
| `PATCH` | `/capsules/{id}` | `update_capsule` |
| `GET` | `/capsules/{id}/versions` | version history |
| `POST` | `/capsules/{id}/export` | `export_capsule` |
| `POST` | `/context/health` | `check_context_health` |
| `GET` | `/stats` | `get_stats` |
| `GET` | `/health` | server self-check |

Both transports call the same service layer, so they cannot drift apart.

---

## Architecture

```
MCP client (Claude Desktop, Cursor, Cline)
        │ stdio · JSON-RPC
┌───────▼──────────────────────────────────┐
│ server.py      8 tool definitions        │  thin: forward + shape errors
├──────────────────────────────────────────┤
│ service.py     orchestration             │  ingest → count → compress → store
├─────────────┬──────────────┬─────────────┤
│ compression │   storage    │  ingestion  │
│ slim / deep │  aiosqlite   │ markitdown  │
├─────────────┴──────────────┴─────────────┤
│ config · paths · tokens · minify · capsule│  pure, no I/O dependencies
└──────────────────────────────────────────┘
```

```
src/contextslim/
├── config.py          env-driven settings
├── paths.py           cross-platform locations
├── tokens.py          approximate counting + offline fallback
├── minify.py          raw text minifier
├── ingest.py          multi-format file processor
├── capsule.py         the six-section capsule model
├── compression/
│   ├── base.py        compressor contract
│   ├── slim.py        sumy LSA extractive
│   ├── deep.py        abstractive: prompt, chunking, rate limit, fallback
│   ├── providers/     vendor backends (gemini, anthropic) behind one interface
│   └── text_utils.py  offline tokenizer, reflow, sentence splitting
├── storage/
│   ├── schema.sql     capsules + capsule_versions + meta
│   ├── models.py      row models
│   └── db.py          async store
├── service.py         all eight capabilities
├── server.py          MCP transport
├── api.py             REST transport
└── __main__.py        CLI entry point
```

**Database.** Two tables plus metadata. `capsules` holds the current state of
every session; `capsule_versions` archives each earlier state so `update_capsule`
never destroys history. Stats are computed in SQL, so counters cannot drift out
of sync with reality. The schema avoids SQLite-only features, keeping the
PostgreSQL upgrade path a driver swap rather than a rewrite.

---

## Testing

```bash
pytest                                   # full suite
pytest --cov=contextslim                 # with coverage
pytest tests/test_server.py -v           # MCP protocol tests only
```

**276 tests, ~96% coverage.** No test touches the network, spends API credit, or
writes outside a temporary directory. Both vendor clients are stubbed, so deep
mode's prompt shape, per-provider request format, JSON parsing, chunking, rate
limiting and every fallback path are all covered offline.

The MCP tests drive a real in-memory MCP client rather than calling Python
functions, so tool registration, schemas and error shaping are covered the way a
client would actually hit them.

---

## Portability

The project is built to survive being cloned onto a different machine:

- No hardcoded paths anywhere — a test asserts this by scanning the source.
- All locations come from `platformdirs` or environment variables.
- Runtime directories are created automatically on first use.
- Secrets live only in the environment; `.env` is git-ignored.
- No NLTK corpus download: slim mode ships its own tokenizer.
- tiktoken unavailable or offline → character-ratio estimate, clearly labelled,
  instead of a crash.
- MarkItDown missing → plain-text formats still ingest.
- No API key → deep mode falls back to slim and names the variable to set.
- No vendor lock-in: the deep-mode provider is one environment variable.

---

## Licence

MIT. See [LICENSE](LICENSE).

Built from the ContextSlim AI product document by Devi Sai Charan Vemulapalli
and Yagnadeep Reddy.
