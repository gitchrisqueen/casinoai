"""Parsing-layer tests using a tiny generated PDF (no network, no LLM)."""

import pymupdf
import pytest

from casinoai.parsing import parse_pdf
from casinoai.parsing.parser import ParsedDoc


@pytest.fixture
def tiny_pdf(tmp_path):
    path = tmp_path / "strategy.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Bet one unit on red. Double after every loss.")
    doc.save(str(path))
    doc.close()
    return path


def test_parse_produces_markdown_and_sidecar(tiny_pdf, tmp_path):
    cache = tmp_path / "parsed"
    doc = parse_pdf(tiny_pdf, cache_dir=cache, parser="pymupdf4llm")
    assert "Double after every loss" in (cache / f"{tiny_pdf.stem}-{doc.sha256[:8]}.md").read_text()
    assert doc.n_chars > 0
    meta = cache / f"{tiny_pdf.stem}-{doc.sha256[:8]}.json"
    assert ParsedDoc.model_validate_json(meta.read_text()) == doc


def test_cache_hit_skips_reparse(tiny_pdf, tmp_path, monkeypatch):
    cache = tmp_path / "parsed"
    first = parse_pdf(tiny_pdf, cache_dir=cache, parser="pymupdf4llm")

    def boom(_):
        raise AssertionError("cache miss — parser was called again")

    monkeypatch.setattr("casinoai.parsing.parser._parse_with_pymupdf", boom)
    second = parse_pdf(tiny_pdf, cache_dir=cache, parser="pymupdf4llm")
    assert second == first


def test_content_change_busts_cache(tiny_pdf, tmp_path):
    cache = tmp_path / "parsed"
    first = parse_pdf(tiny_pdf, cache_dir=cache, parser="pymupdf4llm")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Completely different strategy.")
    doc.save(str(tiny_pdf))
    doc.close()
    second = parse_pdf(tiny_pdf, cache_dir=cache, parser="pymupdf4llm")
    assert second.sha256 != first.sha256


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        parse_pdf(tmp_path / "nope.pdf")
