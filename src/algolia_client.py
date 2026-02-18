"""
Algolia client initialization and index configuration.

Environment variables:
- ALGOLIA_APP_ID: Algolia application ID
- ALGOLIA_API_KEY: Algolia admin/write API key
- ALGOLIA_INDEX_NAME: Index name (default: research_commits)

The Algolia index stores research commits for fast full-text search
in cold_search. Searchable attributes: domain, subdomain, problem,
hypothesis, pseudonym. Facets: domain, overall_solidity.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("research_match.algolia")

try:
    from algoliasearch.search.client import SearchClientSync  # type: ignore[import-untyped]
    from algoliasearch.search.models.index_settings import IndexSettings  # type: ignore[import-untyped]
    HAS_ALGOLIA = True
except ImportError:
    HAS_ALGOLIA = False


def init_algolia() -> Optional[Any]:
    """Initialize Algolia client and configure index settings.

    Returns the SearchClientSync instance, or None if not configured.
    """
    if not HAS_ALGOLIA:
        logger.info("Algolia SDK not installed — search will use Firestore fallback")
        return None

    app_id = os.environ.get("ALGOLIA_APP_ID", "")
    api_key = os.environ.get("ALGOLIA_API_KEY", "")
    index_name = os.environ.get("ALGOLIA_INDEX_NAME", "research_commits")

    if not app_id or not api_key:
        logger.info("Algolia credentials not configured — search will use Firestore fallback")
        return None

    client = SearchClientSync(app_id, api_key)

    # Configure index settings (idempotent)
    try:
        client.set_settings(
            index_name=index_name,
            index_settings=IndexSettings(
                searchable_attributes=[
                    "domain",
                    "subdomain",
                    "problem",
                    "hypothesis",
                    "pseudonym",
                ],
                attributes_for_faceting=[
                    "filterOnly(domain)",
                    "filterOnly(overall_solidity)",
                ],
                custom_ranking=[
                    "desc(ot_score)",
                    "desc(ofc_score)",
                ],
            ),
        )
        logger.info("Algolia index '%s' configured", index_name)
    except Exception as e:
        logger.warning("Failed to configure Algolia index settings: %s", e)

    return client
