"""Service layer: the full extract -> restore -> update -> export lifecycle."""

from __future__ import annotations

import json

import pytest

from contextslim.errors import CapsuleNotFoundError, InvalidInputError
from contextslim.service import ContextSlimService


@pytest.fixture
def service(settings) -> ContextSlimService:
    return ContextSlimService(settings)


# --- extract ---------------------------------------------------------------


async def test_extract_returns_metrics_and_stores_capsule(service, sample_chat):
    result = await service.extract_session_state(sample_chat)

    assert result["ok"] is True
    assert len(result["session_id"]) == 8
    assert result["mode"] == "slim"
    assert result["metrics"]["raw_tokens"] > result["metrics"]["compressed_tokens"]
    assert result["metrics"]["reduction_pct"] > 50
    assert result["metrics"]["tokens_saved"] > 0
    assert result["capsule"]["decisions"]
    assert result["session_id"] in result["restore_hint"]

    stored = await service.store.get(result["session_id"])
    assert stored is not None


async def test_extract_records_minifier_contribution(service, sample_chat):
    padded = sample_chat.replace("\n", "\n   \n")  # simulate a noisy transcript
    result = await service.extract_session_state(padded)
    assert result["metrics"]["minifier_saved_tokens"] > 0


async def test_extract_rejects_empty_input(service):
    with pytest.raises(InvalidInputError, match="Nothing to compress"):
        await service.extract_session_state("   ")


async def test_extract_rejects_unknown_mode(service, sample_chat):
    with pytest.raises(InvalidInputError, match="Unknown mode"):
        await service.extract_session_state(sample_chat, mode="turbo")


async def test_deep_mode_without_key_falls_back_and_says_so(service, sample_chat):
    result = await service.extract_session_state(sample_chat, mode="deep")
    assert result["requested_mode"] == "deep"
    assert result["mode"] == "slim"
    # Names the variable for the *selected* provider, so the fix is obvious.
    assert "GEMINI_API_KEY" in result["fallback_reason"]
    assert "fell back to slim" in result["summary"]


async def test_anthropic_provider_names_its_own_key_when_selected(tmp_path, sample_chat):
    from contextslim.config import Settings

    settings = Settings(home=tmp_path, deep_provider="anthropic", _env_file=None)
    result = await ContextSlimService(settings).extract_session_state(sample_chat, mode="deep")
    assert result["mode"] == "slim"
    assert "ANTHROPIC_API_KEY" in result["fallback_reason"]


async def test_health_reports_the_selected_provider(service):
    report = await service.health()
    assert report["deep_provider"]["provider"] == "gemini"
    assert report["deep_provider"]["key_env_var"] == "GEMINI_API_KEY"
    assert report["deep_provider"]["available"] is False


async def test_extract_from_files_only(service, tmp_path):
    doc = tmp_path / "design.md"
    doc.write_text(
        "# Auth design\n\nDecision: we chose RS256 over HS256 for token signing.\n"
        "Constraint: no new infrastructure until Q4.\n",
        encoding="utf-8",
    )
    result = await service.extract_session_state(file_paths=[str(doc)])

    assert result["ingestion"]["file_count"] == 1
    assert result["ok"] is True
    stored = await service.store.get(result["session_id"])
    assert stored.source_files == ["design.md"]


async def test_extract_reports_unreadable_files(service, sample_chat, tmp_path):
    result = await service.extract_session_state(
        sample_chat, file_paths=[str(tmp_path / "ghost.pdf")]
    )
    assert result["ok"] is True  # the chat still compressed
    assert len(result["ingestion"]["errors"]) == 1


async def test_explicit_project_is_stored(service, sample_chat):
    result = await service.extract_session_state(sample_chat, project="Portal auth")
    assert result["project"] == "Portal auth"


# --- load ------------------------------------------------------------------


async def test_extract_then_load_round_trip(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    loaded = await service.load_capsule(created["session_id"])

    assert loaded["session_id"] == created["session_id"]
    assert loaded["capsule"] == created["capsule"]
    assert "CONTEXT CAPSULE RESTORED" in loaded["restore_prompt"]
    assert loaded["metrics"]["tokens_saved"] == created["metrics"]["tokens_saved"]
    assert loaded["capsule"]["next_objective"] in loaded["summary"]


async def test_load_is_case_insensitive(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    loaded = await service.load_capsule(created["session_id"].lower())
    assert loaded["ok"] is True


async def test_load_increments_restore_count(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    await service.load_capsule(created["session_id"])
    await service.load_capsule(created["session_id"])
    record = await service.store.get(created["session_id"])
    assert record.restore_count == 2


async def test_load_unknown_id_lists_known_ones(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    with pytest.raises(CapsuleNotFoundError) as exc:
        await service.load_capsule("ZZZZZZZZ")
    assert created["session_id"] in str(exc.value)


async def test_load_requires_an_id(service):
    with pytest.raises(InvalidInputError):
        await service.load_capsule("")


# --- list ------------------------------------------------------------------


async def test_list_capsules(service, sample_chat):
    await service.extract_session_state(sample_chat, project="Portal")
    await service.extract_session_state(sample_chat, project="Billing")

    everything = await service.list_capsules()
    assert everything["count"] == 2
    assert {"session_id", "mode", "reduction_pct", "created_at"} <= set(
        everything["capsules"][0]
    )

    filtered = await service.list_capsules(project="Bill")
    assert filtered["count"] == 1


async def test_list_when_empty_suggests_next_step(service):
    result = await service.list_capsules()
    assert result["count"] == 0
    assert "extract_session_state" in result["summary"]


# --- stats -----------------------------------------------------------------


async def test_stats_aggregate_across_sessions(service, sample_chat):
    first = await service.extract_session_state(sample_chat)
    second = await service.extract_session_state(sample_chat)
    stats = await service.get_stats()

    assert stats["total_sessions"] == 2
    expected_saved = first["metrics"]["tokens_saved"] + second["metrics"]["tokens_saved"]
    assert stats["total_tokens_saved"] == expected_saved
    assert stats["overall_efficiency_pct"] > 50
    assert "slim" in stats["modes"] and "deep" in stats["modes"]


# --- health ----------------------------------------------------------------


def test_health_healthy(service):
    result = service.check_context_health(token_count=10_000)
    assert result["status"] == "HEALTHY"
    assert result["should_compress"] is False


def test_health_warning_at_threshold(service):
    result = service.check_context_health(token_count=60_000)
    assert result["status"] == "WARNING"
    assert result["should_compress"] is True


def test_health_critical_matches_the_product_walkthrough(service):
    result = service.check_context_health(token_count=94_000)
    assert result["status"] == "CRITICAL"
    assert result["should_compress"] is True
    assert "extract_session_state" in result["recommendation"]
    assert result["window_used_pct"] == 47.0


def test_health_can_measure_raw_text(service, sample_chat):
    result = service.check_context_health(chat_history=sample_chat)
    assert result["token_count"] > 0
    assert result["status"] == "HEALTHY"


def test_health_requires_an_input(service):
    with pytest.raises(InvalidInputError):
        service.check_context_health()


def test_health_thresholds_come_from_settings(settings):
    settings.health_warning_tokens = 100
    settings.health_critical_tokens = 200
    service = ContextSlimService(settings)
    assert service.check_context_health(token_count=150)["status"] == "WARNING"
    assert service.check_context_health(token_count=250)["status"] == "CRITICAL"


# --- update ----------------------------------------------------------------


async def test_update_merges_and_versions(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    follow_up = (
        "We finished the Alembic migration for the auth schema. "
        "Decision: we chose Locust over k6 for load testing. "
        "Next objective: wire the PostgreSQL rate limiter into the login route."
    )
    updated = await service.update_capsule(created["session_id"], follow_up)

    assert updated["version"] == 2
    assert updated["previous_version"] == 1
    assert updated["metrics"]["cumulative_raw_tokens"] > created["metrics"]["raw_tokens"]

    capsule = updated["capsule"]
    assert any("Locust" in d for d in capsule["decisions"])
    assert any("PostgreSQL" in d for d in capsule["decisions"]) or any(
        "PostgreSQL" in c for c in capsule["constraints"] + capsule["completed"]
    )
    assert "rate limiter" in capsule["next_objective"]


async def test_update_preserves_earlier_decisions(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    original_decisions = set(created["capsule"]["decisions"])
    updated = await service.update_capsule(
        created["session_id"], "Decision: we chose Locust for load testing."
    )
    assert original_decisions <= set(updated["capsule"]["decisions"])


async def test_update_archives_history(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    await service.update_capsule(created["session_id"], "More work happened here.", note="block 2")
    history = await service.capsule_versions(created["session_id"])
    assert history["count"] == 1
    assert history["versions"][0]["note"] == "block 2"


async def test_update_unknown_capsule_raises(service):
    with pytest.raises(CapsuleNotFoundError):
        await service.update_capsule("ZZZZZZZZ", "text")


# --- search ----------------------------------------------------------------


async def test_search_finds_by_content_with_excerpt(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    found = await service.search_capsules("PostgreSQL")

    assert found["count"] == 1
    assert found["capsules"][0]["session_id"] == created["session_id"]
    assert "postgresql" in found["capsules"][0]["excerpt"].lower()


async def test_search_no_matches(service, sample_chat):
    await service.extract_session_state(sample_chat)
    found = await service.search_capsules("quantum teleportation")
    assert found["count"] == 0
    assert "No capsules match" in found["summary"]


async def test_search_requires_a_query(service):
    with pytest.raises(InvalidInputError):
        await service.search_capsules("  ")


# --- export ----------------------------------------------------------------


async def test_export_txt_is_a_restore_prompt(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    exported = await service.export_capsule(created["session_id"], "txt")

    from pathlib import Path

    path = Path(exported["path"])
    assert path.exists()
    assert path.suffix == ".txt"
    assert "CONTEXT CAPSULE RESTORED" in path.read_text(encoding="utf-8")
    assert exported["bytes_written"] > 0


async def test_export_json_is_machine_readable(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    exported = await service.export_capsule(created["session_id"], "json")

    payload = json.loads(exported["content"])
    assert payload["session_id"] == created["session_id"]
    assert payload["capsule"]["decisions"]


async def test_export_to_explicit_destination(service, sample_chat, tmp_path):
    created = await service.extract_session_state(sample_chat)
    target = tmp_path / "handoff" / "capsule.txt"
    exported = await service.export_capsule(created["session_id"], "txt", str(target))
    assert exported["path"] == str(target)
    assert target.exists()  # parent directory created automatically


async def test_export_into_a_directory_names_the_file(service, sample_chat, tmp_path):
    created = await service.extract_session_state(sample_chat)
    exported = await service.export_capsule(created["session_id"], "json", str(tmp_path))
    assert exported["path"].endswith(f"{created['session_id']}_v1.json")


async def test_export_rejects_unknown_format(service, sample_chat):
    created = await service.extract_session_state(sample_chat)
    with pytest.raises(InvalidInputError, match="Unknown export format"):
        await service.export_capsule(created["session_id"], "pdf")


async def test_export_unknown_capsule_raises(service):
    with pytest.raises(CapsuleNotFoundError):
        await service.export_capsule("ZZZZZZZZ", "txt")


# --- diagnostics -----------------------------------------------------------


async def test_health_report(service, sample_chat):
    await service.extract_session_state(sample_chat)
    report = await service.health()
    assert report["ok"] is True
    assert report["capsules_stored"] == 1
    assert report["deep_mode_available"] is False
    assert report["version"]
