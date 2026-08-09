# ContextSlim MCP

An MCP (Model Context Protocol) server that compresses AI chat history into structured, searchable **"Context Capsules."** Built with Python and FastMCP, it helps preserve important context from long AI conversations without hitting token limits — instead of losing history when a chat gets too long, ContextSlim distills it down and stores it for later retrieval.

Built collaboratively with [Devi Sai Charan] , where it was pitched to a startup CEO evaluator.

## What it does

Long AI conversations accumulate context that's expensive to keep around and easy to lose. ContextSlim solves this by:

- Compressing conversation history into compact, structured "Context Capsules"
- Storing capsules in a local SQLite database for fast retrieval
- Supporting two distinct compression modes depending on how much fidelity you need
- Letting AI tools like Claude Desktop pull relevant past context back into a conversation on demand

## Features

- **Dual compression modes:**
  - **Slim mode** — extractive summarization using `sumy` (LSA algorithm). Fast, lightweight, no external API calls.
  - **Deep mode** — LLM-based summarization using Gemini Flash for higher-quality, context-aware compression.
- **8 MCP tools** exposed for creating, searching, retrieving, and managing Context Capsules
- **PDF ingestion** — pull content directly from PDF documents into the capsule system
- **SQLite-backed storage** with absolute path anchoring, so the database works reliably regardless of where the server is launched from
- **Claude Desktop integration** — works directly as an MCP server inside Claude Desktop
- **Environment-based configuration** via `python-dotenv` for reliable API key handling

## Tech stack

- **Language:** Python
- **Protocol:** FastMCP (Model Context Protocol)
- **Database:** SQLite
- **Summarization:** sumy (LSA) for slim mode, Gemini Flash for deep mode
- **Config management:** python-dotenv

## Architecture notes

A few deliberate design decisions worth calling out:

- **Lazy Gemini client initialization** — the Gemini API client is only initialized when deep mode is actually invoked, avoiding unnecessary startup overhead or failures when the API isn't needed.
- **Absolute DB path anchoring** — the SQLite database path is resolved absolutely rather than relative to the working directory, so the server behaves consistently no matter where it's launched from.
- **Compression trade-offs** — compression performs best on longer conversations. Very short inputs can actually produce net-negative compression once capsule metadata overhead is factored in, so ContextSlim is best suited for genuinely long chat histories.

## Getting started

```bash
# Clone the repo
git clone https://github.com/yagnadeepreddy081-reddy/contextslim-mcp.git
cd contextslim-mcp

# Install dependencies (fastmcp, sumy, google-generativeai, python-dotenv)
pip install fastmcp sumy google-generativeai python-dotenv

# Set up environment variables
echo "GEMINI_API_KEY=your_key_here" > .env

# Run the server
python server.py
```

> **Note:** You'll need a Gemini API key for deep mode compression. Slim mode works without any external API.

## Project structure

```
contextslim-mcp/
├── server.py              # Main MCP server
├── compressor.py          # Compression logic (slim + deep modes)
├── storage.py             # SQLite storage layer
├── test_*.py               # Test suite covering compressor, storage, server integration
└── .gitignore
```

## Status

Actively developed. Built as part of ongoing exploration into agentic AI tooling and the Model Context Protocol ecosystem.

## License

MIT — see [LICENSE](LICENSE) for details.
