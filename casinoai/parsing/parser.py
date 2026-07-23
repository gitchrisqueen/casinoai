"""PDF → markdown parsing, cached in data/parsed/.

Parses once per unique file content (sha256-keyed cache). Docling is used
when installed (better table fidelity); PyMuPDF4LLM otherwise — Docling's
torch/onnxruntime stack has no wheels for Intel Macs, so it is an optional
extra rather than a hard dependency.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

DEFAULT_CACHE_DIR = Path("data/parsed")


class ParsedDoc(BaseModel):
    """Metadata sidecar for one parsed PDF; markdown lives next to it."""

    source_path: str
    sha256: str
    parser: str
    markdown_path: str
    parsed_at: str
    n_chars: int


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_with_docling(pdf_path: Path) -> str:
    from docling.document_converter import DocumentConverter

    result = DocumentConverter().convert(str(pdf_path))
    return result.document.export_to_markdown()


def _parse_with_pymupdf(pdf_path: Path) -> str:
    import pymupdf4llm

    return pymupdf4llm.to_markdown(str(pdf_path), show_progress=False)


def available_parser() -> str:
    try:
        import docling  # noqa: F401

        return "docling"
    except ImportError:
        return "pymupdf4llm"


def parse_pdf(
    pdf_path: Path,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    parser: str | None = None,
    force: bool = False,
) -> ParsedDoc:
    """Parse one PDF to markdown, reusing the cache when content is unchanged."""
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise FileNotFoundError(pdf_path)
    parser = parser or available_parser()

    digest = _sha256(pdf_path)
    stem = f"{pdf_path.stem}-{digest[:8]}"
    meta_path = cache_dir / f"{stem}.json"
    md_path = cache_dir / f"{stem}.md"

    if not force and meta_path.is_file() and md_path.is_file():
        cached = ParsedDoc.model_validate_json(meta_path.read_text())
        if cached.parser == parser:
            return cached

    if parser == "docling":
        markdown = _parse_with_docling(pdf_path)
    elif parser == "pymupdf4llm":
        markdown = _parse_with_pymupdf(pdf_path)
    else:
        raise ValueError(f"Unknown parser: {parser}")

    cache_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown)
    doc = ParsedDoc(
        source_path=str(pdf_path),
        sha256=digest,
        parser=parser,
        markdown_path=str(md_path),
        parsed_at=datetime.now(UTC).isoformat(),
        n_chars=len(markdown),
    )
    meta_path.write_text(json.dumps(doc.model_dump(), indent=2))
    return doc
