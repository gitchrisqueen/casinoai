"""Registry of calibrated table layouts, keyed by the game URL.

A layout is stored once per table and looked up automatically from the URL you
pass to auto-play, so you calibrate a table once and every later run just finds
it. The id is derived from the URL (normalised, then hashed) so the same table
always maps to the same file, and two different tables never collide.

If a site redesigns its game the stored points stop working; `mark_stale()`
records that (auto-play flags it when the table stops responding) and the
operator re-calibrates — confirming what still matches and only re-clicking what
moved. See casinoai.live.vision for the LLM-driven proposal step.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from casinoai.live.autoplay import (
    TableLayout,
    is_calibrated,
    load_layout,
    needs_attention,
    save_layout,
)

DEFAULT_REGISTRY = Path("configs/table_layouts")


def normalise_url(url: str) -> str:
    """Canonical form for keying: scheme/query/fragment and trailing slashes are
    incidental, so http(s)://Casino.Guru/x/ and https://casino.guru/x?a=1 are the
    same table."""
    parts = urlsplit((url or "").strip())
    host = (parts.netloc or "").lower().removeprefix("www.")
    path = (parts.path or "").rstrip("/")
    if not host:  # bare string, not a URL
        return (url or "").strip().lower().rstrip("/")
    return f"{host}{path}"


def layout_id(url: str) -> str:
    """Stable, human-readable id for a table URL: slug + short hash of the
    canonical URL (the hash keeps distinct tables from colliding after slugging)."""
    canon = normalise_url(url)
    slug = re.sub(r"[^a-z0-9]+", "-", canon).strip("-")[:48] or "table"
    digest = hashlib.sha256(canon.encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def layout_path(url: str, registry: Path = DEFAULT_REGISTRY) -> Path:
    return Path(registry) / f"{layout_id(url)}.yaml"


def find_layout(url: str, registry: Path = DEFAULT_REGISTRY) -> TableLayout | None:
    """The stored layout for this table, or None if it's never been calibrated."""
    p = layout_path(url, registry)
    return load_layout(p) if p.exists() else None


def store_layout(layout: TableLayout, registry: Path = DEFAULT_REGISTRY) -> Path:
    """Persist a layout under its URL-derived id, stamping the calibration time."""
    layout.id = layout_id(layout.url)
    layout.calibrated_at = datetime.now(UTC).isoformat(timespec="seconds")
    return save_layout(layout, layout_path(layout.url, registry))


def mark_stale(url: str, registry: Path = DEFAULT_REGISTRY, stale: bool = True) -> Path | None:
    """Flag a table as needing re-calibration (the site changed / it stopped
    responding). Returns the path written, or None if there's nothing stored."""
    layout = find_layout(url, registry)
    if layout is None:
        return None
    layout.stale = stale
    return save_layout(layout, layout_path(url, registry))


def status_of(layout: TableLayout) -> str:
    if layout.stale:
        return "STALE — re-calibrate"
    pending = needs_attention(layout)
    if pending:
        return f"needs {len(pending)} control(s): {', '.join(pending)}"
    return "ready" if is_calibrated(layout) else "incomplete"


def list_layouts(registry: Path = DEFAULT_REGISTRY) -> list[TableLayout]:
    """Every calibrated table, for `--list-layouts`."""
    reg = Path(registry)
    if not reg.exists():
        return []
    out: list[TableLayout] = []
    for p in sorted(reg.glob("*.yaml")):
        try:
            out.append(load_layout(p))
        except Exception:  # a stub/hand-edited file shouldn't break the listing
            continue
    return out


def render_registry(registry: Path = DEFAULT_REGISTRY) -> str:
    layouts = list_layouts(registry)
    if not layouts:
        return "No calibrated tables yet. Calibrate one with --calibrate."
    lines = [f"{len(layouts)} calibrated table(s) in {registry}:"]
    for lay in layouts:
        lines.append(f"  [{lay.game}] {lay.name}")
        lines.append(f"      url:    {lay.url or '(none)'}")
        lines.append(f"      id:     {lay.id}")
        lines.append(f"      when:   {lay.calibrated_at or '(unknown)'}")
        lines.append(f"      status: {status_of(lay)}")
    return "\n".join(lines)
