#!/usr/bin/env python3
"""End-to-end demo: compress a 41-turn session, then restore it.

Runs entirely offline in slim mode against a throwaway database, so it works
on any machine with no API key and no network:

    python scripts/demo.py

Add --deep to use Claude Haiku instead (requires ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SAMPLE = ROOT / "tests" / "fixtures" / "sample_chat.md"

RULE = "─" * 72


def heading(text: str) -> None:
    print(f"\n{RULE}\n  {text}\n{RULE}")


async def run(mode: str, keep_db: bool) -> int:
    if not keep_db:
        os.environ["CONTEXTSLIM_HOME"] = tempfile.mkdtemp(prefix="contextslim-demo-")

    from contextslim.config import reset_settings_cache
    from contextslim.service import ContextSlimService

    reset_settings_cache()
    service = ContextSlimService()

    chat = SAMPLE.read_text(encoding="utf-8")

    heading("1. DETECT — check_context_health()")
    # Scaled up to a realistic long session so the thresholds are meaningful.
    health = service.check_context_health(token_count=94_000)
    print(f"  status        : {health['status']}")
    print(f"  tokens        : {health['token_count']:,} ({health['window_used_pct']}% of window)")
    print(f"  recommendation: {health['recommendation']}")

    heading(f"2. EXTRACT — extract_session_state(mode='{mode}')")
    created = await service.extract_session_state(
        chat, mode=mode, project="FastAPI auth system", title="Portal auth session"
    )
    metrics = created["metrics"]
    print(f"  session id       : {created['session_id']}")
    print(f"  mode used        : {created['mode']}")
    if created.get("fallback_reason"):
        print(f"  fallback         : {created['fallback_reason']}")
    print(f"  raw tokens       : {metrics['raw_tokens']:,}")
    print(f"  minifier saved   : {metrics['minifier_saved_tokens']:,}")
    print(f"  compressed tokens: {metrics['compressed_tokens']:,}")
    print(f"  reduction        : {metrics['reduction_pct']}%")

    heading("3. THE CAPSULE")
    print(created["capsule_preview"])

    heading("4. RESTORE — load_capsule() in a fresh chat")
    loaded = await service.load_capsule(created["session_id"])
    print(loaded["restore_prompt"][:700] + "\n  …")
    print(f"\n  tokens saved vs replaying the session: {loaded['metrics']['tokens_saved']:,}")

    heading("5. UPDATE — update_capsule() after more work")
    updated = await service.update_capsule(
        created["session_id"],
        "We finished the Alembic migration. Decision: we chose Locust over k6 for "
        "load testing. Next objective: ship the rate limiter to staging.",
        note="second work block",
    )
    print(f"  version      : v{updated['previous_version']} → v{updated['version']}")
    print(f"  items added  : {updated['items_added']}")
    print(f"  next objective: {updated['capsule']['next_objective']}")

    heading("6. SEARCH + EXPORT + STATS")
    found = await service.search_capsules("PostgreSQL")
    print(f"  search 'PostgreSQL' : {found['count']} match(es)")
    exported = await service.export_capsule(created["session_id"], "txt")
    print(f"  exported to         : {exported['path']}")
    stats = await service.get_stats()
    print(f"  sessions            : {stats['total_sessions']}")
    print(f"  tokens processed    : {stats['total_raw_tokens']:,}")
    print(f"  tokens saved        : {stats['total_tokens_saved']:,}")
    print(f"  overall efficiency  : {stats['overall_efficiency_pct']}%")

    print(f"\n{RULE}\n  Token counts are approximate (tiktoken/GPT tokenizer).\n{RULE}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="ContextSlim end-to-end demo.")
    parser.add_argument("--deep", action="store_true", help="Use deep mode (needs an API key).")
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Use the real database instead of a throwaway one.",
    )
    args = parser.parse_args()
    return asyncio.run(run("deep" if args.deep else "slim", args.keep_db))


if __name__ == "__main__":
    raise SystemExit(main())
