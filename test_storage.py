"""
Test script for storage.py
Run this to verify the aiosqlite storage layer works correctly.

Usage:
    python test_storage.py
"""

import asyncio
from storage import init_db, save_capsule, get_capsule, list_capsules, get_stats


async def main():
    print("1. Initializing database...")
    await init_db()
    print("   Done. A file named 'contextslim.db' should now exist in this folder.\n")

    print("2. Saving a dummy capsule...")
    await save_capsule(
        capsule_id="capsule-001",
        session_id="dummy-session-001",
        mode="slim",
        original_turn_count=42,
        token_count_before=8000,
        token_count_after=1200,
        compressed_content={"summary": "This is a placeholder compressed summary."},
    )
    print("   Saved.\n")

    print("3. Loading it back by ID...")
    capsule = await get_capsule("capsule-001")
    print("  ", capsule, "\n")

    print("4. Listing all capsules...")
    capsules = await list_capsules()
    print("  ", capsules, "\n")

    print("5. Getting aggregate stats...")
    stats = await get_stats()
    print("  ", stats)


if __name__ == "__main__":
    asyncio.run(main())