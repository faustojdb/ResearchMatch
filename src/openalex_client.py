"""OpenAlex literature client for literature-grounded novelty scoring.

OpenAlex (https://openalex.org) is a free, open catalog of ~250M scholarly works.
The API requires NO key. We use it to ground the "novelty" signal of a Research
Commit in the *real published literature* instead of only comparing against other
registered users, so an originality score means "how different is this from prior
art" rather than "how many buzzwords did you type".

Design goals:
- Zero new dependencies: uses urllib from the standard library.
- Fails soft: any network/parse error returns an empty list, and the caller falls
  back to a neutral "unscored" state rather than fabricating a number.
- Polite: honors the OpenAlex "polite pool" via an optional mailto parameter.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

_logger = logging.getLogger("research_match.openalex")

OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_TIMEOUT = 8          # seconds per request
DEFAULT_LIMIT = 15           # works fetched per query
MAX_ABSTRACT_CHARS = 2000    # cap reconstructed abstract length


def _reconstruct_abstract(inverted_index: Optional[Dict[str, List[int]]]) -> str:
    """Rebuild plain-text abstract from OpenAlex's abstract_inverted_index.

    The index maps each word to the list of positions it occupies. We place every
    word at its positions and join in order. Returns "" if the index is missing.
    """
    if not inverted_index:
        return ""
    positioned: List[tuple] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            positioned.append((pos, word))
    if not positioned:
        return ""
    positioned.sort(key=lambda x: x[0])
    text = " ".join(word for _, word in positioned)
    return text[:MAX_ABSTRACT_CHARS]


class OpenAlexClient:
    """Minimal, dependency-free client for OpenAlex works search."""

    def __init__(self, mailto: Optional[str] = None, timeout: int = DEFAULT_TIMEOUT):
        # The polite-pool contact is optional; only the app's own contact is ever sent,
        # never any user research content.
        self.mailto = mailto or os.environ.get("RESEARCH_MATCH_OPENALEX_MAILTO", "")
        self.timeout = timeout

    def is_available(self) -> bool:
        """OpenAlex needs no key; treat it as available unless explicitly disabled."""
        return os.environ.get("RESEARCH_MATCH_DISABLE_OPENALEX", "").lower() not in ("1", "true", "yes")

    def search_works(self, query: str, limit: int = DEFAULT_LIMIT) -> List[Dict]:
        """Search OpenAlex for works matching `query`.

        Returns a list of {id, title, abstract, year, cited_by_count}. Never raises —
        returns [] on any error so novelty scoring degrades gracefully offline.
        """
        query = (query or "").strip()
        if not query or not self.is_available():
            return []

        params = {
            "search": query[:400],
            "per_page": max(1, min(limit, 50)),
            "select": "id,title,publication_year,cited_by_count,abstract_inverted_index",
        }
        if self.mailto:
            params["mailto"] = self.mailto
        url = f"{OPENALEX_WORKS_URL}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "ResearchMatch-MCP (mailto:%s)" % (self.mailto or "n/a")}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001 — fail soft on any network/parse error
            _logger.warning("OpenAlex search failed for %r: %s", query[:60], e)
            return []

        works: List[Dict] = []
        for item in data.get("results", []):
            abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))
            title = item.get("title") or ""
            if not (title or abstract):
                continue
            works.append({
                "id": item.get("id", ""),
                "title": title,
                "abstract": abstract,
                "year": item.get("publication_year"),
                "cited_by_count": item.get("cited_by_count", 0),
            })
        _logger.debug("OpenAlex returned %d works for %r", len(works), query[:60])
        return works

    @staticmethod
    def work_text(work: Dict) -> str:
        """Combine title + abstract into a single comparison string."""
        return f"{work.get('title', '')}. {work.get('abstract', '')}".strip()
