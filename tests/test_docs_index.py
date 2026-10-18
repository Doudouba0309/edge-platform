"""The documentation library must link only to existing local files."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and values.get("href"):
            self.hrefs.append(values["href"] or "")


def _links() -> list[str]:
    parser = _Links()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser.hrefs


def test_docs_index_links_resolve() -> None:
    missing: list[str] = []
    for href in _links():
        if href.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = urlsplit(href).path
        target = (INDEX.parent / path).resolve() if path else INDEX
        if not target.exists():
            missing.append(href)
    assert missing == []


def test_docs_index_does_not_link_removed_documents() -> None:
    hrefs = "\n".join(_links())
    assert "open-questions" not in hrefs
    assert "edge-platform-roadmap" not in hrefs
