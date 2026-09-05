"""Capsule store: schema, CRUD, versioning, search, aggregation."""

from __future__ import annotations

import re

import pytest

from contextslim.capsule import Capsule
from contextslim.errors import CapsuleNotFoundError
from contextslim.storage import CapsuleRecord, CapsuleStore, generate_session_id


@pytest.fixture
async def store(settings) -> CapsuleStore:
    store = CapsuleStore(settings)
    await store.initialize()
    return store


def make_record(**overrides) -> CapsuleRecord:
    data = dict(
        session_id="",
        mode="slim",
        title="FastAPI auth",
        project="Portal",
        capsule=Capsule(
            project="FastAPI authentication system",
            decisions=["PostgreSQL over a new datastore"],
            constraints=["No Redis until Q4"],
            next_objective="Finish the refresh endpoint",
        ),
        raw_tokens=94_200,
        compressed_tokens=680,
        reduction_pct=99.28,
    )
    data.update(overrides)
    return CapsuleRecord(**data)


# --- ids and schema --------------------------------------------------------


def test_session_ids_are_eight_unambiguous_characters():
    for _ in range(50):
        session_id = generate_session_id()
        assert len(session_id) == 8
        assert re.fullmatch(r"[A-HJ-NP-Z2-9]{8}", session_id)


def test_session_ids_are_not_repeated():
    ids = {generate_session_id() for _ in range(500)}
    assert len(ids) == 500


async def test_database_file_and_schema_created_on_demand(settings):
    store = CapsuleStore(settings)
    assert not store.db_path.exists()
    await store.initialize()
    assert store.db_path.exists()
    assert await store.schema_version() == "1"


async def test_initialize_is_idempotent(store):
    await store.initialize()
    await store.initialize()
    assert await store.count() == 0


# --- create / get ----------------------------------------------------------


async def test_create_allocates_id_and_round_trips(store):
    created = await store.create(make_record())
    assert created.session_id

    fetched = await store.get(created.session_id)
    assert fetched is not None
    assert fetched.capsule.decisions == ["PostgreSQL over a new datastore"]
    assert fetched.capsule.next_objective == "Finish the refresh endpoint"
    assert fetched.raw_tokens == 94_200
    assert fetched.tokens_saved == 93_520
    assert fetched.version == 1


async def test_explicit_session_id_is_kept(store):
    created = await store.create(make_record(session_id="ABCD2345"))
    assert created.session_id == "ABCD2345"


async def test_get_is_case_insensitive_and_trims(store):
    created = await store.create(make_record())
    assert await store.get(f"  {created.session_id.lower()}  ") is not None


async def test_get_unknown_id_returns_none(store):
    assert await store.get("ZZZZZZZZ") is None


async def test_delete_removes_capsule(store):
    created = await store.create(make_record())
    assert await store.delete(created.session_id) is True
    assert await store.get(created.session_id) is None
    assert await store.delete(created.session_id) is False


# --- list ------------------------------------------------------------------


async def test_list_is_newest_first_and_limited(store):
    for index in range(5):
        await store.create(make_record(title=f"session {index}"))
    listed = await store.list(limit=3)
    assert len(listed) == 3
    timestamps = [record.updated_at for record in listed]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_list_filters_by_project(store):
    await store.create(make_record(project="Portal"))
    await store.create(make_record(project="Billing"))
    assert len(await store.list(project="Bill")) == 1
    assert len(await store.list()) == 2


async def test_list_offset(store):
    for _ in range(4):
        await store.create(make_record())
    assert len(await store.list(limit=10, offset=2)) == 2


# --- update / versioning ---------------------------------------------------


async def test_update_bumps_version_and_archives_previous(store):
    created = await store.create(make_record())
    updated = await store.update(
        created.session_id,
        Capsule(project="FastAPI auth", next_objective="Write the Alembic migration"),
        note="second work block",
    )
    assert updated.version == 2
    assert updated.capsule.next_objective == "Write the Alembic migration"

    history = await store.versions(created.session_id)
    assert len(history) == 1
    assert history[0].version == 1
    assert history[0].capsule.next_objective == "Finish the refresh endpoint"
    assert history[0].note == "second work block"


async def test_update_keeps_unspecified_fields(store):
    created = await store.create(make_record())
    updated = await store.update(created.session_id, Capsule(project="x"))
    assert updated.raw_tokens == created.raw_tokens
    assert updated.title == created.title
    assert updated.created_at == created.created_at


async def test_repeated_updates_accumulate_history(store):
    created = await store.create(make_record())
    for index in range(3):
        await store.update(created.session_id, Capsule(next_objective=f"step {index}"))
    final = await store.get(created.session_id)
    assert final.version == 4
    assert len(await store.versions(created.session_id)) == 3


async def test_update_unknown_capsule_raises(store):
    with pytest.raises(CapsuleNotFoundError):
        await store.update("ZZZZZZZZ", Capsule())


async def test_deleting_capsule_cascades_to_versions(store):
    created = await store.create(make_record())
    await store.update(created.session_id, Capsule(next_objective="next"))
    await store.delete(created.session_id)
    assert await store.versions(created.session_id) == []


# --- restore tracking ------------------------------------------------------


async def test_mark_restored_increments_counter(store):
    created = await store.create(make_record())
    await store.mark_restored(created.session_id)
    await store.mark_restored(created.session_id)
    record = await store.get(created.session_id)
    assert record.restore_count == 2
    assert record.last_restored_at is not None


# --- search ----------------------------------------------------------------


async def test_search_matches_capsule_body(store):
    await store.create(make_record())
    await store.create(
        make_record(
            title="Billing rewrite",
            project="Billing",
            capsule=Capsule(decisions=["Stripe over Adyen"], next_objective="Invoices"),
        )
    )
    assert len(await store.search("postgresql")) == 1
    assert len(await store.search("stripe")) == 1
    assert len(await store.search("nothing here")) == 0


async def test_search_is_case_insensitive_and_covers_metadata(store):
    created = await store.create(make_record())
    assert len(await store.search("PORTAL")) == 1
    assert len(await store.search(created.session_id)) == 1


# --- stats -----------------------------------------------------------------


async def test_stats_on_empty_store(store):
    stats = await store.stats()
    assert stats["total_sessions"] == 0
    assert stats["total_tokens_saved"] == 0
    assert stats["overall_efficiency_pct"] == 0.0
    assert stats["by_mode"] == {}


async def test_stats_aggregate_correctly(store):
    await store.create(make_record(raw_tokens=1000, compressed_tokens=100, reduction_pct=90.0))
    await store.create(
        make_record(mode="deep", raw_tokens=3000, compressed_tokens=300, reduction_pct=90.0)
    )
    stats = await store.stats()
    assert stats["total_sessions"] == 2
    assert stats["total_raw_tokens"] == 4000
    assert stats["total_compressed_tokens"] == 400
    assert stats["total_tokens_saved"] == 3600
    assert stats["overall_efficiency_pct"] == 90.0
    assert stats["avg_reduction_pct"] == 90.0
    assert stats["by_mode"]["slim"]["sessions"] == 1
    assert stats["by_mode"]["deep"]["tokens_saved"] == 2700


async def test_export_rows_returns_plain_dicts(store):
    await store.create(make_record())
    rows = await store.export_rows()
    assert len(rows) == 1
    assert rows[0]["capsule"]["decisions"] == ["PostgreSQL over a new datastore"]
