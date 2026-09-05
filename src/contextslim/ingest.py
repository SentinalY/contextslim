"""Layer 1 - multi-format file ingestion.

Documents are converted to clean Markdown *before* anything reaches a model,
so the token bill starts lower. MarkItDown does the conversion because it
preserves structure - headings, tables, lists - instead of flattening a
document into a wall of text.

MarkItDown is imported lazily and plain-text formats have a built-in reader,
so a missing optional dependency costs you one file type rather than the whole
server.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from .config import Settings, get_settings
from .errors import IngestionError
from .minify import minify
from .paths import expand
from .tokens import count_tokens

logger = logging.getLogger(__name__)

#: Formats the processor accepts. MarkItDown handles the rich ones; the
#: plain-text ones are readable even without it.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".pptx",
        ".csv",
        ".tsv",
        ".txt",
        ".md",
        ".markdown",
        ".json",
        ".html",
        ".htm",
        ".xml",
        ".rst",
        ".log",
    }
)

_PLAIN_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".rst", ".log", ".xml"}
)


@dataclass
class IngestedFile:
    """One converted document."""

    path: str
    name: str
    extension: str
    markdown: str
    tokens: int
    size_bytes: int
    converter: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "extension": self.extension,
            "tokens": self.tokens,
            "size_bytes": self.size_bytes,
            "converter": self.converter,
        }


@dataclass
class IngestionReport:
    """The result of ingesting a batch of files."""

    markdown: str
    files: List[IngestedFile]
    errors: List[str]

    @property
    def total_tokens(self) -> int:
        return sum(f.tokens for f in self.files)

    def as_dict(self) -> dict:
        return {
            "files": [f.as_dict() for f in self.files],
            "file_count": len(self.files),
            "total_tokens": self.total_tokens,
            "errors": self.errors,
        }


class FileIngestor:
    """Converts PDF / DOCX / XLSX / CSV / TXT / MD into clean Markdown."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._markitdown = None
        self._markitdown_failed = False

    # ------------------------------------------------------------------
    # Converters
    # ------------------------------------------------------------------
    def _get_markitdown(self):
        if self._markitdown is not None or self._markitdown_failed:
            return self._markitdown
        try:
            from markitdown import MarkItDown

            self._markitdown = MarkItDown()
        except Exception as exc:
            self._markitdown_failed = True
            logger.warning("MarkItDown unavailable (%s); plain text only", exc)
        return self._markitdown

    @property
    def markitdown_available(self) -> bool:
        return self._get_markitdown() is not None

    def _convert(self, path: Path) -> Tuple[str, str]:
        """Return ``(markdown, converter_name)`` for one file."""
        extension = path.suffix.lower()

        converter = self._get_markitdown()
        if converter is not None:
            try:
                result = converter.convert(str(path))
                text = getattr(result, "text_content", None) or getattr(result, "markdown", "")
                if text and text.strip():
                    return text, "markitdown"
                logger.warning("MarkItDown produced no text for %s", path.name)
            except Exception as exc:
                logger.warning("MarkItDown failed on %s (%s)", path.name, exc)

        if extension in _PLAIN_TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8", errors="replace"), "plain-text"

        raise IngestionError(
            f"Could not convert '{path.name}'. Install the MarkItDown extras for "
            f"'{extension}' files, or supply the content as text."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest(self, file_path: str) -> IngestedFile:
        """Convert a single file to minified Markdown."""
        path = expand(file_path)

        if not path.exists():
            raise IngestionError(f"File not found: {file_path}")
        if path.is_dir():
            raise IngestionError(f"Expected a file but got a directory: {file_path}")

        extension = path.suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise IngestionError(
                f"Unsupported file type '{extension or 'none'}'. Supported: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            )

        size = path.stat().st_size
        limit = self.settings.max_file_mb * 1024 * 1024
        if size > limit:
            raise IngestionError(
                f"'{path.name}' is {size / 1024 / 1024:.1f} MB, over the "
                f"{self.settings.max_file_mb} MB limit "
                "(raise CONTEXTSLIM_MAX_FILE_MB to allow it)."
            )

        raw, converter = self._convert(path)
        markdown = minify(raw)
        return IngestedFile(
            path=str(path),
            name=path.name,
            extension=extension,
            markdown=markdown,
            tokens=count_tokens(markdown, self.settings.token_encoding),
            size_bytes=size,
            converter=converter,
        )

    def ingest_many(self, file_paths: Sequence[str]) -> IngestionReport:
        """Convert several files, collecting failures instead of raising.

        One unreadable attachment should not lose the other nine, so errors
        are reported alongside whatever succeeded.
        """
        files: List[IngestedFile] = []
        errors: List[str] = []

        for file_path in file_paths or []:
            try:
                files.append(self.ingest(file_path))
            except IngestionError as exc:
                errors.append(str(exc))
            except Exception as exc:  # pragma: no cover - unexpected reader bug
                errors.append(f"{file_path}: {exc.__class__.__name__}: {exc}")

        blocks: Iterable[str] = (
            f"# Source document: {f.name}\n\n{f.markdown}" for f in files
        )
        return IngestionReport(markdown="\n\n".join(blocks), files=files, errors=errors)
