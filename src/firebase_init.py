"""
Firebase Admin SDK initialization.

Expects GOOGLE_APPLICATION_CREDENTIALS env var pointing to a service account JSON.
If not set, falls back to Application Default Credentials (ADC).
"""

from __future__ import annotations

import logging
import os

import firebase_admin  # type: ignore[import-untyped]
from firebase_admin import credentials  # type: ignore[import-untyped]

logger = logging.getLogger("research_match.firebase")

_app: firebase_admin.App | None = None


def init_firebase() -> firebase_admin.App:
    """Initialize Firebase Admin SDK (idempotent)."""
    global _app
    if _app is not None:
        return _app

    cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred_path and os.path.isfile(cred_path):
        cred = credentials.Certificate(cred_path)
        _app = firebase_admin.initialize_app(cred)
        logger.info("Firebase initialized with service account: %s", cred_path)
    else:
        # Application Default Credentials (e.g., Cloud Run, GCE, emulator)
        _app = firebase_admin.initialize_app()
        logger.info("Firebase initialized with Application Default Credentials")

    return _app
