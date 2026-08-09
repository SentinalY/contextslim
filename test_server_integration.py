"""
Test the full pipeline: extract_session_state -> compress -> save -> load/list/stats
Run this to confirm server.py's real tools work together, without needing Claude Desktop.
"""
import asyncio
from fastmcp import Client

async def main():
    client = Client("server.py")
    async with client:
        # Simulate a real conversation the AI client would pass in
        messages = [
            {"role": "user", "content": "I want to build an MCP server that compresses chat history."},
            {"role": "assistant", "content": "Great idea. We can use sumy for local LSA-based summarization."},
            {"role": "user", "content": "How do we store the compressed capsules?"},
            {"role": "assistant", "content": "We'll use aiosqlite for local async storage, no external DB needed."},
            {"role": "user", "content": "And how do we restore a session later?"},
            {"role": "assistant", "content": "We'll expose a load_capsule tool that returns the full capsule by ID."},
        ]

        print("1. Calling extract_session_state()...")
        result = await client.call_tool(
            "extract_session_state",
            {"messages": messages, "session_id": "test-session-001", "sentence_count": 3},
        )
        print(result.content[0].text, "\n")

        print("2. Listing all capsules...")
        result = await client.call_tool("list_capsules", {})
        print(result.content[0].text, "\n")

        print("3. Getting aggregate stats...")
        result = await client.call_tool("get_stats", {})
        print(result.content[0].text)

if __name__ == "__main__":
    asyncio.run(main())