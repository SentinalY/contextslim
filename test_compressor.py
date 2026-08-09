from compressor import compress_slim

def run_test():
    print("Testing LSA Slim Compression...\n")

    # A bulky dummy conversation to test the math and summarization
    dummy_text = """
    User: Can you explain how ContextSlim works?
    Assistant: ContextSlim is an MCP server designed to solve LLM memory limits. It takes your massive conversation history and compresses it into a structured 'Context Capsule'. This way, you don't lose context between sessions.
    User: That sounds useful. What technologies does it use under the hood?
    Assistant: It uses FastMCP for the server protocol, aiosqlite for persistent storage, and sumy for LSA-based lightweight compression. For deep compression, it will eventually route through an LLM API.
    User: And how do you measure if the compression is actually working?
    Assistant: By token counting! We use tiktoken with the cl100k_base encoding to count the exact number of tokens before and after compression, storing those metrics in the database.
    """

    # Compress down to the 3 most mathematically significant sentences
    result = compress_slim(dummy_text, sentence_count=3)

    print("--- Compressed Summary ---")
    print(result["summary"])
    
    print("\n--- Token Math ---")
    print(f"Tokens Before: {result['tokens_before']}")
    print(f"Tokens After:  {result['tokens_after']}")
    print(f"Tokens Saved:  {result['tokens_before'] - result['tokens_after']}")

if __name__ == "__main__":
    run_test()