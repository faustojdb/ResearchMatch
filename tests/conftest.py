"""
Shared fixtures for Research Match Firestore tests.

Requires Firestore Emulator running on localhost:8080:
    firebase emulators:start --only firestore
"""

from __future__ import annotations

import os
import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio

# Point the Firestore SDK at the local emulator BEFORE any imports
os.environ["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8080"
os.environ["GCLOUD_PROJECT"] = "research-match-dev"
# Ensure Algolia is disabled during tests (no env vars = Firestore-only search)
os.environ.pop("ALGOLIA_APP_ID", None)
os.environ.pop("ALGOLIA_API_KEY", None)

from src.firestore_datastore import FirestoreDataStore  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def ds() -> AsyncGenerator[FirestoreDataStore, None]:
    """Fresh FirestoreDataStore connected to emulator, cleaned after each test."""
    store = FirestoreDataStore()
    await store.initialize()
    yield store
    # Cleanup: delete all documents from all top-level collections
    await _clear_emulator(store)
    await store.close()


async def _clear_emulator(store: FirestoreDataStore) -> None:
    """Delete all documents from emulator to ensure test isolation."""
    top_level_collections = [
        "users",
        "research_commits",
        "matches",
        "collaboration_requests",
        "teams",
        "collaboration_contracts",
        "bug_reports",
    ]
    for coll_name in top_level_collections:
        coll_ref = store.db.collection(coll_name)
        docs = coll_ref.list_documents()
        for doc_ref in docs:
            # Delete subcollections first (teams have many)
            for subcoll in doc_ref.collections():
                for subdoc in subcoll.list_documents():
                    subdoc.delete()
            doc_ref.delete()
