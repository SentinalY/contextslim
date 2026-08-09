import asyncio
from fastmcp import Client

async def main():
    client = Client("server.py")
    async with client:
        print("Connected! Listing tools...")
        tools = await client.list_tools()
        for t in tools:
            print(" -", t.name)

        print("\nCalling ping()...")
        result = await client.call_tool("ping", {})
        print(result.content[0].text)

if __name__ == "__main__":
    asyncio.run(main())