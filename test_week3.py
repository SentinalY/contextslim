"""
Test Week 3: slim mode, deep mode, and check_context_health — all through server.py
"""
import asyncio
from fastmcp import Client

async def main():
    import os
    client = Client("server.py")
    async with client:
       
        messages = [
            {"role": "user", "content": "I want to build an MCP server that compresses chat history."},
            {"role": "assistant", "content": "Great idea. We'll use fastmcp for the server and sumy for slim-mode compression."},
            {"role": "user", "content": "How do we store the compressed capsules?"},
            {"role": "assistant", "content": "We'll use aiosqlite for local async storage, no external DB needed."},
            {"role": "user", "content": "What about higher quality compression?"},
            {"role": "assistant", "content": "We'll add a deep mode using Gemini Flash with a structured 6-section prompt."},
        ]

        print("1. Checking context health...")
        result = await client.call_tool("check_context_health", {"messages": messages, "token_threshold": 50})
        print(result.content[0].text, "\n")

        print("2. Compressing in SLIM mode...")
        result = await client.call_tool(
            "extract_session_state",
            {"messages": messages, "session_id": "week3-test", "mode": "slim"},
        )
        print(result.content[0].text, "\n")

        print("3. Compressing in DEEP mode...")
        result = await client.call_tool(
            "extract_session_state",
            {"messages": messages, "session_id": "week3-test", "mode": "deep"},
        )
        print(result.content[0].text, "\n")

if __name__ == "__main__":
    asyncio.run(main())