import json
import asyncio
import uuid
from fastmcp import FastMCP
import storage
from compressor import compress_slim, compress_deep, count_tokens

mcp = FastMCP("ContextSlim")

# Ensure the database is initialized when the server script runs
asyncio.run(storage.init_db())


@mcp.tool()
def ping() -> str:
    """Simple health-check tool. Call this first to confirm the server is alive."""
    return "pong - ContextSlim MCP server is running"


@mcp.tool()
async def extract_session_state(
    messages: list[dict],
    session_id: str,
    mode: str = "slim",
    sentence_count: int = 5,
) -> str:
    """
    Compress a conversation into a Context Capsule and save it.
    mode can be "slim" (fast/free) or "deep" (higher quality, uses Gemini).
    """
    full_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)

    if mode == "deep":
        result = compress_deep(full_text)
        content_to_store = result["summary"]
    else:
        result = compress_slim(full_text, sentence_count=sentence_count)
        content_to_store = {"summary": result["summary"]}

    capsule_id = str(uuid.uuid4())[:8]

    await storage.save_capsule(
        capsule_id=capsule_id,
        session_id=session_id,
        mode=mode,
        original_turn_count=len(messages),
        token_count_before=result["tokens_before"],
        token_count_after=result["tokens_after"],
        compressed_content=content_to_store,
    )

    return json.dumps({
        "capsule_id": capsule_id,
        "session_id": session_id,
        "mode": mode,
        "tokens_before": result["tokens_before"],
        "tokens_after": result["tokens_after"],
        "tokens_saved": result["tokens_before"] - result["tokens_after"],
        "content": content_to_store,
    }, indent=2)
@mcp.tool()
def check_context_health(messages: list[dict], token_threshold: int = 80000) -> str:
    """
    Checks if a conversation has gotten too long and should be compressed.
    """
    full_text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    current_tokens = count_tokens(full_text)
    should_compress = current_tokens >= token_threshold

    return json.dumps({
        "current_tokens": current_tokens,
        "threshold": token_threshold,
        "should_compress": should_compress,
        "recommendation": (
            "Context is large — call extract_session_state to compress."
            if should_compress
            else "Context is healthy — no action needed yet."
        ),
    }, indent=2)

    


# ==========================================
# WEEK 2: STORAGE TOOLS
# ==========================================

@mcp.tool()
async def load_capsule(capsule_id: str) -> str:
    """Load a specific Context Capsule by ID."""
    capsule = await storage.get_capsule(capsule_id)
    if capsule:
        return json.dumps(capsule, indent=2)
    return json.dumps({"error": f"Capsule {capsule_id} not found."})


@mcp.tool()
async def list_capsules(session_id: str = None) -> str:
    """List all capsules, optionally filtered by session_id."""
    capsules = await storage.list_capsules(session_id)
    return json.dumps(capsules, indent=2)


@mcp.tool()
async def get_stats() -> str:
    """Get aggregate compression stats across all saved capsules."""
    stats = await storage.get_stats()
    return json.dumps(stats, indent=2)

@mcp.tool()
async def update_capsule(capsule_id: str, summary: str) -> str:
    """Update an existing capsule's summary content."""
    new_content = {"summary": summary}
    new_tokens = count_tokens(summary)
    success = await storage.update_capsule(capsule_id, new_content, new_tokens)
    if success:
        return json.dumps({"status": "updated", "capsule_id": capsule_id})
    return json.dumps({"status": "not_found", "capsule_id": capsule_id})


@mcp.tool()
async def search_capsules(query: str) -> str:
    """Search saved capsules for those containing the given text."""
    results = await storage.search_capsules(query)
    return json.dumps(results, indent=2)

if __name__ == "__main__":
    mcp.run()