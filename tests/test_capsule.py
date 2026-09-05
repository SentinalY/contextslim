"""Capsule model: rendering, parsing, merging."""

from __future__ import annotations

from contextslim.capsule import SECTION_ORDER, Capsule


def make_capsule() -> Capsule:
    return Capsule(
        project="FastAPI authentication system for an internal portal",
        completed=["User model written", "Argon2id hashing wired"],
        decisions=["PostgreSQL over a new datastore", "RS256 over HS256"],
        current_state=["Refresh endpoint skeleton in place"],
        next_objective="Finish the JWT refresh endpoint with reuse detection",
        constraints=["No Redis until the Q4 datacentre migration"],
    )


def test_render_contains_all_six_sections():
    rendered = make_capsule().render()
    for section in SECTION_ORDER:
        assert f"## {section}" in rendered


def test_render_marks_empty_sections_explicitly():
    rendered = Capsule().render()
    assert rendered.count("(none recorded)") == len(SECTION_ORDER)


def test_render_parse_round_trip():
    original = make_capsule()
    parsed = Capsule.parse(original.render())
    assert parsed.model_dump() == original.model_dump()


def test_parse_ignores_surrounding_noise():
    text = "chatter before\n\n" + make_capsule().render() + "\n\ntrailing chatter"
    parsed = Capsule.parse(text)
    assert parsed.next_objective.startswith("Finish the JWT refresh endpoint")
    assert len(parsed.decisions) == 2


def test_parse_empty_returns_empty_capsule():
    assert Capsule.parse("").is_empty
    assert Capsule.parse("no headings at all").is_empty


def test_parse_round_trip_of_empty_capsule_stays_empty():
    assert Capsule.parse(Capsule().render()).is_empty


def test_bullets_are_stripped_on_input():
    capsule = Capsule(decisions=["- chose PostgreSQL", "* used Argon2id", "1. RS256"])
    assert capsule.decisions == ["chose PostgreSQL", "used Argon2id", "RS256"]


def test_duplicate_items_removed_case_insensitively():
    capsule = Capsule(completed=["Wrote model", "wrote model", "Wrote  model "])
    assert capsule.completed == ["Wrote model"]


def test_string_input_is_split_into_lines():
    capsule = Capsule(constraints="- no redis\n- no open signup")
    assert capsule.constraints == ["no redis", "no open signup"]


def test_text_fields_collapse_whitespace():
    capsule = Capsule(project="  a   multi\nline   project  ")
    assert capsule.project == "a multi line project"


def test_restore_prompt_carries_identity_and_instructions():
    prompt = make_capsule().to_restore_prompt(
        "A3F2K9B1", created_at="2026-09-04T10:00:00Z", mode="deep", version=2
    )
    assert "A3F2K9B1" in prompt
    assert "deep mode" in prompt
    assert "v2" in prompt
    assert "NEXT OBJECTIVE" in prompt
    assert "CONSTRAINTS" in prompt
    assert "do not contradict" in prompt.lower()


def test_restore_prompt_omits_version_one():
    prompt = make_capsule().to_restore_prompt("ABC12345", version=1)
    assert "v1" not in prompt


def test_merge_accumulates_lists_and_replaces_focus():
    original = make_capsule()
    update = Capsule(
        completed=["Rate limiter table added"],
        decisions=["PostgreSQL over a new datastore"],  # duplicate, must collapse
        current_state=["Reuse detection under test"],
        next_objective="Write the Alembic migration",
        constraints=["Quarterly key rotation"],
    )
    merged = original.merge(update)

    assert "Rate limiter table added" in merged.completed
    assert "User model written" in merged.completed
    assert merged.decisions.count("PostgreSQL over a new datastore") == 1
    assert merged.current_state == ["Reuse detection under test"]
    assert merged.next_objective == "Write the Alembic migration"
    assert len(merged.constraints) == 2
    assert merged.project == original.project  # unchanged when update omits it


def test_merge_keeps_previous_focus_when_update_is_silent():
    merged = make_capsule().merge(Capsule(completed=["something"]))
    assert merged.next_objective == "Finish the JWT refresh endpoint with reuse detection"
    assert merged.current_state == ["Refresh endpoint skeleton in place"]


def test_item_count_and_is_empty():
    assert Capsule().is_empty is True
    assert Capsule().item_count == 0
    assert make_capsule().is_empty is False
    assert make_capsule().item_count == 8
