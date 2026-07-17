"""
Shared fixtures for Research Match Firestore tests.

Requires Firestore Emulator running on localhost:8080:
    firebase emulators:start --only firestore
"""

from __future__ import annotations

import os
import socket
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


# =====================================================================
# EMULATOR REACHABILITY GUARD
# =====================================================================
# The emulator-backed suites (test_firestore_datastore.py, test_flows_integration.py)
# open a real gRPC connection to FIRESTORE_EMULATOR_HOST. When the emulator is NOT
# running, the SDK retries for ~60s per operation before failing, which makes an
# offline `pytest` run hang for minutes. To keep offline runs fast, we probe the
# emulator port once at collection time and, if it is not accepting TCP connections,
# SKIP the emulator-dependent test modules with a clear message. The offline unit
# suites (test_engines.py, test_openalex.py) are never touched by this guard.

_EMULATOR_DEPENDENT_MODULES = (
    "test_firestore_datastore.py",
    "test_flows_integration.py",
)


def _emulator_reachable(timeout: float = 1.0) -> bool:
    """Return True if FIRESTORE_EMULATOR_HOST accepts a TCP connection."""
    host_port = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    if ":" not in host_port:
        return False
    host, _, port = host_port.rpartition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def pytest_collection_modifyitems(config, items):
    """Skip emulator-dependent tests when the Firestore emulator is unreachable.

    Runs after collection. If the emulator port is open we do nothing (the existing
    suite runs exactly as before). If it is closed, every test whose file is an
    emulator-dependent module is marked skipped so the run does not hang.
    """
    if _emulator_reachable():
        return
    skip_emulator = pytest.mark.skip(
        reason=(
            "Firestore emulator not reachable at "
            f"FIRESTORE_EMULATOR_HOST={os.environ.get('FIRESTORE_EMULATOR_HOST', '<unset>')}. "
            "Start it with `firebase emulators:start --only firestore` to run these tests."
        )
    )
    for item in items:
        filename = os.path.basename(str(getattr(item, "fspath", "")))
        if filename in _EMULATOR_DEPENDENT_MODULES:
            item.add_marker(skip_emulator)


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
