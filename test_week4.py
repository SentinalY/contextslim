"""
Test Week 4: update_capsule() and search_capsules()
"""
import asyncio
from fastmcp import Client

async def main():
    client = Client("server.py")
    async with client:
        messages = [
            {"role": "user", "content": "I want to build an MCP server that compresses chat history."},
            {"role": "assistant", "content": "Great idea. We'll use fastmcp for the server and sumy for slim-mode compression."},
        ]

        print("1. Creating a capsule to update later...")
        result = await client.call_tool(
            "extract_session_state",
            {"messages": messages, "session_id": "week4-test", "mode": "slim"},
        )
        print(result.content[0].text, "\n")

        # Extract the capsule_id from the JSON response so we can update it next
        import json
        capsule_data = json.loads(result.content[0].text)
        capsule_id = capsule_data["capsule_id"]

        print(f"2. Updating capsule {capsule_id}...")
        result = await client.call_tool(
            "update_capsule",
            {"capsule_id": capsule_id, "summary": "Updated: the project now also plans to add deep mode via Gemini Flash."},
        )
        print(result.content[0].text, "\n")

        print("3. Loading the capsule back to confirm the update...")
        result = await client.call_tool("load_capsule", {"capsule_id": capsule_id})
        print(result.content[0].text, "\n")

        print("4. Searching capsules for 'Gemini'...")
        result = await client.call_tool("search_capsules", {"query": "Gemini"})
        print(result.content[0].text, "\n")

if __name__ == "__main__":
    asyncio.run(main())