import asyncio
from fastmcp import Client

async def main():
    print("Starting MCP Client and connecting to ContextSlim server...")
    
    # Connect to the local server via stdio
    async with Client("server.py") as client:
        
        print("\n--- Testing get_stats() ---")
        try:
            stats_result = await client.call_tool("get_stats", {})
            print(stats_result)
        except Exception as e:
            print(f"Error calling get_stats: {e}")

        print("\n--- Testing list_capsules() ---")
        try:
            # We pass an empty dict because session_id is optional
            capsules_result = await client.call_tool("list_capsules", {})
            print(capsules_result)
        except Exception as e:
            print(f"Error calling list_capsules: {e}")

if __name__ == "__main__":
    asyncio.run(main())