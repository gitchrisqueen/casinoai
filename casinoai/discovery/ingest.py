"""Ingest a discovered web strategy into the standard parsing cache.

A strategy found online (a page's text, a forum post, a transcript) becomes a
ParsedDoc — the exact shape the PDF parser emits — so the existing
`extract → review → backtest` pipeline runs on it unchanged.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from casinoai.parsing.parser import DEFAULT_CACHE_DIR, ParsedDoc


def ingest_text(
    name: str,
    text: str,
    source_url: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> ParsedDoc:
    """Write `text` as cached markdown + a ParsedDoc sidecar keyed by content
    hash. Returns the ParsedDoc (its .json sidecar path feeds `casinoai extract`)."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    slug = name.lower().replace(" ", "-").replace("/", "-")
    stem = f"{slug}-{digest[:8]}"
    cache_dir.mkdir(parents=True, exist_ok=True)
    md_path = cache_dir / f"{stem}.md"
    meta_path = cache_dir / f"{stem}.json"

    # Preserve provenance at the top of the markdown so extraction sees it.
    header = f"# {name}\n\nSource: {source_url}\n\n---\n\n"
    md_path.write_text(header + text)

    doc = ParsedDoc(
        source_path=source_url,
        sha256=digest,
        parser="web-ingest",
        markdown_path=str(md_path),
        parsed_at=datetime.now(UTC).isoformat(),
        n_chars=len(text),
    )
    meta_path.write_text(json.dumps(doc.model_dump(), indent=2))
    return doc
