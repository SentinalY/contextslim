from compressor import compress_deep
import json

conversation = """
user: I want to build an MCP server that compresses chat history.
assistant: Great idea. We'll use fastmcp for the server and sumy for slim-mode compression.
user: How do we store the compressed capsules?
assistant: We'll use aiosqlite for local async storage, no external DB needed.
user: What about higher quality compression?
assistant: We'll add a deep mode using Gemini Flash with a structured 6-section prompt.
user: What are the 6 sections?
assistant: PROJECT, COMPLETED, DECISIONS, CURRENT STATE, NEXT OBJECTIVE, and CONSTRAINTS.
"""

result = compress_deep(conversation)
print("--- Deep Compression Result ---")
print(json.dumps(result["summary"], indent=2))
print(f"\nTokens Before: {result['tokens_before']}")
print(f"Tokens After: {result['tokens_after']}")