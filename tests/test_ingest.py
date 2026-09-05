"""Multi-format file ingestion."""

from __future__ import annotations

import pytest

from contextslim.errors import IngestionError
from contextslim.ingest import SUPPORTED_EXTENSIONS, FileIngestor


@pytest.fixture
def ingestor(settings) -> FileIngestor:
    return FileIngestor(settings)


def write(tmp_path, name: str, content: str):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# --- happy paths -----------------------------------------------------------


def test_markdown_file_is_ingested(ingestor, tmp_path):
    path = write(tmp_path, "notes.md", "# Title\n\nSome    notes about   PostgreSQL.")
    result = ingestor.ingest(str(path))

    assert "PostgreSQL" in result.markdown
    assert result.name == "notes.md"
    assert result.extension == ".md"
    assert result.tokens > 0
    assert result.size_bytes > 0


def test_output_is_minified(ingestor, tmp_path):
    path = write(tmp_path, "notes.txt", "a     b\n\n\n\n\nc   ")
    assert ingestor.ingest(str(path)).markdown == "a b\n\nc"


def test_csv_content_survives(ingestor, tmp_path):
    path = write(tmp_path, "data.csv", "name,role\nalex,lead\npriya,backend")
    markdown = ingestor.ingest(str(path)).markdown
    assert "alex" in markdown and "priya" in markdown


def test_plain_text_reader_used_when_markitdown_missing(ingestor, tmp_path):
    ingestor._markitdown_failed = True  # simulate the optional dep being absent
    path = write(tmp_path, "notes.txt", "decision: use SQLite")
    result = ingestor.ingest(str(path))
    assert result.converter == "plain-text"
    assert "SQLite" in result.markdown


def test_html_uses_markitdown_when_available(ingestor, tmp_path):
    if not ingestor.markitdown_available:
        pytest.skip("MarkItDown not installed")
    path = write(
        tmp_path,
        "page.html",
        "<html><body><h1>Auth design</h1><p>We chose RS256.</p></body></html>",
    )
    result = ingestor.ingest(str(path))
    assert "Auth design" in result.markdown
    assert "RS256" in result.markdown
    assert "<h1>" not in result.markdown  # HTML noise stripped


def test_tilde_and_relative_paths_resolve(ingestor, tmp_path, monkeypatch):
    write(tmp_path, "rel.md", "relative content here")
    monkeypatch.chdir(tmp_path)
    assert "relative content" in ingestor.ingest("rel.md").markdown


# --- failures --------------------------------------------------------------


def test_missing_file_raises(ingestor, tmp_path):
    with pytest.raises(IngestionError, match="not found"):
        ingestor.ingest(str(tmp_path / "nope.md"))


def test_directory_raises(ingestor, tmp_path):
    with pytest.raises(IngestionError, match="directory"):
        ingestor.ingest(str(tmp_path))


def test_unsupported_extension_raises(ingestor, tmp_path):
    path = write(tmp_path, "binary.exe", "nope")
    with pytest.raises(IngestionError, match="Unsupported file type"):
        ingestor.ingest(str(path))


def test_oversized_file_raises(settings, tmp_path):
    settings.max_file_mb = 1
    ingestor = FileIngestor(settings)
    path = tmp_path / "big.txt"
    path.write_text("x" * (2 * 1024 * 1024), encoding="utf-8")
    with pytest.raises(IngestionError, match="MB limit"):
        ingestor.ingest(str(path))


# --- batches ---------------------------------------------------------------


def test_ingest_many_combines_documents(ingestor, tmp_path):
    write(tmp_path, "one.md", "First document about Argon2id hashing.")
    write(tmp_path, "two.txt", "Second document about JWT rotation.")
    report = ingestor.ingest_many([str(tmp_path / "one.md"), str(tmp_path / "two.txt")])

    assert len(report.files) == 2
    assert report.errors == []
    assert "Argon2id" in report.markdown
    assert "JWT rotation" in report.markdown
    assert "# Source document: one.md" in report.markdown
    assert report.total_tokens > 0


def test_ingest_many_reports_failures_without_losing_successes(ingestor, tmp_path):
    write(tmp_path, "good.md", "This document survived ingestion.")
    report = ingestor.ingest_many(
        [str(tmp_path / "good.md"), str(tmp_path / "missing.pdf")]
    )

    assert len(report.files) == 1
    assert len(report.errors) == 1
    assert "not found" in report.errors[0]
    assert "survived ingestion" in report.markdown


def test_ingest_many_with_no_paths(ingestor):
    report = ingestor.ingest_many([])
    assert report.markdown == ""
    assert report.as_dict()["file_count"] == 0


def test_report_dict_shape(ingestor, tmp_path):
    write(tmp_path, "one.md", "Document content for the report shape test.")
    report = ingestor.ingest_many([str(tmp_path / "one.md")])
    payload = report.as_dict()
    assert payload["file_count"] == 1
    assert payload["files"][0]["name"] == "one.md"
    assert payload["files"][0]["tokens"] > 0


def test_documented_formats_are_supported():
    for extension in (".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md"):
        assert extension in SUPPORTED_EXTENSIONS
