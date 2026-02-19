"""
Research Match MCP Server
=========================
MCP Server that integrates Research Match into Claude.
Allows researchers to submit work, get originality scores,
find collaborators, rate collaborators, and manage collaboration requests.

v2.0 — Added: Rating system, solidity levels, reputation engine.
v2.2 — Added: Sentence-transformers semantic similarity, health endpoint, improved tool descriptions.

Usage:
    python research_match_server.py              # stdio transport (local)
    python research_match_server.py --http 8000   # HTTP transport (remote)
"""

import json
import uuid
import hashlib
import sqlite3
import os
import sys
import threading
import time
import functools
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from enum import Enum
import urllib.request
import urllib.parse
import logging
import tempfile
import shutil
import subprocess

import numpy as np
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict, field_validator

from .datastore import DataStore, Record


# =============================================================================
# LOGGING SETUP
# =============================================================================

_LOG_FORMAT = os.environ.get("RESEARCH_MATCH_LOG_FORMAT", "text")  # "json" or "text"
_LOG_LEVEL = os.environ.get("RESEARCH_MATCH_LOG_LEVEL", "INFO").upper()


class _JsonFormatter(logging.Formatter):
    """Structured JSON log formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "tool_name"):
            log_entry["tool"] = record.tool_name
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "extra_data"):
            log_entry["data"] = record.extra_data
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def _setup_logging() -> logging.Logger:
    """Configure structured logging based on environment variables."""
    logger = logging.getLogger("research_match")
    if logger.handlers:
        return logger  # Already configured

    handler = logging.StreamHandler()

    if _LOG_FORMAT == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))

    logger.addHandler(handler)
    logger.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
    return logger


_logger = _setup_logging()


def _log_tool_call(func):
    """Decorator that logs MCP tool calls with timing."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        tool_name = func.__name__
        _logger.info("Tool call started: %s", tool_name,
                      extra={"tool_name": tool_name} if _LOG_FORMAT == "json" else {})
        start = time.monotonic()
        try:
            result = await func(*args, **kwargs)
            elapsed = (time.monotonic() - start) * 1000
            _logger.info("Tool call completed: %s (%.1fms)", tool_name, elapsed,
                          extra={"tool_name": tool_name, "duration_ms": round(elapsed, 1)}
                          if _LOG_FORMAT == "json" else {})
            return result
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            _logger.error("Tool call failed: %s (%.1fms) — %s", tool_name, elapsed, e,
                           extra={"tool_name": tool_name, "duration_ms": round(elapsed, 1)}
                           if _LOG_FORMAT == "json" else {})
            raise

    return wrapper


# =============================================================================
# CONSTANTS
# =============================================================================

DB_PATH = os.environ.get("RESEARCH_MATCH_DB") or "research_match.db"
SERVER_VERSION = "3.0.0"

# Scoring weights for Theoretical Originality (OT)
OT_WEIGHTS = {
    "hypothesis_novelty": 0.30,
    "interdisciplinary_connections": 0.25,
    "adhoc_content": 0.30,
    "corpus_divergence": 0.15,
}

# Scoring weights for Formal-Computational Originality (OFC)
OFC_WEIGHTS = {
    "formal_method_originality": 0.25,
    "code_quality": 0.20,
    "validation_power": 0.25,
    "technical_sophistication": 0.15,
    "coverage": 0.15,
}

# Solidity level multipliers — affect how scores are weighted
# Higher solidity = more confidence in the score
SOLIDITY_MULTIPLIERS = {
    "proven": 1.0,        # Fully demonstrated, peer-reviewed or formally verified
    "functional": 0.85,   # Working code/data, reproducible but not formally proven
    "speculative": 0.60,  # Theoretical reasoning without full validation
    "adhoc": 0.40,        # Original intuition, preliminary ideas
    "cherry_picked": 0.30, # Curated from other sources (declared honestly)
}

# Semaphore thresholds (v2.3 calibrated)
GREEN_MUTUAL_THRESHOLD = 20      # Both >= 20 → GREEN fuerte
GREEN_MAX_GAIN_THRESHOLD = 40    # Max >= 40 para GREEN por complementariedad
GREEN_AVG_GAIN_THRESHOLD = 20    # Avg >= 20 para GREEN por complementariedad
GREEN_MIN_GAIN_FLOOR = 4         # Min >= 4 para GREEN (el debil gana algo real)
YELLOW_MAX_GAIN_THRESHOLD = 25   # Max >= 25 para YELLOW
YELLOW_MIN_GAIN_MODERATE = 5     # Min >= 5 para YELLOW moderado
YELLOW_AVG_THRESHOLD = 12        # Avg >= 12 para YELLOW moderado
WEAKNESS_BONUS_COEFFICIENT = 0.15

# Rating constants
RATING_MIN = 1
RATING_MAX = 5
MIN_RATINGS_FOR_REPUTATION = 2  # Need at least 2 ratings to affect reputation

# Reputation engine constants
REPUTATION_ALPHA = 0.2           # Exponential smoothing factor (higher = more weight on recent)
REPUTATION_WEIGHT_HONESTY = 0.50  # 50% weight on honesty
REPUTATION_WEIGHT_QUALITY = 0.30  # 30% weight on quality
REPUTATION_WEIGHT_EFFORT = 0.20   # 20% weight on effort
REPUTATION_LOW_HONESTY_THRESHOLD = 2.0   # Below this, harsh penalty applied
REPUTATION_LOW_HONESTY_PENALTY = 0.5     # Multiplier for dishonest users
REPUTATION_BONUS_MIN_RATINGS = 5         # Min ratings for consistency bonus
REPUTATION_BONUS_HONESTY_FLOOR = 4.0     # Min avg honesty for bonus
REPUTATION_BONUS_QUALITY_FLOOR = 3.5     # Min avg quality for bonus
REPUTATION_BONUS_MULTIPLIER = 1.1        # Bonus multiplier for consistent users

# Collaboration layer constants
MAX_OPEN_TICKETS_PER_USER_PER_TEAM = 5
TICKET_EFFORT_BONUS = 0.5
MAX_TICKET_TITLE_LENGTH = 200
MAX_TICKET_DESCRIPTION_LENGTH = 2000
MAX_PENDING_REVEALS_PER_TEAM = 10
LICENSE_STALE_DAYS = 30  # Days without reveal before team becomes "time-limited"
MAX_SHARED_FILES_PER_TEAM = 50
MAX_FILE_PATH_LENGTH = 500
MAX_FILE_DESCRIPTION_LENGTH = 500
RESHARING_PENALTY_HONESTY = 1.0  # Forced honesty score on re-sharing violation
DEEP_SEARCH_CLONE_TIMEOUT = 60          # seconds for git clone
DEEP_SEARCH_MAX_REPO_SIZE_MB = 500      # refuse repos larger than this

# Proforma constants
PROFORMA_VERSION = "1.0"
MAX_FILE_READ_CHARS = 8000              # max chars per file in prompt context
MAX_PROMPT_TOTAL_CHARS = 25000          # total prompt size cap
MAX_KEY_FILES = 6                       # max files included in prompt
NARRATIVE_JSON_MAX_LENGTH = 20000       # max length of narrative_json input

# Contract constants (NEED-08)
CONTRACT_VERSION = "1.0"
CONTRACT_DIR_NAME = ".research-match"
CONTRACT_FILE_PREFIX = "CONTRACT_"
GIT_COMMIT_HASH_PATTERN = r'^[0-9a-f]{40}$'
MAX_CONTRACT_CONFIRMATIONS_PER_TEAM = 20

LICENSE_TERMS = {
    "joint-equal": [
        "Both parties are co-authors with equal rights.",
        "Either party may publish with mandatory co-author credit.",
        "Derived works require consent from both parties.",
        "Neither party may sublicense without mutual agreement.",
    ],
    "joint-weighted": [
        "Both parties are co-authors with weighted rights.",
        "Contribution split reflects ticket resolution balance.",
        "Publishing rights proportional to contribution percentage.",
        "Split recalculates as collaboration evolves.",
    ],
    "advisory-only": [
        "Content owner retains full IP rights.",
        "Advisor receives acknowledgment credit only.",
        "Advisor may NOT publish or derive from shared content.",
        "Upgrade to joint-equal requires bilateral reveal.",
    ],
    "time-limited": [
        "Collaboration window has not progressed to active sharing.",
        "No IP rights transferred — team exists for coordination only.",
        "Use research_match_reveal_request to activate full collaboration.",
        "Team may be dissolved if no activity within 60 days.",
    ],
}

# Embedding model
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # 384 dims, ~90MB, fast


# =============================================================================
# EMBEDDING ENGINE (Lazy-loaded Sentence Transformers)
# =============================================================================

class EmbeddingEngine:
    """Provides semantic similarity via sentence-transformers.

    The model is lazy-loaded on first use to avoid blocking server startup.
    Thread-safe: uses a lock for model loading.
    Falls back to Jaccard similarity if the model fails to load.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL_NAME):
        self._model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        self._load_failed = False
        self._logger = logging.getLogger("research_match.embeddings")

    def _ensure_model(self) -> bool:
        """Lazy-load the embedding model. Returns True if model is available."""
        if self._model is not None:
            return True
        if self._load_failed:
            return False

        with self._lock:
            if self._model is not None:
                return True
            if self._load_failed:
                return False
            try:
                from sentence_transformers import SentenceTransformer
                self._logger.info("Loading embedding model '%s'...", self._model_name)
                self._model = SentenceTransformer(self._model_name)
                self._logger.info("Embedding model loaded successfully.")
                return True
            except Exception as e:
                self._logger.warning("Failed to load embedding model: %s. Using Jaccard fallback.", e)
                self._load_failed = True
                return False

    def similarity(self, text_a: str, text_b: str) -> float:
        """Compute semantic similarity between two texts (0.0 to 1.0).

        Uses cosine similarity of sentence embeddings if model is available,
        otherwise falls back to Jaccard word-overlap similarity.
        """
        if not text_a or not text_b:
            return 0.0

        if self._ensure_model():
            return self._cosine_similarity(text_a, text_b)
        return self._jaccard_similarity(text_a, text_b)

    def _cosine_similarity(self, text_a: str, text_b: str) -> float:
        """Cosine similarity using sentence embeddings."""
        embeddings = self._model.encode([text_a, text_b], normalize_embeddings=True)
        score = float(np.dot(embeddings[0], embeddings[1]))
        return max(0.0, min(1.0, score))

    @staticmethod
    def _jaccard_similarity(text_a: str, text_b: str) -> float:
        """Fallback: Jaccard word-overlap similarity."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def method(self) -> str:
        return "sentence-transformers" if self._model is not None else "jaccard-fallback"


# =============================================================================
# DATABASE INITIALIZATION
# =============================================================================

def init_database(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database with Research Match schema."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            pseudonym TEXT UNIQUE NOT NULL,
            email_hash TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            reputation_score REAL DEFAULT 100.0,
            total_ratings_received INTEGER DEFAULT 0,
            avg_honesty REAL DEFAULT 0.0,
            avg_quality REAL DEFAULT 0.0,
            avg_effort REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS research_commits (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            version INTEGER DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),

            -- Theory Base (stored as JSON)
            domain TEXT NOT NULL,
            subdomain TEXT,
            problem TEXT NOT NULL,
            hypothesis TEXT,
            theoretical_framework TEXT,

            -- Demonstrations (metadata only, content hashed)
            demonstrations_summary TEXT,
            demo_types TEXT,  -- JSON array: ["math", "code", "data"]
            code_languages TEXT,  -- JSON array: ["Python", "Julia"]

            -- Ad Hoc Content
            adhoc_summary TEXT,
            adhoc_connections TEXT,  -- JSON array of interdisciplinary connections

            -- Cherry-Picking Declared
            cherry_picking TEXT,  -- JSON array of declared sources

            -- Solidity levels (JSON object mapping component to level)
            solidity_levels TEXT,  -- {"theory": "speculative", "demos": "functional", ...}
            overall_solidity TEXT DEFAULT 'speculative',

            -- Content hashes for integrity verification
            content_hash TEXT NOT NULL,

            -- AI-generated scores
            ot_score REAL,  -- Theoretical Originality (0-100)
            ofc_score REAL,  -- Formal-Computational Originality (0-100)
            ot_breakdown TEXT,  -- JSON with per-factor scores
            ofc_breakdown TEXT,  -- JSON with per-factor scores
            solidity_impact TEXT,  -- JSON showing how solidity affected scores

            UNIQUE(user_id, version)
        );

        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY,
            user_a_id TEXT NOT NULL REFERENCES users(id),
            user_b_id TEXT NOT NULL REFERENCES users(id),
            base_similarity REAL NOT NULL,  -- 0-100
            complementarity_score REAL NOT NULL,  -- 0-100
            semaphore TEXT NOT NULL CHECK(semaphore IN ('green', 'yellow', 'red')),
            semaphore_reason_a TEXT,  -- Why this color, from A's perspective
            semaphore_reason_b TEXT,  -- Why this color, from B's perspective
            semaphore_summary TEXT,   -- Neutral summary
            a_gains_from_b REAL,  -- What A gains from B (0-100)
            b_gains_from_a REAL,  -- What B gains from A (0-100)
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(user_a_id, user_b_id)
        );

        CREATE TABLE IF NOT EXISTS collaboration_requests (
            id TEXT PRIMARY KEY,
            match_id TEXT NOT NULL REFERENCES matches(id),
            requester_id TEXT NOT NULL REFERENCES users(id),
            recipient_id TEXT NOT NULL REFERENCES users(id),
            message TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'accepted', 'rejected', 'expired')),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            responded_at TEXT
        );

        CREATE TABLE IF NOT EXISTS teams (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            repository_url TEXT,
            license_type TEXT DEFAULT 'joint-equal'
        );

        CREATE TABLE IF NOT EXISTS team_members (
            team_id TEXT NOT NULL REFERENCES teams(id),
            user_id TEXT NOT NULL REFERENCES users(id),
            role TEXT DEFAULT 'contributor',
            contribution_percentage REAL,
            joined_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (team_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL REFERENCES teams(id),
            rater_id TEXT NOT NULL REFERENCES users(id),
            rated_id TEXT NOT NULL REFERENCES users(id),
            honesty INTEGER NOT NULL CHECK(honesty BETWEEN 1 AND 5),
            quality INTEGER NOT NULL CHECK(quality BETWEEN 1 AND 5),
            effort INTEGER NOT NULL CHECK(effort BETWEEN 1 AND 5),
            comment TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_revealed INTEGER DEFAULT 0,  -- 0 = anonymous until both rate
            UNIQUE(team_id, rater_id, rated_id)
        );

        -- =============================================================
        -- COLLABORATION LAYER (v2.4)
        -- =============================================================

        CREATE TABLE IF NOT EXISTS team_tickets (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL REFERENCES teams(id),
            author_id TEXT NOT NULL REFERENCES users(id),
            type TEXT NOT NULL CHECK(type IN ('need_help', 'can_offer', 'warning', 'question')),
            area TEXT NOT NULL CHECK(area IN ('theory', 'code', 'data', 'review', 'infrastructure')),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'important'
                CHECK(priority IN ('critical', 'important', 'nice_to_have')),
            status TEXT NOT NULL DEFAULT 'open'
                CHECK(status IN ('open', 'in_progress', 'resolved', 'wont_fix')),
            assigned_to TEXT REFERENCES users(id),
            resolved_by TEXT REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS reveal_consents (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL REFERENCES teams(id),
            level INTEGER NOT NULL CHECK(level IN (3, 4)),
            requester_id TEXT NOT NULL REFERENCES users(id),
            approver_id TEXT NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'approved', 'denied')),
            resource_type TEXT,
            resource_ref TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at TEXT,
            UNIQUE(team_id, level, requester_id, resource_ref)
        );

        CREATE TABLE IF NOT EXISTS shared_files (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL REFERENCES teams(id),
            consent_id TEXT REFERENCES reveal_consents(id),
            shared_by TEXT NOT NULL REFERENCES users(id),
            file_path TEXT NOT NULL,
            file_hash TEXT,
            description TEXT,
            origin_user_id TEXT NOT NULL REFERENCES users(id),
            shared_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL REFERENCES teams(id),
            actor_id TEXT NOT NULL REFERENCES users(id),
            action TEXT NOT NULL CHECK(action IN (
                'reveal_requested', 'reveal_approved', 'reveal_denied',
                'file_shared', 'file_accessed',
                'ticket_created', 'ticket_updated', 'ticket_resolved',
                'license_generated', 'violation_detected'
            )),
            resource_ref TEXT,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Collaboration contracts (NEED-08)
        CREATE TABLE IF NOT EXISTS collaboration_contracts (
            id TEXT PRIMARY KEY,
            team_id TEXT NOT NULL REFERENCES teams(id),
            contract_version INTEGER NOT NULL DEFAULT 1,
            license_type TEXT NOT NULL,
            contribution_split TEXT NOT NULL,
            contract_content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            generated_by TEXT NOT NULL REFERENCES users(id),
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            confirmation_a_user_id TEXT REFERENCES users(id),
            confirmation_a_git_hash TEXT,
            confirmation_a_repo_url TEXT,
            confirmation_a_at TEXT,
            confirmation_b_user_id TEXT REFERENCES users(id),
            confirmation_b_git_hash TEXT,
            confirmation_b_repo_url TEXT,
            confirmation_b_at TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'partial', 'confirmed', 'superseded')),
            UNIQUE(team_id, contract_version)
        );

        -- Original indexes
        CREATE INDEX IF NOT EXISTS idx_commits_user ON research_commits(user_id);
        CREATE INDEX IF NOT EXISTS idx_commits_domain ON research_commits(domain, subdomain);
        CREATE INDEX IF NOT EXISTS idx_matches_users ON matches(user_a_id, user_b_id);
        CREATE INDEX IF NOT EXISTS idx_requests_recipient ON collaboration_requests(recipient_id, status);
        CREATE INDEX IF NOT EXISTS idx_ratings_rated ON ratings(rated_id);
        CREATE INDEX IF NOT EXISTS idx_ratings_team ON ratings(team_id);

        -- Collaboration layer indexes (v2.4)
        CREATE INDEX IF NOT EXISTS idx_tickets_team_status ON team_tickets(team_id, status);
        CREATE INDEX IF NOT EXISTS idx_tickets_author ON team_tickets(author_id);
        CREATE INDEX IF NOT EXISTS idx_reveal_team_level ON reveal_consents(team_id, level);
        CREATE INDEX IF NOT EXISTS idx_shared_files_team ON shared_files(team_id);
        CREATE INDEX IF NOT EXISTS idx_shared_files_origin ON shared_files(origin_user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_team ON audit_log(team_id);
        CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id);
        CREATE INDEX IF NOT EXISTS idx_contracts_team ON collaboration_contracts(team_id, status);
    """)

    conn.commit()

    # Migration: add running average columns for exponential smoothing
    for col in ("running_honesty", "running_quality", "running_effort"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} REAL DEFAULT NULL")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Migration: add license_updated_at to teams (NEED-03)
    try:
        conn.execute("ALTER TABLE teams ADD COLUMN license_updated_at TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add description to shared_files (NEED-04)
    try:
        conn.execute("ALTER TABLE shared_files ADD COLUMN description TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Migration: add git refs to research_commits (NEED-08)
    for col in ("git_repo_url TEXT", "git_commit_hash TEXT"):
        try:
            conn.execute(f"ALTER TABLE research_commits ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.commit()

    return conn


# =============================================================================
# AI EVALUATION ENGINE (MVP - Simulated Enclave)
# =============================================================================

class OriginalityEvaluator:
    """
    Evaluates originality of Research Commits.

    In production, this runs inside a TEE (Trusted Execution Environment).
    For MVP, it uses heuristic analysis against the local corpus.
    The architecture is designed so this module can be swapped for a
    real enclave-based evaluator without changing the interface.

    v2.2: Uses sentence-transformers for semantic similarity (with Jaccard fallback).
    """

    def __init__(self, db: Optional[sqlite3.Connection] = None,
                 embeddings: Optional[EmbeddingEngine] = None,
                 datastore: Optional[DataStore] = None):
        self.db = db
        self.datastore = datastore
        self.embeddings = embeddings or EmbeddingEngine()

    async def evaluate_commit(self, commit_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Evaluate a Research Commit and return originality scores."""
        eval_logger = logging.getLogger("research_match.evaluator")

        # Get existing commits in the same domain for comparison
        corpus = await self._get_corpus_async(commit_data["domain"], commit_data.get("subdomain"), user_id)
        eval_logger.debug("Evaluating commit in %s/%s, corpus size: %d",
                          commit_data["domain"], commit_data.get("subdomain", ""), len(corpus))

        # Calculate Theoretical Originality (OT)
        ot_breakdown = self._evaluate_theoretical(commit_data, corpus)
        ot_score = sum(
            score * OT_WEIGHTS[factor]
            for factor, score in ot_breakdown.items()
        )

        # Calculate Formal-Computational Originality (OFC)
        ofc_breakdown = self._evaluate_formal_computational(commit_data, corpus)
        ofc_score = sum(
            score * OFC_WEIGHTS[factor]
            for factor, score in ofc_breakdown.items()
        )

        # Apply solidity multipliers
        solidity_levels = commit_data.get("solidity_levels", {})
        overall_solidity = commit_data.get("overall_solidity", "speculative")
        solidity_impact = self._apply_solidity(
            ot_score, ofc_score, solidity_levels, overall_solidity
        )

        eval_logger.info("Commit evaluated: OT=%.1f%% OFC=%.1f%% (raw: OT=%.1f%% OFC=%.1f%%, solidity=%s)",
                         solidity_impact["adjusted_ot"], solidity_impact["adjusted_ofc"],
                         ot_score, ofc_score, overall_solidity)

        return {
            "ot_score": round(solidity_impact["adjusted_ot"], 1),
            "ofc_score": round(solidity_impact["adjusted_ofc"], 1),
            "ot_breakdown": ot_breakdown,
            "ofc_breakdown": ofc_breakdown,
            "ot_raw": round(ot_score, 1),
            "ofc_raw": round(ofc_score, 1),
            "solidity_impact": solidity_impact,
        }

    def _apply_solidity(
        self, ot_raw: float, ofc_raw: float,
        solidity_levels: Dict[str, str], overall_solidity: str
    ) -> Dict[str, Any]:
        """Apply solidity level multipliers to raw scores.

        Solidity affects confidence in the score:
        - 'proven' content keeps its full score
        - 'speculative' content is discounted
        - Mixed solidity uses weighted average of components
        """
        # If detailed solidity levels provided, use component-level adjustment
        if solidity_levels:
            theory_mult = SOLIDITY_MULTIPLIERS.get(
                solidity_levels.get("theory", overall_solidity), 0.6
            )
            demos_mult = SOLIDITY_MULTIPLIERS.get(
                solidity_levels.get("demos", overall_solidity), 0.6
            )
            adhoc_mult = SOLIDITY_MULTIPLIERS.get(
                solidity_levels.get("adhoc", overall_solidity), 0.6
            )
            cherry_mult = SOLIDITY_MULTIPLIERS.get(
                solidity_levels.get("cherry_picking", "cherry_picked"), 0.3
            )

            # OT is more affected by theory and adhoc solidity
            ot_mult = (theory_mult * 0.5 + adhoc_mult * 0.35 + cherry_mult * 0.15)
            # OFC is more affected by demos solidity
            ofc_mult = (demos_mult * 0.7 + theory_mult * 0.2 + cherry_mult * 0.1)
        else:
            # Use overall solidity for both
            mult = SOLIDITY_MULTIPLIERS.get(overall_solidity, 0.6)
            ot_mult = mult
            ofc_mult = mult

        adjusted_ot = ot_raw * ot_mult
        adjusted_ofc = ofc_raw * ofc_mult

        return {
            "adjusted_ot": adjusted_ot,
            "adjusted_ofc": adjusted_ofc,
            "ot_multiplier": round(ot_mult, 2),
            "ofc_multiplier": round(ofc_mult, 2),
            "overall_solidity": overall_solidity,
            "component_levels": solidity_levels,
            "explanation": (
                f"Solidity '{overall_solidity}' applied. "
                f"OT adjusted by x{ot_mult:.2f} ({ot_raw:.1f} -> {adjusted_ot:.1f}), "
                f"OFC adjusted by x{ofc_mult:.2f} ({ofc_raw:.1f} -> {adjusted_ofc:.1f})."
            )
        }

    async def _get_corpus_async(self, domain: str, subdomain: Optional[str], exclude_user: str) -> List[Dict]:
        """Get existing commits in the same domain for comparison."""
        if self.datastore:
            return await self.datastore.get_corpus_commits(domain, exclude_user, subdomain)

        query = "SELECT * FROM research_commits WHERE domain = ? AND user_id != ?"
        params = [domain, exclude_user]
        if subdomain:
            query += " AND subdomain = ?"
            params.append(subdomain)

        rows = self.db.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def _evaluate_theoretical(self, commit: Dict, corpus: List[Dict]) -> Dict[str, float]:
        """Evaluate theoretical originality factors."""
        corpus_size = len(corpus)

        # Hypothesis novelty: compare against existing hypotheses
        hypothesis_novelty = 75.0  # Base score
        if commit.get("hypothesis"):
            hyp_text = commit["hypothesis"].lower()
            for c in corpus:
                if c.get("hypothesis") and self._text_similarity(hyp_text, c["hypothesis"].lower()) > 0.7:
                    hypothesis_novelty -= 15.0
            hypothesis_novelty = max(20.0, min(100.0, hypothesis_novelty))

        # Interdisciplinary connections
        connections = commit.get("adhoc_connections", [])
        if isinstance(connections, str):
            try:
                connections = json.loads(connections)
            except (json.JSONDecodeError, TypeError):
                connections = []
        interdisciplinary = min(100.0, 40.0 + len(connections) * 15.0)

        # Ad hoc content richness
        adhoc = commit.get("adhoc_summary", "")
        adhoc_score = min(100.0, 30.0 + len(adhoc.split()) * 0.5) if adhoc else 25.0

        # Corpus divergence
        if corpus_size == 0:
            divergence = 90.0  # First in the field = high divergence
        else:
            similarities = []
            for c in corpus:
                sim = self._commit_similarity(commit, c)
                similarities.append(sim)
            avg_sim = sum(similarities) / len(similarities)
            divergence = max(10.0, 100.0 - avg_sim)

        return {
            "hypothesis_novelty": round(hypothesis_novelty, 1),
            "interdisciplinary_connections": round(interdisciplinary, 1),
            "adhoc_content": round(adhoc_score, 1),
            "corpus_divergence": round(divergence, 1),
        }

    def _evaluate_formal_computational(self, commit: Dict, corpus: List[Dict]) -> Dict[str, float]:
        """Evaluate formal-computational originality factors."""

        demo_types = commit.get("demo_types", [])
        if isinstance(demo_types, str):
            try:
                demo_types = json.loads(demo_types)
            except (json.JSONDecodeError, TypeError):
                demo_types = []

        code_langs = commit.get("code_languages", [])
        if isinstance(code_langs, str):
            try:
                code_langs = json.loads(code_langs)
            except (json.JSONDecodeError, TypeError):
                code_langs = []

        # Formal method originality
        formal_score = 50.0
        if "math" in demo_types:
            formal_score += 20.0
        if "proof_assistant" in demo_types:
            formal_score += 25.0
        formal_score = min(100.0, formal_score)

        # Code quality (based on diversity and description)
        code_score = 30.0
        code_score += len(code_langs) * 12.0
        if commit.get("demonstrations_summary"):
            code_score += min(30.0, len(commit["demonstrations_summary"].split()) * 0.3)
        code_score = min(100.0, code_score)

        # Validation power
        validation = 40.0
        if "data" in demo_types:
            validation += 25.0
        if "code" in demo_types:
            validation += 20.0
        if "math" in demo_types:
            validation += 15.0
        validation = min(100.0, validation)

        # Technical sophistication
        sophistication = 35.0 + len(demo_types) * 15.0 + len(code_langs) * 8.0
        sophistication = min(100.0, sophistication)

        # Coverage (how much of theory is backed by demos)
        coverage = 30.0
        if demo_types:
            coverage += len(demo_types) * 20.0
        coverage = min(100.0, coverage)

        return {
            "formal_method_originality": round(formal_score, 1),
            "code_quality": round(code_score, 1),
            "validation_power": round(validation, 1),
            "technical_sophistication": round(sophistication, 1),
            "coverage": round(coverage, 1),
        }

    def _text_similarity(self, a: str, b: str) -> float:
        """Semantic similarity using sentence-transformers (with Jaccard fallback).

        Returns a value between 0.0 and 1.0.
        """
        return self.embeddings.similarity(a, b)

    def _commit_similarity(self, a: Dict, b: Dict) -> float:
        """Calculate overall similarity between two commits using semantic embeddings.

        Compares problem, hypothesis, and theoretical_framework fields.
        Returns a value between 0 and 100.
        """
        scores = []
        for field in ["problem", "hypothesis", "theoretical_framework"]:
            va = (a.get(field) or "")
            vb = (b.get(field) or "")
            if va and vb:
                scores.append(self._text_similarity(va, vb) * 100)
        return sum(scores) / max(len(scores), 1)


# =============================================================================
# REPUTATION ENGINE
# =============================================================================

class ReputationEngine:
    """Calculates and manages user reputation based on ratings.

    Reputation is a composite score that reflects:
    - Honesty: Does the user declare solidity levels accurately?
    - Quality: Is their work well-structured and valuable?
    - Effort: Do they contribute meaningfully to collaborations?

    v2.3: Uses exponential smoothing (O(1) per update) with batch fallback.
    Anti-retaliation: Ratings are anonymous until BOTH team members
    have rated each other. This prevents strategic rating.
    """

    def __init__(self, db: Optional[sqlite3.Connection] = None,
                 datastore: Optional[DataStore] = None):
        self.db = db
        self.datastore = datastore

    def _compute_reputation_score(self, avg_honesty: float, avg_quality: float,
                                   avg_effort: float, total_ratings: int) -> float:
        """Compute composite reputation from averages (0-100 scale)."""
        rep_logger = logging.getLogger("research_match.reputation")

        reputation = (
            (avg_honesty / 5.0) * (REPUTATION_WEIGHT_HONESTY * 100) +
            (avg_quality / 5.0) * (REPUTATION_WEIGHT_QUALITY * 100) +
            (avg_effort / 5.0) * (REPUTATION_WEIGHT_EFFORT * 100)
        )

        if avg_honesty < REPUTATION_LOW_HONESTY_THRESHOLD:
            reputation *= REPUTATION_LOW_HONESTY_PENALTY
            rep_logger.info("Low honesty penalty applied (avg_honesty=%.2f)", avg_honesty)

        if (total_ratings >= REPUTATION_BONUS_MIN_RATINGS
                and avg_honesty >= REPUTATION_BONUS_HONESTY_FLOOR
                and avg_quality >= REPUTATION_BONUS_QUALITY_FLOOR):
            reputation = min(100.0, reputation * REPUTATION_BONUS_MULTIPLIER)
            rep_logger.info("Consistency bonus applied (ratings=%d)", total_ratings)

        rep_logger.debug("Reputation computed: %.1f (h=%.2f q=%.2f e=%.2f, n=%d)",
                         reputation, avg_honesty, avg_quality, avg_effort, total_ratings)

        return round(reputation, 1)

    async def calculate_reputation(self, user_id: str) -> Dict[str, Any]:
        """Calculate composite reputation for a user.

        Uses running averages if available (O(1)), falls back to batch recalculation.
        """
        if self.datastore:
            user = await self.datastore.get_user_running_averages(user_id)
            total_ratings = await self.datastore.count_ratings_received(user_id)
        else:
            user = self.db.execute(
                "SELECT running_honesty, running_quality, running_effort, total_ratings_received FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()
            total_ratings = self.db.execute(
                "SELECT COUNT(*) as c FROM ratings WHERE rated_id = ?", (user_id,)
            ).fetchone()["c"]

        if total_ratings < MIN_RATINGS_FOR_REPUTATION:
            return {
                "reputation_score": 100.0,
                "total_ratings": total_ratings,
                "avg_honesty": 0.0,
                "avg_quality": 0.0,
                "avg_effort": 0.0,
                "status": "insufficient_data",
                "message": f"Need at least {MIN_RATINGS_FOR_REPUTATION} ratings to calculate reputation."
            }

        # Try running averages first
        if user and user["running_honesty"] is not None:
            avg_honesty = user["running_honesty"]
            avg_quality = user["running_quality"]
            avg_effort = user["running_effort"]
        else:
            # Fallback: batch recalculate
            avgs = await self._batch_recalculate(user_id)
            avg_honesty = avgs["avg_honesty"]
            avg_quality = avgs["avg_quality"]
            avg_effort = avgs["avg_effort"]

        reputation = self._compute_reputation_score(avg_honesty, avg_quality, avg_effort, total_ratings)

        return {
            "reputation_score": reputation,
            "total_ratings": total_ratings,
            "avg_honesty": round(avg_honesty, 2),
            "avg_quality": round(avg_quality, 2),
            "avg_effort": round(avg_effort, 2),
            "status": "calculated",
        }

    async def apply_new_rating(self, user_id: str, honesty: int, quality: int, effort: int) -> None:
        """Apply a single new rating using exponential smoothing O(1).

        Formula: new_avg = alpha * new_value + (1 - alpha) * old_avg
        """
        if self.datastore:
            user = await self.datastore.get_user_running_averages(user_id)
        else:
            user = self.db.execute(
                "SELECT running_honesty, running_quality, running_effort FROM users WHERE id = ?",
                (user_id,)
            ).fetchone()

        alpha = REPUTATION_ALPHA

        if user and user.get("running_honesty") is not None:
            new_honesty = alpha * honesty + (1 - alpha) * user["running_honesty"]
            new_quality = alpha * quality + (1 - alpha) * user["running_quality"]
            new_effort = alpha * effort + (1 - alpha) * user["running_effort"]
        else:
            # First rating or migration: initialize from batch
            avgs = await self._batch_recalculate(user_id)
            new_honesty = avgs["avg_honesty"]
            new_quality = avgs["avg_quality"]
            new_effort = avgs["avg_effort"]

        if self.datastore:
            await self.datastore.update_user_running_averages(user_id, new_honesty, new_quality, new_effort)
        else:
            self.db.execute("""
                UPDATE users SET running_honesty = ?, running_quality = ?, running_effort = ?
                WHERE id = ?
            """, (new_honesty, new_quality, new_effort, user_id))
            self.db.commit()

    async def _batch_recalculate(self, user_id: str) -> Dict[str, float]:
        """Recalculate running averages from all ratings (migration/fallback).

        Uses temporal weighting: recent ratings count more.
        Also stores the result as running averages for future O(1) updates.
        """
        if self.datastore:
            ratings = await self.datastore.get_ratings_received_desc(user_id)
        else:
            ratings = self.db.execute(
                "SELECT * FROM ratings WHERE rated_id = ? ORDER BY created_at DESC",
                (user_id,)
            ).fetchall()

        if not ratings:
            return {"avg_honesty": 0.0, "avg_quality": 0.0, "avg_effort": 0.0}

        total_weight = 0.0
        weighted_honesty = 0.0
        weighted_quality = 0.0
        weighted_effort = 0.0

        for i, r in enumerate(ratings):
            r = dict(r)
            weight = (1 - REPUTATION_ALPHA) ** i
            total_weight += weight
            weighted_honesty += r["honesty"] * weight
            weighted_quality += r["quality"] * weight
            weighted_effort += r["effort"] * weight

        avg_honesty = weighted_honesty / total_weight
        avg_quality = weighted_quality / total_weight
        avg_effort = weighted_effort / total_weight

        # Store as running averages
        if self.datastore:
            await self.datastore.update_user_running_averages(user_id, avg_honesty, avg_quality, avg_effort)
        else:
            self.db.execute("""
                UPDATE users SET running_honesty = ?, running_quality = ?, running_effort = ?
                WHERE id = ?
            """, (avg_honesty, avg_quality, avg_effort, user_id))
            self.db.commit()

        return {
            "avg_honesty": avg_honesty,
            "avg_quality": avg_quality,
            "avg_effort": avg_effort,
        }

    async def update_user_reputation(self, user_id: str) -> None:
        """Recalculate and store reputation for a user."""
        rep = await self.calculate_reputation(user_id)
        if self.datastore:
            await self.datastore.update_user_reputation_stats(
                user_id, rep["reputation_score"], rep["total_ratings"],
                rep["avg_honesty"], rep["avg_quality"], rep["avg_effort"])
        else:
            self.db.execute("""
                UPDATE users SET
                    reputation_score = ?,
                    total_ratings_received = ?,
                    avg_honesty = ?,
                    avg_quality = ?,
                    avg_effort = ?
                WHERE id = ?
            """, (
                rep["reputation_score"],
                rep["total_ratings"],
                rep["avg_honesty"],
                rep["avg_quality"],
                rep["avg_effort"],
                user_id
            ))
            self.db.commit()

    async def check_both_rated(self, team_id: str, user_a_id: str, user_b_id: str) -> bool:
        """Check if both team members have rated each other."""
        if self.datastore:
            a_rated_b = await self.datastore.find_rating(team_id, user_a_id, user_b_id)
            b_rated_a = await self.datastore.find_rating(team_id, user_b_id, user_a_id)
        else:
            a_rated_b = self.db.execute(
                "SELECT id FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
                (team_id, user_a_id, user_b_id)
            ).fetchone()
            b_rated_a = self.db.execute(
                "SELECT id FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
                (team_id, user_b_id, user_a_id)
            ).fetchone()
        return bool(a_rated_b and b_rated_a)

    async def reveal_ratings(self, team_id: str) -> None:
        """Mark all ratings in a team as revealed (both have rated)."""
        if self.datastore:
            await self.datastore.reveal_team_ratings(team_id)
        else:
            self.db.execute(
                "UPDATE ratings SET is_revealed = 1 WHERE team_id = ?",
                (team_id,)
            )
            self.db.commit()

    async def detect_abuse_patterns(self, rater_id: str) -> Dict[str, Any]:
        """Detect if a rater shows patterns of abusive rating behavior.

        Flags:
        - Always gives 1-star (vindictive)
        - Always gives 5-star (inflating)
        - Rates too quickly after team formation (didn't actually collaborate)
        """
        if self.datastore:
            ratings_given = await self.datastore.get_ratings_given_desc(rater_id)
        else:
            ratings_given = self.db.execute(
                "SELECT * FROM ratings WHERE rater_id = ? ORDER BY created_at DESC",
                (rater_id,)
            ).fetchall()

        if len(ratings_given) < 3:
            return {"abuse_detected": False, "flags": []}

        flags = []
        honesty_vals = [dict(r)["honesty"] for r in ratings_given]
        quality_vals = [dict(r)["quality"] for r in ratings_given]

        # All 1s pattern
        if all(h <= 1 for h in honesty_vals[-5:]):
            flags.append("vindictive_pattern")

        # All 5s pattern
        if all(h >= 5 for h in honesty_vals[-5:]) and all(q >= 5 for q in quality_vals[-5:]):
            flags.append("inflation_pattern")

        # Low variance (always same score)
        if len(set(honesty_vals[-5:])) == 1 and len(ratings_given) >= 5:
            flags.append("zero_variance_pattern")

        return {
            "abuse_detected": len(flags) > 0,
            "flags": flags,
            "total_ratings_given": len(ratings_given),
        }


# =============================================================================
# MATCHING ENGINE
# =============================================================================

class MatchingEngine:
    """Calculates matches and bilateral convenience semaphores.

    v2.2: Uses sentence-transformers for semantic base similarity (with Jaccard fallback).
    """

    def __init__(self, db: Optional[sqlite3.Connection] = None,
                 embeddings: Optional[EmbeddingEngine] = None,
                 datastore: Optional[DataStore] = None):
        self.db = db
        self.datastore = datastore
        self.embeddings = embeddings or EmbeddingEngine()

    async def find_matches(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Find potential collaborators for a user."""
        match_logger = logging.getLogger("research_match.matcher")

        # Get user's latest commit
        if self.datastore:
            user_commit = await self.datastore.get_latest_commit_by_user(user_id)
        else:
            user_commit = self.db.execute(
                "SELECT * FROM research_commits WHERE user_id = ? ORDER BY version DESC LIMIT 1",
                (user_id,)
            ).fetchone()

        if not user_commit:
            return []

        user_commit = dict(user_commit)

        # Find commits in same/similar domain
        if self.datastore:
            candidates = await self.datastore.find_candidate_commits_in_domain(
                user_id, user_commit["domain"])
        else:
            candidates = self.db.execute("""
                SELECT rc.*, u.pseudonym, u.reputation_score,
                       u.total_ratings_received, u.avg_honesty, u.avg_quality, u.avg_effort
                FROM research_commits rc
                JOIN users u ON rc.user_id = u.id
                WHERE rc.user_id != ?
                AND rc.domain = ?
                AND rc.id IN (
                    SELECT id FROM research_commits
                    GROUP BY user_id
                    HAVING version = MAX(version)
                )
                ORDER BY rc.created_at DESC
                LIMIT ?
            """, (user_id, user_commit["domain"], limit * 3)).fetchall()

        matches = []
        for candidate in candidates:
            candidate = dict(candidate)
            match_data = self._calculate_match(user_commit, candidate)
            if match_data:
                matches.append(match_data)

        # Sort by complementarity score descending
        matches.sort(key=lambda m: m["complementarity_score"], reverse=True)
        result = matches[:limit]

        match_logger.info("find_matches for user %s: %d candidates, %d matches returned",
                          user_id[:8], len(candidates), len(result))
        for m in result:
            match_logger.info("  %s: %s (a_gains=%.1f, b_gains=%.1f, complementarity=%.1f)",
                              m["semaphore"].upper(), m["candidate_pseudonym"],
                              m["a_gains_from_b"], m["b_gains_from_a"], m["complementarity_score"])
        return result

    def _calculate_match(self, user_commit: Dict, candidate_commit: Dict) -> Optional[Dict]:
        """Calculate match quality between two commits."""
        # Phase 1: Base similarity
        base_sim = self._base_similarity(user_commit, candidate_commit)
        if base_sim < 20:  # Too different to match
            return None

        # Phase 2: Complementarity
        user_ot = user_commit.get("ot_score", 50) or 50
        user_ofc = user_commit.get("ofc_score", 50) or 50
        cand_ot = candidate_commit.get("ot_score", 50) or 50
        cand_ofc = candidate_commit.get("ofc_score", 50) or 50

        # What each gains: the OTHER's strength in their weakness
        a_gains = self._calculate_gain(user_ot, user_ofc, cand_ot, cand_ofc)
        b_gains = self._calculate_gain(cand_ot, cand_ofc, user_ot, user_ofc)

        complementarity = (a_gains + b_gains) / 2

        # Phase 3: Semaphore
        semaphore = self._calculate_semaphore(a_gains, b_gains)

        return {
            "candidate_pseudonym": candidate_commit.get("pseudonym", "Unknown"),
            "candidate_user_id": candidate_commit["user_id"],
            "base_similarity": round(base_sim, 1),
            "complementarity_score": round(complementarity, 1),
            "semaphore": semaphore["color"],
            "semaphore_reason": semaphore["reason_for_a"],
            "semaphore_reason_for_candidate": semaphore["reason_for_b"],
            "semaphore_summary": semaphore["summary"],
            "a_gains_from_b": round(a_gains, 1),
            "b_gains_from_a": round(b_gains, 1),
            "candidate_ot": round(cand_ot, 1),
            "candidate_ofc": round(cand_ofc, 1),
            "candidate_domain": candidate_commit["domain"],
            "candidate_subdomain": candidate_commit.get("subdomain", ""),
            "candidate_reputation": candidate_commit.get("reputation_score", 100),
            "candidate_total_ratings": candidate_commit.get("total_ratings_received", 0),
            "candidate_avg_honesty": candidate_commit.get("avg_honesty", 0),
            "candidate_solidity": candidate_commit.get("overall_solidity", "unknown"),
        }

    def _base_similarity(self, a: Dict, b: Dict) -> float:
        """Calculate how similar the theoretical base is using semantic similarity."""
        score = 0.0
        if a.get("domain") == b.get("domain"):
            score += 40.0
        if a.get("subdomain") and a.get("subdomain") == b.get("subdomain"):
            score += 30.0

        # Problem similarity via embeddings (or Jaccard fallback)
        prob_a = a.get("problem") or ""
        prob_b = b.get("problem") or ""
        if prob_a and prob_b:
            sim = self.embeddings.similarity(prob_a, prob_b)
            score += sim * 30.0

        return min(100.0, score)

    def _calculate_gain(self, my_ot: float, my_ofc: float, their_ot: float, their_ofc: float) -> float:
        """Calculate what I gain from the other person's strengths in my weaknesses."""
        ot_diff = max(0, their_ot - my_ot)
        ofc_diff = max(0, their_ofc - my_ofc)

        ot_gain = ot_diff * (their_ot / 100.0) * 1.5
        ofc_gain = ofc_diff * (their_ofc / 100.0) * 1.5

        weakness_bonus_ot = max(0, (100 - my_ot) * (their_ot / 100.0) * WEAKNESS_BONUS_COEFFICIENT)
        weakness_bonus_ofc = max(0, (100 - my_ofc) * (their_ofc / 100.0) * WEAKNESS_BONUS_COEFFICIENT)

        total = ot_gain + ofc_gain + weakness_bonus_ot + weakness_bonus_ofc
        return min(100.0, total)

    def _calculate_semaphore(self, a_gains: float, b_gains: float) -> Dict[str, str]:
        """Calculate the bilateral convenience semaphore with reasoning.

        Rules (evaluated in order):
        1. GREEN fuerte: min_gain >= 20 (ambos ganan mucho)
        2. GREEN complementario: max >= 40, avg >= 20, min >= 3
        3. YELLOW: max >= 25 (al menos uno gana bien, sub-niveles por min_gain)
        4. YELLOW moderado: avg >= 12, min >= 3 (ganancia moderada bilateral)
        5. RED: todo lo demas
        """
        min_gain = min(a_gains, b_gains)
        max_gain = max(a_gains, b_gains)
        avg_gain = (a_gains + b_gains) / 2

        # Rule 1: GREEN fuerte — ambos ganan mucho
        if min_gain >= GREEN_MUTUAL_THRESHOLD:
            return {
                "color": "green",
                "reason_for_a": f"Alta conveniencia mutua. Ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. Colaboración equilibrada.",
                "reason_for_b": f"Alta conveniencia mutua. Ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. Colaboración equilibrada.",
                "summary": "Ambos se benefician significativamente. Match recomendado."
            }

        # Rule 2: GREEN complementario — uno gana mucho, total alto, el otro gana algo
        if max_gain >= GREEN_MAX_GAIN_THRESHOLD and avg_gain >= GREEN_AVG_GAIN_THRESHOLD and min_gain >= GREEN_MIN_GAIN_FLOOR:
            weak_side = "a" if a_gains < b_gains else "b"
            return {
                "color": "green",
                "reason_for_a": (
                    f"Alta complementariedad. Ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. "
                    f"{'Tu aporte compensa con tu especialización única.' if weak_side == 'a' else 'Gran beneficio de la complementariedad del otro.'}"
                ),
                "reason_for_b": (
                    f"Alta complementariedad. Ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. "
                    f"{'Tu aporte compensa con tu especialización única.' if weak_side == 'b' else 'Gran beneficio de la complementariedad del otro.'}"
                ),
                "summary": f"Complementariedad fuerte (max {max_gain:.0f}%, avg {avg_gain:.0f}%). Match recomendado."
            }

        # Rule 3: YELLOW — al menos uno gana bien
        if max_gain >= YELLOW_MAX_GAIN_THRESHOLD:
            if min_gain >= YELLOW_MIN_GAIN_MODERATE:
                sub = "moderado"
                detail = "Ambos obtienen beneficio, aunque asimétrico."
            else:
                sub = "asimétrico"
                detail = "Un lado se beneficia mucho más. Considerar negociación de términos."
            return {
                "color": "yellow",
                "reason_for_a": f"Match {sub}. Ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. {detail}",
                "reason_for_b": f"Match {sub}. Ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. {detail}",
                "summary": f"Match {sub} (max {max_gain:.0f}%, min {min_gain:.0f}%). Funcional con negociación."
            }

        # Rule 4: YELLOW moderado — ganancia moderada bilateral
        if avg_gain >= YELLOW_AVG_THRESHOLD and min_gain >= GREEN_MIN_GAIN_FLOOR:
            return {
                "color": "yellow",
                "reason_for_a": f"Conveniencia moderada. Ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. Beneficio modesto pero bilateral.",
                "reason_for_b": f"Conveniencia moderada. Ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. Beneficio modesto pero bilateral.",
                "summary": f"Ganancia moderada bilateral (avg {avg_gain:.0f}%). Viable con interés mutuo."
            }

        # Rule 5: RED — beneficio insuficiente
        return {
            "color": "red",
            "reason_for_a": f"Baja conveniencia. Ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. Insuficiente para justificar colaboración.",
            "reason_for_b": f"Baja conveniencia. Ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. Insuficiente para justificar colaboración.",
            "summary": "Beneficio insuficiente para ambas partes."
        }


# =============================================================================
# PYDANTIC INPUT MODELS
# =============================================================================

class SolidityLevel(str, Enum):
    """Maturity/solidity levels for research components."""
    PROVEN = "proven"           # Formally verified, peer-reviewed, reproducible
    FUNCTIONAL = "functional"   # Working implementation, reproducible results
    SPECULATIVE = "speculative" # Theoretical reasoning, not fully validated
    ADHOC = "adhoc"             # Original intuition, preliminary ideas
    CHERRY_PICKED = "cherry_picked"  # Curated from external sources (declared)


class SolidityLevels(BaseModel):
    """Per-component solidity declaration."""
    model_config = ConfigDict(extra="forbid")

    theory: Optional[SolidityLevel] = Field(
        default=SolidityLevel.SPECULATIVE,
        description="Solidity of the theoretical framework"
    )
    demos: Optional[SolidityLevel] = Field(
        default=SolidityLevel.SPECULATIVE,
        description="Solidity of demonstrations/code/proofs"
    )
    adhoc: Optional[SolidityLevel] = Field(
        default=SolidityLevel.ADHOC,
        description="Solidity of ad hoc original content"
    )
    cherry_picking: Optional[SolidityLevel] = Field(
        default=SolidityLevel.CHERRY_PICKED,
        description="Solidity of cherry-picked content (always cherry_picked)"
    )


class SubmitCommitInput(BaseModel):
    """Input for submitting a Research Commit."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    # Theory Base
    domain: str = Field(..., description="Scientific/technical domain (e.g., 'molecular biology', 'theoretical physics', 'machine learning')", min_length=2, max_length=200)
    subdomain: Optional[str] = Field(None, description="Specialization within domain (e.g., 'protein folding', 'quantum gravity')", max_length=200)
    problem: str = Field(..., description="Specific problem being addressed", min_length=10, max_length=2000)
    hypothesis: Optional[str] = Field(None, description="Central hypothesis or proposition", max_length=2000)
    theoretical_framework: Optional[str] = Field(None, description="Theories and references the work builds on", max_length=3000)

    # Demonstrations
    demonstrations_summary: Optional[str] = Field(None, description="Summary of proofs, code, simulations, experiments", max_length=5000)
    demo_types: Optional[List[str]] = Field(default_factory=list, description="Types of demonstrations: 'math', 'code', 'data', 'proof_assistant', 'simulation'")
    code_languages: Optional[List[str]] = Field(default_factory=list, description="Programming languages used: 'Python', 'R', 'Julia', 'C++', etc.")

    # Ad Hoc Content
    adhoc_summary: Optional[str] = Field(None, description="Original content not from established theory base", max_length=5000)
    adhoc_connections: Optional[List[str]] = Field(default_factory=list, description="Interdisciplinary connections made")

    # Cherry-Picking Declared
    cherry_picking: Optional[List[str]] = Field(default_factory=list, description="Declared sources and what was taken from each")

    # Solidity Levels (NEW in v2)
    solidity_levels: Optional[SolidityLevels] = Field(
        default=None,
        description="Per-component solidity declaration. Honest declaration builds reputation."
    )
    overall_solidity: Optional[SolidityLevel] = Field(
        default=SolidityLevel.SPECULATIVE,
        description="Overall solidity if not specifying per-component: proven, functional, speculative, adhoc, cherry_picked"
    )

    # Git references (NEED-08)
    git_repo_url: Optional[str] = Field(None, description="Repository URL where this work lives", max_length=500)
    git_commit_hash: Optional[str] = Field(None, description="Git commit SHA-1 hash (40-char hex)", max_length=40)

    @field_validator("git_commit_hash")
    @classmethod
    def validate_git_commit_hash(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            if not re.match(GIT_COMMIT_HASH_PATTERN, v):
                raise ValueError("git_commit_hash must be a 40-character lowercase hex string")
        return v


class FindCollaboratorsInput(BaseModel):
    """Input for finding potential collaborators."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    limit: Optional[int] = Field(default=5, description="Maximum number of candidates to return", ge=1, le=20)
    min_semaphore: Optional[str] = Field(default=None, description="Minimum semaphore level: 'green', 'yellow', or 'red'")


class SendRequestInput(BaseModel):
    """Input for sending a collaboration request."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    candidate_user_id: str = Field(..., description="User ID of the candidate (from find_collaborators results)")
    message: Optional[str] = Field(None, description="Optional message describing what you're looking for", max_length=1000)


class RespondRequestInput(BaseModel):
    """Input for responding to a collaboration request."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    request_id: str = Field(..., description="ID of the collaboration request")
    accept: bool = Field(..., description="Whether to accept (true) or reject (false) the request")


class RegisterInput(BaseModel):
    """Input for registering a new user."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: str = Field(..., description="Email address (will be hashed, never stored in plain text)", min_length=5)
    pseudonym: Optional[str] = Field(None, description="Preferred pseudonym (auto-generated if not provided)", max_length=50)


class RateUserInput(BaseModel):
    """Input for rating a collaborator after working together."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="ID of the team where you collaborated")
    rated_user_id: str = Field(..., description="User ID of the person you're rating")
    honesty: int = Field(..., description="Honesty rating 1-5: Did they accurately declare their solidity levels? Were they transparent about cherry-picking?", ge=1, le=5)
    quality: int = Field(..., description="Quality rating 1-5: Was their work well-structured, original, and valuable?", ge=1, le=5)
    effort: int = Field(..., description="Effort rating 1-5: Did they contribute meaningfully to the collaboration?", ge=1, le=5)
    comment: Optional[str] = Field(None, description="Optional private comment (only visible after both parties rate)", max_length=500)


class ColdSearchInput(BaseModel):
    """Input for FREE cold search — no registration required."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Search keywords (domain, topic, or technology)", min_length=2, max_length=200)
    max_results: int = Field(10, description="Maximum results to return", ge=1, le=25)


class DeepSearchInput(BaseModel):
    """Input for deep repository analysis — no registration required."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    repo_url: str = Field(..., description="GitHub repository URL to analyze", min_length=10, max_length=300)
    include_mcp_analysis: bool = Field(True, description="Include MCP framework/tool extraction (Layer 2)")
    include_comparison: bool = Field(True, description="Include gap analysis vs Research Match (Layer 3)")
    include_scoring: bool = Field(False, description="Include originality scoring via OT/OFC (Layer 4, heavier)")

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        import re
        v = v.rstrip("/")
        if v.endswith(".git"):
            v = v[:-4]
        if not re.match(r"^https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", v):
            raise ValueError(
                "Only GitHub URLs accepted. Format: https://github.com/owner/repo"
            )
        return v


# --- Proforma Models (v2.7) ---

class ProformaSolidityAssessment(BaseModel):
    """Solidity assessment with per-component reasoning."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    overall_solidity: str = Field(..., description="Overall solidity: proven/functional/speculative/adhoc/cherry_picked")
    overall_reasoning: str = Field(..., description="Why this overall level", max_length=500)
    theory_solidity: str = Field("speculative", description="Solidity of theoretical framework")
    theory_reasoning: str = Field("", description="Why this theory level", max_length=300)
    demos_solidity: str = Field("speculative", description="Solidity of demonstrations/code")
    demos_reasoning: str = Field("", description="Why this demos level", max_length=300)
    adhoc_solidity: str = Field("adhoc", description="Solidity of ad hoc original content")
    adhoc_reasoning: str = Field("", description="Why this adhoc level", max_length=300)

    @field_validator("overall_solidity", "theory_solidity", "demos_solidity", "adhoc_solidity")
    @classmethod
    def validate_solidity_values(cls, v: str) -> str:
        valid = {sl.value for sl in SolidityLevel}
        if v not in valid:
            raise ValueError(f"Solidity must be one of {sorted(valid)}, got '{v}'")
        return v


class ProformaNarrativeData(BaseModel):
    """Narrative fields generated by AI from project analysis."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    domain: str = Field(..., description="Scientific/technical domain", min_length=2, max_length=200)
    subdomain: Optional[str] = Field(None, description="Specific niche", max_length=200)
    problem: str = Field(..., description="Problem being addressed", min_length=10, max_length=2000)
    hypothesis: Optional[str] = Field(None, description="Central hypothesis", max_length=2000)
    theoretical_framework: Optional[str] = Field(None, description="Theories/papers it builds on", max_length=3000)
    demonstrations_summary: Optional[str] = Field(None, description="What the code/data/proofs DO", max_length=5000)
    adhoc_summary: Optional[str] = Field(None, description="What is genuinely NOVEL", max_length=5000)
    adhoc_connections: List[str] = Field(default_factory=list, description="Interdisciplinary connections")
    cherry_picking: List[str] = Field(default_factory=list, description="Declared external sources")
    solidity_assessment: ProformaSolidityAssessment = Field(..., description="Solidity with reasoning")


class PrepareCommitInput(BaseModel):
    """Input for the universal proforma generator."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    project_path: Optional[str] = Field(None, description="Absolute path to local project directory")
    repo_url: Optional[str] = Field(None, description="GitHub URL to clone and analyze")
    mode: str = Field("extract", description="Mode: 'extract' (analyze + prompt), 'validate' (check narrative), 'submit' (validate + submit)")
    narrative_json: Optional[str] = Field(None, description="JSON string of ProformaNarrativeData (for validate/submit modes)", max_length=NARRATIVE_JSON_MAX_LENGTH)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        allowed = ("extract", "validate", "submit")
        if v not in allowed:
            raise ValueError(f"mode must be one of {allowed}, got '{v}'")
        return v

    @field_validator("project_path")
    @classmethod
    def validate_project_path(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not os.path.isabs(v):
            raise ValueError("project_path must be an absolute path")
        return v

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            import re
            v = v.rstrip("/")
            if v.endswith(".git"):
                v = v[:-4]
            if not re.match(r"^https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", v):
                raise ValueError("Only GitHub URLs accepted. Format: https://github.com/owner/repo")
        return v


# --- Contract Models (NEED-08) ---

class ExportContractInput(BaseModel):
    """Input for generating a git-verifiable collaboration contract."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="ID of the team to generate a contract for")


class ConfirmContractInput(BaseModel):
    """Input for confirming a contract has been committed to git."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="ID of the team")
    contract_id: str = Field(..., description="Contract ID from export_contract")
    git_commit_hash: str = Field(..., description="Git commit SHA-1 hash (40-char hex)", max_length=40)
    repo_url: Optional[str] = Field(None, description="Repository URL where contract was committed", max_length=500)

    @field_validator("git_commit_hash")
    @classmethod
    def validate_git_commit_hash(cls, v: str) -> str:
        import re
        if not re.match(GIT_COMMIT_HASH_PATTERN, v):
            raise ValueError("git_commit_hash must be a 40-character lowercase hex string")
        return v


# --- Collaboration Layer Models (v2.4) ---

class NeedsCreateInput(BaseModel):
    """Input for creating a team ticket (structured need/offer/question)."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="ID of the team where you want to create a ticket")
    type: str = Field(..., description="Ticket type: need_help, can_offer, warning, question")
    area: str = Field(..., description="Work area: theory, code, data, review, infrastructure")
    title: str = Field(..., description="Short descriptive title for the ticket", min_length=5, max_length=MAX_TICKET_TITLE_LENGTH)
    description: str = Field(..., description="Detailed description of the need or offer", min_length=10, max_length=MAX_TICKET_DESCRIPTION_LENGTH)
    priority: str = Field("important", description="Priority level: critical, important, nice_to_have")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = ("need_help", "can_offer", "warning", "question")
        if v not in allowed:
            raise ValueError(f"type must be one of {allowed}, got '{v}'")
        return v

    @field_validator("area")
    @classmethod
    def validate_area(cls, v: str) -> str:
        allowed = ("theory", "code", "data", "review", "infrastructure")
        if v not in allowed:
            raise ValueError(f"area must be one of {allowed}, got '{v}'")
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed = ("critical", "important", "nice_to_have")
        if v not in allowed:
            raise ValueError(f"priority must be one of {allowed}, got '{v}'")
        return v


class NeedsListInput(BaseModel):
    """Input for listing team tickets with optional filters."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="ID of the team whose tickets to list")
    status: Optional[str] = Field(None, description="Filter by status: open, in_progress, resolved, wont_fix")
    area: Optional[str] = Field(None, description="Filter by area: theory, code, data, review, infrastructure")
    type: Optional[str] = Field(None, description="Filter by type: need_help, can_offer, warning, question")


class NeedsResolveInput(BaseModel):
    """Input for resolving (closing) a team ticket."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ticket_id: str = Field(..., description="ID of the ticket to resolve")
    resolution: str = Field(..., description="Resolution type: resolved or wont_fix")
    resolution_note: Optional[str] = Field(None, description="Optional note explaining the resolution", max_length=1000)

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, v: str) -> str:
        allowed = ("resolved", "wont_fix")
        if v not in allowed:
            raise ValueError(f"resolution must be one of {allowed}, got '{v}'")
        return v


class RevealRequestInput(BaseModel):
    """Input for requesting Level 3 reveal of a teammate's Research Commit."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="Team where both users are members")
    target_user_id: str = Field(..., description="User whose commit you want to see")


class RevealRespondInput(BaseModel):
    """Input for approving or denying a reveal consent request."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    consent_id: str = Field(..., description="ID of the consent to respond to")
    approve: bool = Field(..., description="True to approve, False to deny")


class RevealStatusInput(BaseModel):
    """Input for checking reveal status and viewing revealed content."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="Team to check reveal status for")


class TeamLicenseInput(BaseModel):
    """Input for viewing the automatically computed license for a team."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="Team to view license for")


class ShareFileInput(BaseModel):
    """Input for sharing a file metadata record with a team."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="Team to share the file with")
    file_path: str = Field(..., min_length=1, max_length=500, description="File path or name (e.g. 'scripts/analysis.py')")
    file_hash: Optional[str] = Field(None, description="SHA-256 hash for integrity verification")
    description: Optional[str] = Field(None, max_length=500, description="Brief description of the file content")


class SharedFilesInput(BaseModel):
    """Input for listing shared files in a team."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="Team to list shared files for")


class AuditLogInput(BaseModel):
    """Input for viewing the audit trail of a team."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    team_id: str = Field(..., description="Team to view audit log for")
    action_filter: Optional[str] = Field(
        None, description="Filter by action type (e.g. 'file_shared', 'violation_detected')")
    limit: int = Field(50, ge=1, le=200, description="Max entries to return")


# =============================================================================
# LIFESPAN & SERVER INITIALIZATION
# =============================================================================

_server_start_time: Optional[str] = None


@asynccontextmanager
async def app_lifespan(app):
    """Initialize database/datastore and engines."""
    global _server_start_time
    _server_start_time = datetime.now(timezone.utc).isoformat()

    # Determine backend: Firestore if explicitly set or GOOGLE_APPLICATION_CREDENTIALS exists
    backend_env = os.environ.get("RESEARCH_MATCH_BACKEND", "").lower()
    use_firestore = backend_env == "firestore" or bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

    if use_firestore:
        from .firestore_datastore import FirestoreDataStore
        from .firebase_init import init_firebase
        init_firebase()
        datastore = FirestoreDataStore()
        await datastore.initialize()
        db = None  # No SQLite in Firestore mode
    else:
        datastore = None
        db = init_database(DB_PATH)

    # Compute user identity for multi-user mode
    user_email = os.environ.get("RESEARCH_MATCH_USER_EMAIL", "")
    user_email_hash = ""
    if user_email:
        user_email_hash = hashlib.sha256(user_email.lower().strip().encode()).hexdigest()

    embeddings = EmbeddingEngine()
    evaluator = OriginalityEvaluator(db=db, embeddings=embeddings, datastore=datastore)
    matcher = MatchingEngine(db=db, embeddings=embeddings, datastore=datastore)
    reputation = ReputationEngine(db=db, datastore=datastore)
    yield {
        "db": db, "datastore": datastore, "evaluator": evaluator,
        "matcher": matcher, "reputation": reputation,
        "embeddings": embeddings, "user_email_hash": user_email_hash,
    }
    if db:
        db.close()
    if datastore:
        await datastore.close()


mcp = FastMCP("research_match_mcp", lifespan=app_lifespan)


# =============================================================================
# HEALTH ENDPOINT (HTTP only)
# =============================================================================

def _health_stats() -> Dict[str, Any]:
    """Gather health statistics from the database."""
    backend_env = os.environ.get("RESEARCH_MATCH_BACKEND", "").lower()
    use_firestore = backend_env == "firestore" or bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if use_firestore:
        # Firestore mode — return basic stats without DB queries
        return {
            "status": "ok",
            "version": SERVER_VERSION,
            "started_at": _server_start_time,
            "database": "firestore",
            "backend": "firestore",
            "message": "Health stats in Firestore mode — use individual tools for counts.",
        }
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        commits = db.execute("SELECT COUNT(*) as c FROM research_commits").fetchone()["c"]
        matches = db.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"]
        teams = db.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
        pending_requests = db.execute(
            "SELECT COUNT(*) as c FROM collaboration_requests WHERE status = 'pending'"
        ).fetchone()["c"]
        ratings = db.execute("SELECT COUNT(*) as c FROM ratings").fetchone()["c"]
        tickets = db.execute("SELECT COUNT(*) as c FROM team_tickets").fetchone()["c"]
        audit_entries = db.execute("SELECT COUNT(*) as c FROM audit_log").fetchone()["c"]
        shared_files = db.execute("SELECT COUNT(*) as c FROM shared_files").fetchone()["c"]
        contracts = db.execute("SELECT COUNT(*) as c FROM collaboration_contracts WHERE status = 'confirmed'").fetchone()["c"]
        db.close()
        # Check embedding engine status
        try:
            emb = EmbeddingEngine.__new__(EmbeddingEngine)
            emb_status = "not_initialized"
        except Exception:
            emb_status = "unknown"

        return {
            "status": "ok",
            "version": SERVER_VERSION,
            "started_at": _server_start_time,
            "database": DB_PATH,
            "similarity_method": "sentence-transformers (lazy-load on first use)",
            "embedding_model": EMBEDDING_MODEL_NAME,
            "stats": {
                "users": users,
                "commits": commits,
                "matches": matches,
                "teams": teams,
                "pending_requests": pending_requests,
                "ratings": ratings,
                "tickets": tickets,
                "shared_files": shared_files,
                "contracts": contracts,
                "audit_entries": audit_entries,
            },
        }
    except Exception as e:
        return {
            "status": "error",
            "version": SERVER_VERSION,
            "error": str(e),
        }


@mcp.custom_route("/health", methods=["GET"])
async def health_endpoint(request):
    """Health check endpoint for monitoring."""
    from starlette.responses import JSONResponse
    return JSONResponse(_health_stats())


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_db(ctx) -> Optional[sqlite3.Connection]:
    return ctx.request_context.lifespan_context.get("db")

def _get_datastore(ctx) -> Optional[DataStore]:
    return ctx.request_context.lifespan_context.get("datastore")

def _get_evaluator(ctx) -> OriginalityEvaluator:
    return ctx.request_context.lifespan_context["evaluator"]

def _get_matcher(ctx) -> MatchingEngine:
    return ctx.request_context.lifespan_context["matcher"]

def _get_reputation(ctx) -> ReputationEngine:
    return ctx.request_context.lifespan_context["reputation"]

def _get_user_email_hash(ctx) -> str:
    return ctx.request_context.lifespan_context.get("user_email_hash", "")

async def _get_or_create_user(db: Optional[sqlite3.Connection], email: str,
                               pseudonym: Optional[str] = None,
                               datastore: Optional[DataStore] = None) -> str:
    """Get existing user or create new one by email hash."""
    email_hash = hashlib.sha256(email.lower().strip().encode()).hexdigest()

    if datastore:
        rec = await datastore.find_user_by_email_hash(email_hash)
        if rec:
            return rec["id"]
        user_id = str(uuid.uuid4())
        if not pseudonym:
            pseudonym = f"researcher-{user_id[:8]}"
        await datastore.insert_user(user_id, pseudonym, email_hash)
        return user_id

    # SQLite fallback
    row = db.execute("SELECT id FROM users WHERE email_hash = ?", (email_hash,)).fetchone()
    if row:
        return row["id"]

    user_id = str(uuid.uuid4())
    if not pseudonym:
        pseudonym = f"researcher-{user_id[:8]}"

    db.execute(
        "INSERT INTO users (id, pseudonym, email_hash) VALUES (?, ?, ?)",
        (user_id, pseudonym, email_hash)
    )
    db.commit()
    return user_id

async def _get_current_user(db: Optional[sqlite3.Connection],
                             datastore: Optional[DataStore] = None,
                             user_email_hash: str = "") -> Optional[Dict]:
    """Get the current user.

    Multi-user mode (Firestore): looks up user by email hash from env var.
    Single-user mode (SQLite): returns most recently created user.
    """
    if datastore and user_email_hash:
        rec = await datastore.find_user_by_email_hash(user_email_hash)
        return rec
    if datastore:
        rec = await datastore.get_most_recent_user()
        return rec
    # SQLite fallback
    row = db.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 1").fetchone()
    return dict(row) if row else None

def _hash_content(data: Dict) -> str:
    """Create integrity hash of commit content."""
    content = json.dumps(data, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()

def _semaphore_emoji(s: str) -> str:
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(s, "⚪")

def _format_score_bar(score: float, width: int = 20) -> str:
    filled = int(score / 100 * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {score:.1f}%"

def _reputation_badge(score: float, total_ratings: int) -> str:
    """Generate a reputation badge string."""
    if total_ratings < MIN_RATINGS_FOR_REPUTATION:
        return "🆕 New (no ratings yet)"
    elif score >= 85:
        return f"⭐ Excellent ({score:.0f}/100, {total_ratings} ratings)"
    elif score >= 65:
        return f"✅ Good ({score:.0f}/100, {total_ratings} ratings)"
    elif score >= 40:
        return f"⚠️ Mixed ({score:.0f}/100, {total_ratings} ratings)"
    else:
        return f"🚩 Low ({score:.0f}/100, {total_ratings} ratings)"


async def _write_audit_log(db_or_ds, team_id: str, actor_id: str,
                           action: str, resource_ref: str = None, details: dict = None) -> str:
    """Write an immutable entry to the audit log. Returns the log entry ID.

    db_or_ds: either a sqlite3.Connection or a DataStore instance.
    """
    log_id = str(uuid.uuid4())
    details_str = json.dumps(details) if details else None

    if isinstance(db_or_ds, DataStore):
        await db_or_ds.insert_audit_entry(log_id, team_id, actor_id, action, resource_ref, details_str)
    elif db_or_ds is not None:
        db_or_ds.execute(
            """INSERT INTO audit_log (id, team_id, actor_id, action, resource_ref, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (log_id, team_id, actor_id, action, resource_ref, details_str)
        )
    return log_id


async def _check_resharing_violation(db_or_ds, user_id: str,
                                      file_hash: str) -> Optional[dict]:
    """Check if a file hash was already shared by a DIFFERENT user.

    Returns violation info dict if found, None otherwise.
    Only detects cross-user hash collisions — same user sharing
    the same hash in another team is valid (it's their own file).
    """
    if file_hash is None:
        return None

    if isinstance(db_or_ds, DataStore):
        rec = await db_or_ds.find_file_by_hash_other_user(file_hash, user_id)
        if rec:
            return {
                "original_file_id": rec["id"],
                "original_team_id": rec["team_id"],
                "origin_user_id": rec["origin_user_id"],
                "file_path": rec["file_path"],
            }
        return None

    row = db_or_ds.execute(
        "SELECT id, team_id, origin_user_id, file_path FROM shared_files "
        "WHERE file_hash = ? AND origin_user_id != ? LIMIT 1",
        (file_hash, user_id)
    ).fetchone()
    if row:
        return {
            "original_file_id": row["id"],
            "original_team_id": row["team_id"],
            "origin_user_id": row["origin_user_id"],
            "file_path": row["file_path"],
        }
    return None


# --- Contract Helpers (NEED-08) ---

async def _generate_contract_content(db: Optional[sqlite3.Connection], team_id: str,
                                      license_info: dict, contract_version: int,
                                      datastore: Optional[DataStore] = None) -> str:
    """Generate a human-readable markdown collaboration contract.

    Includes both parties, their latest commits with scores, license terms,
    contribution split, reveal state, and verification instructions.
    """
    if datastore:
        team = await datastore.get_team_by_id(team_id)
        team_name = team["name"] if team else f"team-{team_id[:8]}"
        members = await datastore.get_team_members_with_profiles(team_id)
    else:
        team = db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        team_name = team["name"] if team else f"team-{team_id[:8]}"
        members = db.execute(
            """SELECT tm.user_id, tm.role, tm.contribution_percentage, tm.joined_at,
                      u.pseudonym, u.reputation_score
               FROM team_members tm JOIN users u ON tm.user_id = u.id
               WHERE tm.team_id = ?""",
            (team_id,)
        ).fetchall()

    now = datetime.now(timezone.utc).isoformat()
    contract_id = f"{team_id[:8]}-v{contract_version}"
    license_type = license_info["license_type"]

    lines = [
        "# Research Match Collaboration Contract",
        "",
        f"**Contract ID:** `{contract_id}`",
        f"**Team:** `{team_name}` (`{team_id}`)",
        f"**Generated:** {now}",
        f"**Contract Version:** {contract_version}",
        f"**Format Version:** {CONTRACT_VERSION}",
        f"**License Type:** {license_type}",
        "",
        "## Parties",
        "",
    ]

    for m in members:
        m = dict(m)
        pseudo = m["pseudonym"]
        role = m["role"] or "contributor"
        pct = m["contribution_percentage"]
        pct_str = f"{pct:.0f}%" if pct is not None else "TBD"
        joined = m["joined_at"] or "unknown"
        rep = m["reputation_score"] or 100.0

        lines.append(f"### {pseudo}")
        lines.append(f"- **Role:** {role}")
        lines.append(f"- **Contribution:** {pct_str}")
        lines.append(f"- **Joined:** {joined}")
        lines.append(f"- **Reputation:** {rep:.1f}")

        # Latest commit
        if datastore:
            commit = await datastore.get_latest_commit_by_user(m["user_id"])
        else:
            commit = db.execute(
                """SELECT id, version, domain, problem, content_hash,
                          ot_score, ofc_score, overall_solidity,
                          git_repo_url, git_commit_hash
                   FROM research_commits WHERE user_id = ?
                   ORDER BY version DESC LIMIT 1""",
                (m["user_id"],)
            ).fetchone()

        if commit:
            c = dict(commit)
            lines.append(f"- **Latest Commit:** `{c['id'][:12]}...` (v{c['version']})")
            lines.append(f"  - Domain: {c['domain']}")
            lines.append(f"  - Problem: {c['problem'][:80]}{'...' if len(c['problem'] or '') > 80 else ''}")
            lines.append(f"  - Content Hash: `{c['content_hash'][:16]}...`")
            lines.append(f"  - OT: {c['ot_score']:.1f}% / OFC: {c['ofc_score']:.1f}%")
            lines.append(f"  - Solidity: {c['overall_solidity']}")
            if c["git_repo_url"]:
                lines.append(f"  - Git Repo: {c['git_repo_url']}")
            if c["git_commit_hash"]:
                lines.append(f"  - Git Ref: `{c['git_commit_hash']}`")
        else:
            lines.append("- **Latest Commit:** none")

        lines.append("")

    # License Terms
    terms = license_info.get("terms", LICENSE_TERMS.get(license_type, []))
    rationale = license_info.get("rationale", "")

    lines.append("## License Terms")
    lines.append("")
    lines.append(f"**Type:** {license_type}")
    lines.append(f"**Rationale:** {rationale}")
    lines.append("")
    for i, term in enumerate(terms, 1):
        lines.append(f"{i}. {term}")
    lines.append("")

    # Contribution Split
    split = license_info.get("contribution_split", {})
    lines.append("## Contribution Split")
    lines.append("")
    for name, pct in split.items():
        lines.append(f"- **{name}:** {pct:.0f}%")
    lines.append("")

    # Collaboration State
    reveal_state = license_info.get("reveal_state", "none")
    ticket_balance = license_info.get("ticket_balance", {})

    lines.append("## Collaboration State")
    lines.append("")
    lines.append(f"- **Reveal State:** {reveal_state}")
    lines.append(f"- **Tickets Resolved:** {json.dumps(ticket_balance)}")
    lines.append("")

    # Verification
    lines.append("## Verification")
    lines.append("")
    lines.append("This contract is valid when committed to BOTH parties' git repositories.")
    lines.append("Deletion of this file is tracked by git history and constitutes breach.")
    lines.append("")
    lines.append("---")
    lines.append(f"*Generated by Research Match v{SERVER_VERSION}*")

    return "\n".join(lines)


# --- Deep Search Helpers ---

def _import_analyze_repo() -> dict:
    """Lazy-import functions from analyze_repo.py at repo root.

    Returns dict of callable functions needed for deep analysis.
    Raises ImportError if analyze_repo.py cannot be found.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    import analyze_repo
    return {
        "analyze_git": analyze_repo.analyze_git,
        "analyze_readme": analyze_repo.analyze_readme,
        "analyze_file_tree": analyze_repo.analyze_file_tree,
        "analyze_dependencies": analyze_repo.analyze_dependencies,
        "analyze_mcp": analyze_repo.analyze_mcp,
        "compare_tool_lists": analyze_repo.compare_tool_lists,
        "map_repo_to_commit_data": analyze_repo.map_repo_to_commit_data,
        "score_originality": analyze_repo.score_originality,
        "asdict": analyze_repo.asdict,
        "AnalysisReport": analyze_repo.AnalysisReport,
    }


def _find_git_executable() -> str:
    """Find git executable, checking common Windows paths if not in PATH."""
    if shutil.which("git"):
        return "git"
    # Common Windows Git locations
    candidates = [
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "cmd", "git.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Git", "cmd", "git.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Git", "cmd", "git.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise RuntimeError("git executable not found. Install Git or add it to PATH.")


def _deep_search_clone(repo_url: str, target_dir: str) -> None:
    """Shallow-clone a GitHub repo into target_dir.

    Uses --depth 1 --single-branch to minimize download.
    Raises RuntimeError on clone failure or timeout.
    """
    git_cmd = _find_git_executable()
    try:
        result = subprocess.run(
            [git_cmd, "clone", "--depth", "1", "--single-branch", repo_url, target_dir],
            capture_output=True, text=True,
            timeout=DEEP_SEARCH_CLONE_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed: {result.stderr.strip()}")
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"git clone timed out after {DEEP_SEARCH_CLONE_TIMEOUT}s. "
            "The repository may be too large or the network is slow."
        )


def _deep_search_check_size(repo_url: str) -> Optional[int]:
    """Check repo size via GitHub API. Returns size in KB, or None on failure."""
    try:
        # Extract owner/repo from URL
        parts = repo_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        req = urllib.request.Request(api_url, headers={"User-Agent": "ResearchMatch"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("size")  # KB
    except Exception:
        return None


def _deep_search_sanitize_report(report_dict: dict, repo_url: str) -> dict:
    """Replace local filesystem paths with the repo URL in the report.

    Prevents leaking server-side temp directory paths to users.
    """
    if "repo" in report_dict and isinstance(report_dict["repo"], dict):
        report_dict["repo"]["path"] = repo_url
    if "files" in report_dict and isinstance(report_dict["files"], dict):
        largest = report_dict["files"].get("largest_files")
        if largest and isinstance(largest, list):
            sanitized = []
            for entry in largest:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    filepath = str(entry[0])
                    # Strip temp dir prefix, keep relative path
                    parts = filepath.split("/")
                    # Find repo name in path and keep from there
                    rel_path = "/".join(parts[-2:]) if len(parts) >= 2 else filepath
                    sanitized.append([rel_path, entry[1]])
                else:
                    sanitized.append(entry)
            report_dict["files"]["largest_files"] = sanitized
    return report_dict


# =============================================================================
# PROFORMA HELPERS (v2.7)
# =============================================================================

def _detect_project_type(file_stats: dict) -> str:
    """Detect project type from file composition.

    Args:
        file_stats: dict with 'files_by_extension' and 'loc_by_language' keys.

    Returns:
        One of: 'software', 'paper', 'dataset', 'theoretical', 'mixed'.
    """
    exts = file_stats.get("files_by_extension", {})
    loc = file_stats.get("loc_by_language", {})
    total_files = sum(exts.values()) if exts else 0
    if total_files == 0:
        return "mixed"

    # Count category files
    paper_exts = {".tex", ".bib", ".sty", ".cls"}
    data_exts = {".csv", ".parquet", ".json", ".jsonl", ".tsv", ".xlsx", ".sqlite", ".sql"}
    doc_exts = {".md", ".rst", ".txt", ".adoc"}
    code_exts = set(exts.keys()) - paper_exts - data_exts - doc_exts - {".gitignore", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".lock"}

    paper_count = sum(exts.get(e, 0) for e in paper_exts)
    data_count = sum(exts.get(e, 0) for e in data_exts)
    doc_count = sum(exts.get(e, 0) for e in doc_exts)
    code_count = sum(exts.get(e, 0) for e in code_exts)

    # Dominant category heuristic
    if paper_count > 0 and paper_count >= code_count:
        return "paper"
    if data_count > code_count and code_count < 3:
        return "dataset"
    if doc_count > code_count and code_count < 3 and data_count < 3:
        return "theoretical"
    if code_count > 0:
        return "software"
    return "mixed"


def _read_truncated(path: str, max_chars: int = MAX_FILE_READ_CHARS) -> str:
    """Read a file, truncating to max_chars. Handles encoding errors gracefully."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(max_chars)
        if len(content) == max_chars:
            content += "\n... [truncated]"
        return content
    except (OSError, IOError):
        return ""


def _select_key_files(project_path: str, machine_data: dict) -> Dict[str, str]:
    """Select key files for the narrative prompt context.

    Always includes README. Selects main source file (largest LOC),
    config files, and type-specific files. Caps at MAX_KEY_FILES files
    and MAX_PROMPT_TOTAL_CHARS total characters.

    Args:
        project_path: Absolute path to project root.
        machine_data: dict from analyze_repo with repo, files, deps info.

    Returns:
        Dict mapping relative file paths to their (truncated) content.
    """
    candidates: List[str] = []  # relative paths

    # 1. README (always first priority)
    for name in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        readme_path = os.path.join(project_path, name)
        if os.path.isfile(readme_path):
            candidates.append(name)
            break

    # 2. Main source file (largest in loc_by_language or largest_files)
    largest = machine_data.get("files", {}).get("largest_files", [])
    if largest:
        for entry in largest:
            fpath = entry[0] if isinstance(entry, (list, tuple)) else str(entry)
            # Keep only source-like files
            _, ext = os.path.splitext(fpath)
            if ext in (".py", ".js", ".ts", ".rs", ".go", ".java", ".rb", ".cpp", ".c", ".tex"):
                rel = os.path.relpath(fpath, project_path) if os.path.isabs(fpath) else fpath
                if rel not in candidates:
                    candidates.append(rel)
                    break

    # 3. Config files
    for cfg in ("pyproject.toml", "package.json", "Cargo.toml", "setup.py", "setup.cfg"):
        cfg_path = os.path.join(project_path, cfg)
        if os.path.isfile(cfg_path) and cfg not in candidates:
            candidates.append(cfg)
            break

    # 4. Project-type specific
    project_type = machine_data.get("project_type", "software")
    if project_type == "paper":
        # Look for .tex files
        for root, _, files in os.walk(project_path):
            for f in files:
                if f.endswith(".tex"):
                    rel = os.path.relpath(os.path.join(root, f), project_path)
                    if rel not in candidates:
                        candidates.append(rel)
                        break
            break  # Only top level
    elif project_type == "dataset":
        # Look for data documentation
        for name in ("DATA.md", "data/README.md", "CODEBOOK.md", "docs/data.md"):
            if os.path.isfile(os.path.join(project_path, name)) and name not in candidates:
                candidates.append(name)
                break

    # Cap to MAX_KEY_FILES
    candidates = candidates[:MAX_KEY_FILES]

    # Read files, respecting total char budget
    result: Dict[str, str] = {}
    total_chars = 0
    per_file_budget = MAX_PROMPT_TOTAL_CHARS // max(len(candidates), 1)

    for rel_path in candidates:
        abs_path = os.path.join(project_path, rel_path)
        if not os.path.isfile(abs_path):
            continue
        budget = min(MAX_FILE_READ_CHARS, per_file_budget)
        content = _read_truncated(abs_path, budget)
        if total_chars + len(content) > MAX_PROMPT_TOTAL_CHARS:
            remaining = MAX_PROMPT_TOTAL_CHARS - total_chars
            if remaining > 200:
                content = content[:remaining] + "\n... [truncated]"
            else:
                break
        result[rel_path] = content
        total_chars += len(content)

    return result


def _build_narrative_prompt(machine_dict: dict, key_files: Dict[str, str]) -> str:
    """Build the universal prompt template for AI narrative generation.

    Injects machine-extracted data and key file contents into a standardized
    prompt that instructs the AI to generate ProformaNarrativeData JSON.

    Args:
        machine_dict: Machine-extracted project data.
        key_files: Dict of relative paths → file contents.

    Returns:
        Complete prompt string ready for AI execution.
    """
    project_type = machine_dict.get("project_type", "software")

    type_guidance = {
        "software": (
            "This is a SOFTWARE project. Focus on: what problem the code solves, "
            "what algorithms/architectures are used, what is novel vs standard practice, "
            "and the quality of testing/validation."
        ),
        "paper": (
            "This is an ACADEMIC PAPER. Focus on: the research question, methodology, "
            "theoretical contributions, experimental validation, and citation context."
        ),
        "dataset": (
            "This is a DATASET project. Focus on: what data was collected, collection methodology, "
            "what makes it unique, potential applications, and data quality assurance."
        ),
        "theoretical": (
            "This is a THEORETICAL FRAMEWORK. Focus on: the core ideas/axioms, "
            "how they relate to existing theory, what predictions they make, "
            "and what evidence supports them."
        ),
        "mixed": (
            "This is a MIXED project. Identify the primary contribution type "
            "and focus your analysis on the most substantial component."
        ),
    }

    # Machine data summary (compact)
    machine_summary = json.dumps({
        "project_name": machine_dict.get("repo", {}).get("name", "unknown"),
        "readme_title": machine_dict.get("repo", {}).get("readme_title", ""),
        "readme_description": machine_dict.get("repo", {}).get("readme_description", ""),
        "total_commits": machine_dict.get("repo", {}).get("total_commits", 0),
        "contributors": machine_dict.get("repo", {}).get("contributors", 0),
        "code_languages": list(machine_dict.get("files", {}).get("loc_by_language", {}).keys()),
        "total_files": machine_dict.get("files", {}).get("total_files", 0),
        "total_loc": sum(machine_dict.get("files", {}).get("loc_by_language", {}).values()),
        "project_type": project_type,
        "has_tests": any("test" in str(f).lower() for f in machine_dict.get("files", {}).get("files_by_extension", {}).keys()),
    }, indent=2)

    # File contents block
    files_block = ""
    for path, content in key_files.items():
        files_block += f"\n--- FILE: {path} ---\n{content}\n"

    prompt = f"""You are analyzing a project to generate a structured Research Commit for originality evaluation.

## PROJECT TYPE
{type_guidance.get(project_type, type_guidance["mixed"])}

## MACHINE-EXTRACTED DATA (factual, do NOT contradict)
{machine_summary}

## KEY FILE CONTENTS
{files_block}

## YOUR TASK
Generate a JSON object with these 10 fields. Be specific, honest, and detailed.

### Field Instructions:
1. **domain** — The scientific/technical FIELD, NOT the project name. Examples: "natural language processing", "distributed systems", "computational biology". Must be a real academic/technical domain.
2. **subdomain** — Specific niche within the domain. Examples: "transformer architectures", "consensus protocols", "protein folding simulation".
3. **problem** — Start with "How to..." or "The challenge of...". Describe the specific problem this project addresses. Must be >10 characters.
4. **hypothesis** — Format: "That [approach X] can achieve [Y] by [Z]". What does this project bet on? Can be null if purely tooling.
5. **theoretical_framework** — What theories, papers, or established methods does this build on? Be specific with names/references. Can be null for purely practical work.
6. **demonstrations_summary** — What does the code/data/proof actually DO? Be concrete about functionality, not aspirational.
7. **adhoc_summary** — What is genuinely NOVEL here? What hasn't been done before in this combination? Be honest — if it's mostly standard practice, say so.
8. **adhoc_connections** — List of interdisciplinary connections, format: "Applied [X] from [field A] to [field B]". Empty list if none.
9. **cherry_picking** — Declared external sources, format: "[Source] — [what was taken]". Empty list if all original.
10. **solidity_assessment** — Object with:
    - overall_solidity: one of "proven", "functional", "speculative", "adhoc", "cherry_picked"
    - overall_reasoning: why this level (max 500 chars)
    - theory_solidity, theory_reasoning: for theoretical framework
    - demos_solidity, demos_reasoning: for demonstrations/code
    - adhoc_solidity, adhoc_reasoning: for original content

### SOLIDITY IMPACT ON SCORING:
- "proven" → 1.2x multiplier (bonus for peer-reviewed/verified work)
- "functional" → 1.0x (no change, working implementation)
- "speculative" → 0.8x (penalty for unvalidated claims)
- "adhoc" → 0.6x (significant penalty, preliminary ideas)
- "cherry_picked" → 0.4x (heavy penalty, mostly borrowed)
HONEST declaration builds reputation. Overclaiming will be caught by peer review.

### OUTPUT FORMAT:
Return ONLY valid JSON, no markdown code blocks, no explanation. The JSON must match this schema exactly:
{{
  "domain": "string",
  "subdomain": "string or null",
  "problem": "string (>10 chars)",
  "hypothesis": "string or null",
  "theoretical_framework": "string or null",
  "demonstrations_summary": "string or null",
  "adhoc_summary": "string or null",
  "adhoc_connections": ["string", ...],
  "cherry_picking": ["string", ...],
  "solidity_assessment": {{
    "overall_solidity": "string",
    "overall_reasoning": "string",
    "theory_solidity": "string",
    "theory_reasoning": "string",
    "demos_solidity": "string",
    "demos_reasoning": "string",
    "adhoc_solidity": "string",
    "adhoc_reasoning": "string"
  }}
}}"""

    return prompt


def _validate_narrative(machine_dict: dict, narrative: ProformaNarrativeData) -> dict:
    """Validate a filled narrative against machine data and quality rules.

    Returns dict with 'errors' (list, block submit) and 'warnings' (list, informational).

    Args:
        machine_dict: Machine-extracted data from analyze_repo.
        narrative: Parsed ProformaNarrativeData from AI.

    Returns:
        {"errors": [...], "warnings": [...]}
    """
    errors: List[str] = []
    warnings: List[str] = []

    project_name = machine_dict.get("repo", {}).get("name", "").lower()

    # --- Errors (block submit) ---

    # Domain must not be the project name
    if narrative.domain.lower() == project_name and project_name:
        errors.append(
            f"domain '{narrative.domain}' is the project name, not a scientific field. "
            "Use a real domain like 'machine learning', 'distributed systems', etc."
        )

    # Problem must not be a generic placeholder
    if narrative.problem and len(narrative.problem) < 20:
        errors.append(f"problem is too short ({len(narrative.problem)} chars). Describe the actual problem in detail.")

    # Solidity values already validated by Pydantic, but check overall consistency
    sa = narrative.solidity_assessment
    valid_solidities = {sl.value for sl in SolidityLevel}
    for field_name in ("overall_solidity", "theory_solidity", "demos_solidity", "adhoc_solidity"):
        val = getattr(sa, field_name)
        if val not in valid_solidities:
            errors.append(f"solidity_assessment.{field_name} '{val}' is not valid. Must be one of: {sorted(valid_solidities)}")

    # --- Warnings (informational) ---

    if not narrative.hypothesis:
        warnings.append("hypothesis is empty. Consider adding one for better OT scoring.")

    if not narrative.theoretical_framework:
        warnings.append("theoretical_framework is empty. Consider adding references for better scoring.")

    if narrative.demonstrations_summary and len(narrative.demonstrations_summary.split()) < 20:
        warnings.append("demonstrations_summary is very short (<20 words). More detail improves OFC scoring.")

    if not narrative.adhoc_summary:
        warnings.append("adhoc_summary is empty. Describe what is genuinely novel about this work.")

    # Solidity consistency checks
    total_commits = machine_dict.get("repo", {}).get("total_commits", 0)
    has_tests = any("test" in str(k).lower() for k in machine_dict.get("files", {}).get("files_by_extension", {}).keys())

    if sa.demos_solidity == "proven" and not has_tests:
        warnings.append("demos_solidity='proven' but no test files detected. Consider 'functional' or 'speculative'.")
    if sa.overall_solidity == "proven" and total_commits < 10:
        warnings.append(f"overall_solidity='proven' but only {total_commits} commits. Consider a lower level.")
    if sa.overall_solidity == "cherry_picked" and narrative.adhoc_summary and len(narrative.adhoc_summary) > 100:
        warnings.append("overall_solidity='cherry_picked' but adhoc_summary suggests original work. Consider 'adhoc' or higher.")

    return {"errors": errors, "warnings": warnings}


async def _compute_license(db: Optional[sqlite3.Connection], team_id: str,
                            datastore: Optional[DataStore] = None) -> dict:
    """Compute license type and contribution split based on team activity.

    Pure function (reads DB only, no writes). Evaluates 5 rules in order:
      R1: No approved reveals → joint-equal (default)
      R2: Unilateral reveals → advisory-only
      R3: Bilateral reveals + balanced tickets → joint-equal
      R4: Bilateral reveals + asymmetric tickets → joint-weighted
      R5: Team >30 days old with no reveals → time-limited
    """
    # Get team members
    if datastore:
        members = await datastore.get_team_member_pseudonyms(team_id)
    else:
        members = db.execute(
            """SELECT tm.user_id, u.pseudonym
               FROM team_members tm JOIN users u ON tm.user_id = u.id
               WHERE tm.team_id = ?""",
            (team_id,)
        ).fetchall()
    if len(members) < 2:
        return {
            "license_type": "joint-equal",
            "contribution_split": {},
            "rationale": "Team has fewer than 2 members.",
            "terms": LICENSE_TERMS["joint-equal"],
            "reveal_state": "none",
            "ticket_balance": {},
        }

    member_a = dict(members[0])
    member_b = dict(members[1])

    # Check approved Level 3 reveals in each direction
    if datastore:
        a_revealed_to_b = await datastore.count_approved_reveals_direction(
            team_id, member_a["user_id"], member_b["user_id"])
        b_revealed_to_a = await datastore.count_approved_reveals_direction(
            team_id, member_b["user_id"], member_a["user_id"])
    else:
        a_revealed_to_b = db.execute(
            """SELECT COUNT(*) as c FROM reveal_consents
               WHERE team_id = ? AND level = 3 AND status = 'approved'
                 AND approver_id = ? AND requester_id = ?""",
            (team_id, member_a["user_id"], member_b["user_id"])
        ).fetchone()["c"]

        b_revealed_to_a = db.execute(
            """SELECT COUNT(*) as c FROM reveal_consents
               WHERE team_id = ? AND level = 3 AND status = 'approved'
                 AND approver_id = ? AND requester_id = ?""",
            (team_id, member_b["user_id"], member_a["user_id"])
        ).fetchone()["c"]

    total_reveals = a_revealed_to_b + b_revealed_to_a
    bilateral = a_revealed_to_b > 0 and b_revealed_to_a > 0
    unilateral_a = a_revealed_to_b > 0 and b_revealed_to_a == 0  # A revealed, B didn't
    unilateral_b = b_revealed_to_a > 0 and a_revealed_to_b == 0  # B revealed, A didn't

    if bilateral:
        reveal_state = "bilateral"
    elif unilateral_a:
        reveal_state = "unilateral_a"
    elif unilateral_b:
        reveal_state = "unilateral_b"
    else:
        reveal_state = "none"

    # Count resolved tickets per member
    if datastore:
        tickets_a = await datastore.count_resolved_tickets_by_member(team_id, member_a["user_id"])
        tickets_b = await datastore.count_resolved_tickets_by_member(team_id, member_b["user_id"])
    else:
        tickets_a = db.execute(
            """SELECT COUNT(*) as c FROM team_tickets
               WHERE team_id = ? AND resolved_by = ? AND status = 'resolved'""",
            (team_id, member_a["user_id"])
        ).fetchone()["c"]

        tickets_b = db.execute(
            """SELECT COUNT(*) as c FROM team_tickets
               WHERE team_id = ? AND resolved_by = ? AND status = 'resolved'""",
            (team_id, member_b["user_id"])
        ).fetchone()["c"]

    ticket_balance = {
        member_a["pseudonym"]: tickets_a,
        member_b["pseudonym"]: tickets_b,
    }

    # RULE 5: Team >30 days with no reveals → time-limited
    if total_reveals == 0:
        if datastore:
            created = await datastore.get_team_created_at(team_id)
            if created:
                age_days = await datastore.compute_age_in_days(created)
                if age_days > LICENSE_STALE_DAYS:
                    return {
                        "license_type": "time-limited",
                        "contribution_split": {
                            member_a["pseudonym"]: 0,
                            member_b["pseudonym"]: 0,
                        },
                        "rationale": (
                            f"Team is {int(age_days)} days old with no Level 3 reveals. "
                            "Collaboration has not progressed to active sharing."
                        ),
                        "terms": LICENSE_TERMS["time-limited"],
                        "reveal_state": reveal_state,
                        "ticket_balance": ticket_balance,
                    }
        else:
            team_row = db.execute("SELECT created_at FROM teams WHERE id = ?", (team_id,)).fetchone()
            if team_row:
                created = team_row["created_at"]
                age_days_row = db.execute(
                    "SELECT julianday('now') - julianday(?) as age", (created,)
                ).fetchone()
                if age_days_row and age_days_row["age"] is not None and age_days_row["age"] > LICENSE_STALE_DAYS:
                    return {
                        "license_type": "time-limited",
                        "contribution_split": {
                            member_a["pseudonym"]: 0,
                            member_b["pseudonym"]: 0,
                        },
                        "rationale": (
                            f"Team is {int(age_days_row['age'])} days old with no Level 3 reveals. "
                            "Collaboration has not progressed to active sharing."
                        ),
                        "terms": LICENSE_TERMS["time-limited"],
                        "reveal_state": reveal_state,
                        "ticket_balance": ticket_balance,
                    }

    # RULE 1: No approved reveals → joint-equal (default)
    if total_reveals == 0:
        return {
            "license_type": "joint-equal",
            "contribution_split": {
                member_a["pseudonym"]: 50,
                member_b["pseudonym"]: 50,
            },
            "rationale": "Pre-collaboration: no Level 3 reveals yet. Default equal co-authorship.",
            "terms": LICENSE_TERMS["joint-equal"],
            "reveal_state": reveal_state,
            "ticket_balance": ticket_balance,
        }

    # RULE 2: Unilateral reveals → advisory-only
    if unilateral_a or unilateral_b:
        if unilateral_a:
            owner_pseudo = member_a["pseudonym"]
            advisor_pseudo = member_b["pseudonym"]
        else:
            owner_pseudo = member_b["pseudonym"]
            advisor_pseudo = member_a["pseudonym"]
        return {
            "license_type": "advisory-only",
            "contribution_split": {
                owner_pseudo: 100,
                advisor_pseudo: 0,
            },
            "rationale": (
                f"{owner_pseudo} has revealed content but {advisor_pseudo} has not. "
                "One-sided consultation — advisor receives acknowledgment only."
            ),
            "terms": LICENSE_TERMS["advisory-only"],
            "reveal_state": reveal_state,
            "ticket_balance": ticket_balance,
        }

    # Bilateral reveals — check ticket balance
    total_tickets = tickets_a + tickets_b

    # RULE 3: Bilateral + balanced tickets → joint-equal
    if total_tickets == 0:
        return {
            "license_type": "joint-equal",
            "contribution_split": {
                member_a["pseudonym"]: 50,
                member_b["pseudonym"]: 50,
            },
            "rationale": "Bilateral reveals with no resolved tickets yet. Equal co-authorship.",
            "terms": LICENSE_TERMS["joint-equal"],
            "reveal_state": reveal_state,
            "ticket_balance": ticket_balance,
        }

    ratio = max(tickets_a, tickets_b) / min(tickets_a, tickets_b) if min(tickets_a, tickets_b) > 0 else float("inf")

    if ratio < 2.0:
        # RULE 3: Balanced
        return {
            "license_type": "joint-equal",
            "contribution_split": {
                member_a["pseudonym"]: 50,
                member_b["pseudonym"]: 50,
            },
            "rationale": (
                f"Bilateral reveals with balanced ticket resolution "
                f"({tickets_a}:{tickets_b} ratio = {ratio:.1f}x)."
            ),
            "terms": LICENSE_TERMS["joint-equal"],
            "reveal_state": reveal_state,
            "ticket_balance": ticket_balance,
        }

    # RULE 4: Bilateral + asymmetric → joint-weighted
    ratio_a = tickets_a / total_tickets
    ratio_b = tickets_b / total_tickets
    split_a = max(0.25, min(0.75, ratio_a))
    split_b = 1.0 - split_a

    return {
        "license_type": "joint-weighted",
        "contribution_split": {
            member_a["pseudonym"]: round(split_a * 100),
            member_b["pseudonym"]: round(split_b * 100),
        },
        "rationale": (
            f"Bilateral reveals with asymmetric ticket resolution "
            f"({tickets_a}:{tickets_b} ratio = {ratio:.1f}x). "
            f"Weighted split with 25% floor for lesser contributor."
        ),
        "terms": LICENSE_TERMS["joint-weighted"],
        "reveal_state": reveal_state,
        "ticket_balance": ticket_balance,
    }


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool(
    name="research_match_register",
    description=(
        "STEP 1 OF THE RESEARCH MATCH FLOW — Call this tool FIRST before any other research_match tool. "
        "Registers the user with a pseudonymous identity. "
        "REQUIRED FIELDS: email (str, user's email — will be SHA-256 hashed, NEVER stored in plain text). "
        "OPTIONAL FIELDS: pseudonym (str, display name — auto-generated if omitted). "
        "WARNING: Do NOT send 'name' — the field is called 'pseudonym'. Do NOT send 'domain' or any other extra field. "
        "If the user is already registered (same email), returns existing profile (idempotent). "
        "NEXT: guide user to research_match_analyze_work or research_match_submit_commit."
    ),
    annotations={
        "title": "Register on Research Match",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_register(params: RegisterInput, ctx: Context = None) -> str:
    """Register a new user on Research Match. Creates a pseudonymous profile.
    Email is hashed and never stored in plain text. Idempotent: safe to call multiple times.

    Args:
        params (RegisterInput): Registration data containing:
            - email (str): Email address for identity (will be SHA-256 hashed)
            - pseudonym (Optional[str]): Preferred display name (auto-generated if omitted)

    Returns:
        str: JSON with user_id, pseudonym, and welcome message
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user_id = await _get_or_create_user(db, params.email, params.pseudonym, datastore=datastore)

    if datastore:
        user = await datastore.get_user_by_id(user_id)
    else:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    return json.dumps({
        "status": "registered",
        "user_id": user["id"],
        "pseudonym": user["pseudonym"],
        "message": f"Welcome to Research Match! Your pseudonymous identity is '{user['pseudonym']}'. Your email has been hashed — we never store it in plain text."
    }, indent=2)


@mcp.tool(
    name="research_match_submit_commit",
    description=(
        "STEP 2 — Submit a structured Research Commit for AI originality evaluation. "
        "IMPORTANT: Call research_match_analyze_work FIRST to get the template, then fill it with the user's work context. "
        "The commit is evaluated on two independent axes: "
        "Theoretical Originality (OT) — novelty of hypotheses, interdisciplinary connections, ad hoc content; "
        "Formal-Computational Originality (OFC) — code quality, formal methods, validation power. "
        "Solidity levels (proven/functional/speculative/adhoc/cherry_picked) affect score confidence via multipliers. "
        "HONEST solidity declaration builds reputation — collaborators will rate honesty later. "
        "Required fields: domain (e.g. 'machine learning'), problem (min 10 chars). "
        "All other fields are optional but improve score accuracy. "
        "Each submission creates a new version — previous versions are preserved."
    ),
    annotations={
        "title": "Submit Research Commit",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_submit_commit(params: SubmitCommitInput, ctx: Context = None) -> str:
    """Submit a Research Commit for AI evaluation.

    Args:
        params (SubmitCommitInput): Structured research commit with:
            - domain (str, required): Scientific/technical domain
            - problem (str, required): Specific problem being addressed (min 10 chars)
            - subdomain, hypothesis, theoretical_framework (optional): Theory base
            - demonstrations_summary, demo_types, code_languages (optional): Formal work
            - adhoc_summary, adhoc_connections (optional): Original content
            - cherry_picking (optional): Declared external sources
            - solidity_levels (optional): Per-component solidity declaration
            - overall_solidity (optional, default 'speculative'): Overall maturity level

    Returns:
        str: JSON with commit_id, version, OT/OFC scores, solidity impact, and breakdowns
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    evaluator = _get_evaluator(ctx)

    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Please register first with research_match_register."})

    user_id = user["id"]

    # Prepare commit data
    commit_data = params.model_dump()

    # Handle solidity levels serialization
    solidity_dict = {}
    if params.solidity_levels:
        solidity_dict = {k: v.value if v else "speculative" for k, v in params.solidity_levels.model_dump().items()}
    overall_sol = params.overall_solidity.value if params.overall_solidity else "speculative"

    commit_data["solidity_levels"] = solidity_dict
    commit_data["overall_solidity"] = overall_sol

    content_hash = _hash_content(commit_data)

    # AI Evaluation (in production: runs inside TEE enclave)
    scores = await evaluator.evaluate_commit(commit_data, user_id)

    commit_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    if datastore:
        # Get next version
        version = await datastore.get_next_commit_version(user_id)
        # Find previous latest commit to unmark
        prev = await datastore.get_latest_commit_by_user(user_id)
        prev_id = prev["id"] if prev else None

        commit_record = {
            "id": commit_id, "user_id": user_id, "version": version,
            "domain": params.domain, "subdomain": params.subdomain,
            "problem": params.problem, "hypothesis": params.hypothesis,
            "theoretical_framework": params.theoretical_framework,
            "demonstrations_summary": params.demonstrations_summary,
            "demo_types": json.dumps(params.demo_types),
            "code_languages": json.dumps(params.code_languages),
            "adhoc_summary": params.adhoc_summary,
            "adhoc_connections": json.dumps(params.adhoc_connections),
            "cherry_picking": json.dumps(params.cherry_picking),
            "solidity_levels": json.dumps(solidity_dict),
            "overall_solidity": overall_sol,
            "content_hash": content_hash,
            "ot_score": scores["ot_score"], "ofc_score": scores["ofc_score"],
            "ot_breakdown": json.dumps(scores["ot_breakdown"]),
            "ofc_breakdown": json.dumps(scores["ofc_breakdown"]),
            "solidity_impact": json.dumps(scores["solidity_impact"]),
            "git_repo_url": params.git_repo_url,
            "git_commit_hash": params.git_commit_hash,
            "is_latest": True,
            "created_at": now_iso,
        }
        await datastore.submit_commit_and_mark_latest(commit_record, previous_commit_id=prev_id)
    else:
        # Get next version
        last = db.execute(
            "SELECT MAX(version) as v FROM research_commits WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        version = (last["v"] or 0) + 1

        db.execute("""
            INSERT INTO research_commits
            (id, user_id, version, domain, subdomain, problem, hypothesis,
             theoretical_framework, demonstrations_summary, demo_types,
             code_languages, adhoc_summary, adhoc_connections, cherry_picking,
             solidity_levels, overall_solidity,
             content_hash, ot_score, ofc_score, ot_breakdown, ofc_breakdown,
             solidity_impact, git_repo_url, git_commit_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            commit_id, user_id, version,
            params.domain, params.subdomain, params.problem, params.hypothesis,
            params.theoretical_framework, params.demonstrations_summary,
            json.dumps(params.demo_types), json.dumps(params.code_languages),
            params.adhoc_summary, json.dumps(params.adhoc_connections),
            json.dumps(params.cherry_picking),
            json.dumps(solidity_dict), overall_sol,
            content_hash,
            scores["ot_score"], scores["ofc_score"],
            json.dumps(scores["ot_breakdown"]), json.dumps(scores["ofc_breakdown"]),
            json.dumps(scores["solidity_impact"]),
            params.git_repo_url, params.git_commit_hash,
        ))
        db.commit()

    result = {
        "status": "evaluated",
        "commit_id": commit_id,
        "version": version,
        "content_hash": content_hash,
        "scores": {
            "theoretical_originality": scores["ot_score"],
            "formal_computational_originality": scores["ofc_score"],
            "ot_raw": scores["ot_raw"],
            "ofc_raw": scores["ofc_raw"],
            "ot_breakdown": scores["ot_breakdown"],
            "ofc_breakdown": scores["ofc_breakdown"],
        },
        "solidity": {
            "overall": overall_sol,
            "components": solidity_dict,
            "impact": scores["solidity_impact"]["explanation"],
            "ot_multiplier": scores["solidity_impact"]["ot_multiplier"],
            "ofc_multiplier": scores["solidity_impact"]["ofc_multiplier"],
        },
        "profile_summary": f"OT: {scores['ot_score']}% / OFC: {scores['ofc_score']}% (solidity: {overall_sol})",
        "message": "Your Research Commit has been evaluated. Solidity levels affect score confidence. Honest declaration builds your reputation over time."
    }
    if params.git_repo_url:
        result["git_repo_url"] = params.git_repo_url
    if params.git_commit_hash:
        result["git_commit_hash"] = params.git_commit_hash
    return json.dumps(result, indent=2)


@mcp.tool(
    name="research_match_my_profile",
    description=(
        "View the user's current Research Match profile. Shows: "
        "pseudonym, reputation badge and score, latest commit with OT/OFC scores and solidity impact, "
        "score breakdowns per factor, and team memberships. "
        "Call this ANYTIME the user asks about their profile, scores, reputation, or status. "
        "No parameters needed — automatically detects the current user. "
        "If no commits submitted yet, suggests using research_match_submit_commit."
    ),
    annotations={
        "title": "View My Originality Profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_my_profile(ctx: Context = None) -> str:
    """View current originality profile, scores, reputation, and commit history.

    Returns:
        str: JSON with pseudonym, reputation (badge/score/ratings), latest commit scores,
             OT/OFC breakdowns, solidity impact, and team list
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    reputation_engine = _get_reputation(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Please register first."})

    if datastore:
        commits = await datastore.get_commits_by_user(user["id"])
    else:
        commits = db.execute(
            "SELECT * FROM research_commits WHERE user_id = ? ORDER BY version DESC",
            (user["id"],)
        ).fetchall()

    if not commits:
        return json.dumps({
            "user": user["pseudonym"],
            "message": "No Research Commits submitted yet. Use research_match_submit_commit to get started."
        })

    latest = dict(commits[0])
    ot_breakdown = json.loads(latest.get("ot_breakdown") or "{}")
    ofc_breakdown = json.loads(latest.get("ofc_breakdown") or "{}")
    solidity_impact = json.loads(latest.get("solidity_impact") or "{}")

    if datastore:
        teams = await datastore.get_teams_for_user(user["id"])
    else:
        teams = db.execute("""
            SELECT t.* FROM teams t
            JOIN team_members tm ON t.id = tm.team_id
            WHERE tm.user_id = ?
        """, (user["id"],)).fetchall()

    # Get reputation details
    rep = await reputation_engine.calculate_reputation(user["id"])

    return json.dumps({
        "pseudonym": user["pseudonym"],
        "reputation": {
            "badge": _reputation_badge(rep["reputation_score"], rep["total_ratings"]),
            "score": rep["reputation_score"],
            "total_ratings": rep["total_ratings"],
            "avg_honesty": rep["avg_honesty"],
            "avg_quality": rep["avg_quality"],
            "avg_effort": rep["avg_effort"],
        },
        "total_commits": len(commits),
        "latest_commit": {
            "version": latest["version"],
            "domain": latest["domain"],
            "subdomain": latest.get("subdomain"),
            "problem": latest["problem"],
            "scores": {
                "theoretical_originality": latest["ot_score"],
                "formal_computational_originality": latest["ofc_score"],
            },
            "solidity": {
                "overall": latest.get("overall_solidity", "unknown"),
                "components": json.loads(latest.get("solidity_levels") or "{}"),
                "impact": solidity_impact,
            },
            "ot_breakdown": ot_breakdown,
            "ofc_breakdown": ofc_breakdown,
        },
        "teams": [dict(t) for t in teams],
    }, indent=2)


@mcp.tool(
    name="research_match_find_collaborators",
    description=(
        "STEP 3 — Find researchers with COMPLEMENTARY skills in the same domain. "
        "Requires at least one submitted commit (call research_match_submit_commit first). "
        "Returns candidates ranked by complementarity score, each with: "
        "bilateral semaphore (GREEN=high mutual benefit, YELLOW=asymmetric, RED=low benefit), "
        "what YOU gain from them and what THEY gain from you (percentage), "
        "their OT/OFC scores, reputation badge, and solidity level. "
        "The semaphore reason explains WHY the match is convenient or not FROM EACH PERSPECTIVE. "
        "Use min_semaphore='green' to filter only high-value matches, or leave empty to see all. "
        "After finding candidates, use research_match_send_request to initiate collaboration."
    ),
    annotations={
        "title": "Find Potential Collaborators",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_find_collaborators(params: FindCollaboratorsInput, ctx: Context = None) -> str:
    """Find researchers with complementary skills and knowledge.

    Args:
        params (FindCollaboratorsInput): Search parameters:
            - limit (int, default 5): Max candidates to return (1-20)
            - min_semaphore (str, optional): Filter by minimum level: 'green', 'yellow', or 'red'

    Returns:
        str: JSON with your_profile summary and candidates array, each containing:
             pseudonym, user_id, semaphore (with emoji), reason, complementarity %,
             you_gain %, they_gain %, their OT/OFC scores, domain, reputation badge, solidity
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    matcher = _get_matcher(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))

    if not user:
        return json.dumps({"error": "No registered user found. Please register first."})

    matches = await matcher.find_matches(user["id"], params.limit or 5)

    # Filter by semaphore if requested
    if params.min_semaphore:
        priority = {"green": 3, "yellow": 2, "red": 1}
        min_level = priority.get(params.min_semaphore, 0)
        matches = [m for m in matches if priority.get(m["semaphore"], 0) >= min_level]

    if not matches:
        return json.dumps({
            "candidates": [],
            "message": "No matching candidates found yet. As more researchers join your domain, matches will appear."
        })

    # Store matches in DB for later reference
    if datastore:
        for m in matches:
            match_id = str(uuid.uuid4())
            await datastore.upsert_match({
                "id": match_id,
                "user_a_id": user["id"],
                "user_b_id": m["candidate_user_id"],
                "base_similarity": m["base_similarity"],
                "complementarity_score": m["complementarity_score"],
                "semaphore": m["semaphore"],
                "semaphore_reason_a": m.get("semaphore_reason", ""),
                "semaphore_reason_b": m.get("semaphore_reason_for_candidate", ""),
                "semaphore_summary": m.get("semaphore_summary", ""),
                "a_gains_from_b": m["a_gains_from_b"],
                "b_gains_from_a": m["b_gains_from_a"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        # Get user's latest commit scores
        latest_commit = await datastore.get_latest_commit_by_user(user["id"])
        your_profile_str = f"OT: {{'ot_score': {latest_commit['ot_score']}, 'ofc_score': {latest_commit['ofc_score']}}}" if latest_commit else "No commits"
    else:
        for m in matches:
            match_id = str(uuid.uuid4())
            try:
                db.execute("""
                    INSERT OR REPLACE INTO matches
                    (id, user_a_id, user_b_id, base_similarity, complementarity_score,
                     semaphore, semaphore_reason_a, semaphore_reason_b, semaphore_summary,
                     a_gains_from_b, b_gains_from_a)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (match_id, user["id"], m["candidate_user_id"],
                      m["base_similarity"], m["complementarity_score"],
                   m["semaphore"], m.get("semaphore_reason", ""),
                      m.get("semaphore_reason_for_candidate", ""),
                      m.get("semaphore_summary", ""),
                      m["a_gains_from_b"], m["b_gains_from_a"]))
            except sqlite3.IntegrityError:
                pass
        db.commit()
        your_profile_str = f"OT: {dict(db.execute('SELECT ot_score, ofc_score FROM research_commits WHERE user_id = ? ORDER BY version DESC LIMIT 1', (user['id'],)).fetchone())}"

    return json.dumps({
        "your_profile": your_profile_str,
        "candidates": [{
            "pseudonym": m["candidate_pseudonym"],
            "user_id": m["candidate_user_id"],
            "semaphore": f"{_semaphore_emoji(m['semaphore'])} {m['semaphore'].upper()}",
            "semaphore_reason": m.get("semaphore_reason", ""),
            "semaphore_summary": m.get("semaphore_summary", ""),
            "base_similarity": f"{m['base_similarity']}%",
            "complementarity": f"{m['complementarity_score']}%",
            "you_gain": f"{m['a_gains_from_b']}%",
            "they_gain": f"{m['b_gains_from_a']}%",
            "their_scores": f"OT: {m['candidate_ot']}% / OFC: {m['candidate_ofc']}%",
            "domain": m["candidate_domain"],
            "subdomain": m.get("candidate_subdomain", ""),
            "reputation": _reputation_badge(
                m.get("candidate_reputation", 100),
                m.get("candidate_total_ratings", 0)
            ),
            "solidity": m.get("candidate_solidity", "unknown"),
        } for m in matches],
        "total_found": len(matches),
    }, indent=2)


@mcp.tool(
    name="research_match_send_request",
    description=(
        "STEP 4 — Send a collaboration request to a matched researcher. "
        "REQUIRES: You must have run research_match_find_collaborators first to generate a match record. "
        "Pass the candidate_user_id from the find_collaborators results. "
        "The recipient sees the semaphore and scores FROM THEIR OWN PERSPECTIVE — they never see your content. "
        "Include a message describing what you're looking for in the collaboration. "
        "Only one pending request per candidate is allowed. "
        "After sending, the recipient can check their inbox with research_match_inbox and respond with research_match_respond_request. "
        "If both parties accept, a team is created automatically with joint-equal licensing."
    ),
    annotations={
        "title": "Send Collaboration Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_send_request(params: SendRequestInput, ctx: Context = None) -> str:
    """Send a collaboration request to a matched researcher.

    Args:
        params (SendRequestInput): Request data:
            - candidate_user_id (str, required): Target user ID from find_collaborators results
            - message (str, optional): Describe what you're looking for (max 1000 chars)

    Returns:
        str: JSON with request_id, status, semaphore, reason, and next steps
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found."})

    # Find the match record
    if datastore:
        match = await datastore.find_match_between_users(user["id"], params.candidate_user_id)
    else:
        match = db.execute("""
            SELECT * FROM matches
            WHERE (user_a_id = ? AND user_b_id = ?) OR (user_a_id = ? AND user_b_id = ?)
            ORDER BY created_at DESC LIMIT 1
        """, (user["id"], params.candidate_user_id, params.candidate_user_id, user["id"])).fetchone()

    if not match:
        return json.dumps({"error": "No match found with this user. Run find_collaborators first."})

    match = dict(match)

    # Check for existing pending request
    if datastore:
        existing = await datastore.find_pending_request(user["id"], params.candidate_user_id)
    else:
        existing = db.execute("""
            SELECT * FROM collaboration_requests
            WHERE requester_id = ? AND recipient_id = ? AND status = 'pending'
        """, (user["id"], params.candidate_user_id)).fetchone()

    if existing:
        return json.dumps({"error": "You already have a pending request to this user."})

    request_id = str(uuid.uuid4())
    if datastore:
        await datastore.create_collaboration_request({
            "id": request_id,
            "match_id": match["id"],
            "requester_id": user["id"],
            "recipient_id": params.candidate_user_id,
            "message": params.message,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    else:
        db.execute("""
            INSERT INTO collaboration_requests (id, match_id, requester_id, recipient_id, message, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (request_id, match["id"], user["id"], params.candidate_user_id, params.message))
        db.commit()

    return json.dumps({
        "status": "sent",
        "request_id": request_id,
        "semaphore": f"{_semaphore_emoji(match['semaphore'])} {match['semaphore'].upper()}",
        "semaphore_reason": match.get("semaphore_reason_a", ""),
        "message": f"Collaboration request sent! The recipient will see the match from their perspective with their own semaphore reasoning. They will NOT see your content, only scores and the semaphore.",
        "note": "If both parties accept, a gradual revelation process begins."
    }, indent=2)


@mcp.tool(
    name="research_match_inbox",
    description=(
        "View all collaboration requests — both incoming (others requesting you) and outgoing (you requesting others). "
        "Each request shows: requester/recipient pseudonym, semaphore with reason FROM YOUR PERSPECTIVE, "
        "complementarity score, message, status (pending/accepted/rejected/expired), and date. "
        "Call this when the user asks about pending requests, collaboration status, or inbox. "
        "For incoming pending requests, use research_match_respond_request to accept or reject."
    ),
    annotations={
        "title": "View Collaboration Requests",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_inbox(ctx: Context = None) -> str:
    """View incoming and outgoing collaboration requests with semaphore indicators.

    Returns:
        str: JSON with 'incoming' and 'outgoing' arrays, each entry containing:
             request_id, from/to pseudonym, semaphore (emoji + level), reason,
             complementarity %, message, status, and date
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found."})

    if datastore:
        incoming = await datastore.get_incoming_requests_with_details(user["id"])
        outgoing = await datastore.get_outgoing_requests_with_details(user["id"])
    else:
        incoming = db.execute("""
            SELECT cr.*, m.semaphore, m.complementarity_score, m.a_gains_from_b, m.b_gains_from_a,
                   m.semaphore_reason_b, m.semaphore_summary,
                   u.pseudonym as requester_pseudonym
            FROM collaboration_requests cr
            JOIN matches m ON cr.match_id = m.id
            JOIN users u ON cr.requester_id = u.id
            WHERE cr.recipient_id = ?
            ORDER BY cr.created_at DESC
        """, (user["id"],)).fetchall()

        outgoing = db.execute("""
            SELECT cr.*, m.semaphore, m.complementarity_score,
                   m.semaphore_reason_a, m.semaphore_summary,
                   u.pseudonym as recipient_pseudonym
            FROM collaboration_requests cr
            JOIN matches m ON cr.match_id = m.id
            JOIN users u ON cr.recipient_id = u.id
            WHERE cr.requester_id = ?
            ORDER BY cr.created_at DESC
        """, (user["id"],)).fetchall()

    return json.dumps({
        "incoming": [{
            "request_id": dict(r)["id"],
            "from": dict(r)["requester_pseudonym"],
            "semaphore": f"{_semaphore_emoji(dict(r)['semaphore'])} {dict(r)['semaphore'].upper()}",
            "semaphore_reason": dict(r).get("semaphore_reason_b", ""),
            "semaphore_summary": dict(r).get("semaphore_summary", ""),
            "complementarity": f"{dict(r)['complementarity_score']}%",
            "message": dict(r).get("message", ""),
            "status": dict(r)["status"],
            "date": dict(r)["created_at"],
        } for r in incoming],
        "outgoing": [{
            "request_id": dict(r)["id"],
            "to": dict(r)["recipient_pseudonym"],
            "semaphore": f"{_semaphore_emoji(dict(r)['semaphore'])} {dict(r)['semaphore'].upper()}",
            "semaphore_reason": dict(r).get("semaphore_reason_a", ""),
            "semaphore_summary": dict(r).get("semaphore_summary", ""),
            "complementarity": f"{dict(r)['complementarity_score']}%",
            "status": dict(r)["status"],
            "date": dict(r)["created_at"],
        } for r in outgoing],
    }, indent=2)


@mcp.tool(
    name="research_match_respond_request",
    description=(
        "Accept or reject an incoming collaboration request. "
        "Get the request_id from research_match_inbox (incoming requests). "
        "If ACCEPTED: a team is automatically created with joint-equal licensing (50/50), "
        "both users become co-leads, and the gradual revelation process begins. "
        "After team formation, both members can rate each other using research_match_rate_user. "
        "If REJECTED: the request is closed. The requester can see the rejection in their outbox. "
        "Only pending requests can be responded to — already accepted/rejected requests cannot be changed."
    ),
    annotations={
        "title": "Respond to Collaboration Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_respond_request(params: RespondRequestInput, ctx: Context = None) -> str:
    """Accept or reject a collaboration request.

    Args:
        params (RespondRequestInput): Response data:
            - request_id (str, required): ID of the request (from research_match_inbox)
            - accept (bool, required): true to accept, false to reject

    Returns:
        str: JSON with status ('accepted'/'rejected'), and if accepted: team_id, team_name, license type
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found."})

    if datastore:
        request = await datastore.get_request_for_recipient(params.request_id, user["id"])
    else:
        request = db.execute(
            "SELECT * FROM collaboration_requests WHERE id = ? AND recipient_id = ?",
            (params.request_id, user["id"])
        ).fetchone()

    if not request:
        return json.dumps({"error": "Request not found or you're not the recipient."})

    request = dict(request)
    if request["status"] != "pending":
        return json.dumps({"error": f"Request already {request['status']}."})

    new_status = "accepted" if params.accept else "rejected"
    now_iso = datetime.now(timezone.utc).isoformat()

    result = {"status": new_status, "request_id": params.request_id}

    if params.accept:
        team_id = str(uuid.uuid4())
        team_name = f"team-{team_id[:8]}"

        if datastore:
            await datastore.update_request_status(params.request_id, new_status, now_iso)
            await datastore.create_team_with_members(
                team={"id": team_id, "name": team_name, "license_type": "joint-equal", "created_at": now_iso},
                members=[
                    {"team_id": team_id, "user_id": user["id"], "role": "co-lead", "joined_at": now_iso},
                    {"team_id": team_id, "user_id": request["requester_id"], "role": "co-lead", "joined_at": now_iso},
                ],
            )
        else:
            db.execute("""
                UPDATE collaboration_requests
                SET status = ?, responded_at = datetime('now')
                WHERE id = ?
            """, (new_status, params.request_id))
            db.execute(
                "INSERT INTO teams (id, name, license_type) VALUES (?, ?, 'joint-equal')",
                (team_id, team_name)
            )
            db.execute(
                "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')",
                (team_id, user["id"])
            )
            db.execute(
                "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')",
                (team_id, request["requester_id"])
            )

        await _write_audit_log(datastore or db, team_id, user["id"], "license_generated",
                         resource_ref=team_id,
                         details={"license_type": "joint-equal",
                                  "members": [user["id"], request["requester_id"]]})
        if db:
            db.commit()

        result["team"] = {
            "team_id": team_id,
            "team_name": team_name,
            "license": "joint-equal",
            "message": (
                "Team created! NEXT STEPS: "
                "(1) research_match_reveal_request to request Level 3 reveal of your teammate's full Research Commit, "
                "(2) research_match_needs_create to create tickets (needs, offers, questions), "
                "(3) research_match_needs_list to see the team board, "
                "(4) research_match_needs_resolve to close tickets, "
                "(5) After bilateral Level 3 reveals: research_match_share_file to share supporting files. "
                "(6) Use research_match_audit_log to review team activity and compliance. "
                "(7) Use research_match_export_contract to generate a git-verifiable collaboration contract. "
                "After collaborating, use research_match_rate_user to rate each other."
            ),
        }
    else:
        if datastore:
            await datastore.update_request_status(params.request_id, new_status, now_iso)
        else:
            db.execute("""
                UPDATE collaboration_requests
                SET status = ?, responded_at = datetime('now')
                WHERE id = ?
            """, (new_status, params.request_id))
            db.commit()
        result["message"] = "Request rejected."

    return json.dumps(result, indent=2)


@mcp.tool(
    name="research_match_rate_user",
    description=(
        "Rate a collaborator after working together in a team. "
        "ANTI-RETALIATION: Ratings are ANONYMOUS until BOTH team members have rated each other. "
        "This means you can rate honestly without fear of revenge ratings. "
        "Three dimensions — Honesty (1-5): did they declare solidity levels accurately? "
        "Quality (1-5): was their work well-structured and valuable? "
        "Effort (1-5): did they contribute meaningfully to the collaboration? "
        "HONESTY HAS THE HIGHEST WEIGHT (50%) in reputation calculation. "
        "Low honesty ratings severely penalize reputation. "
        "The system detects abusive patterns (always 1-star, always 5-star, zero variance). "
        "Ratings CANNOT be modified after submission to prevent gaming. "
        "Once both members rate, ratings are revealed simultaneously and reputations update."
    ),
    annotations={
        "title": "Rate a Collaborator",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_rate_user(params: RateUserInput, ctx: Context = None) -> str:
    """Rate a collaborator after working together in a team.

    Args:
        params (RateUserInput): Rating data:
            - team_id (str, required): ID of the team where you collaborated
            - rated_user_id (str, required): User ID of the person to rate
            - honesty (int, required): 1-5, accuracy of solidity declarations
            - quality (int, required): 1-5, work structure and value
            - effort (int, required): 1-5, meaningful contribution level
            - comment (str, optional): Private comment (visible after both rate, max 500 chars)

    Returns:
        str: JSON with rating_id, anonymous status, both_rated flag, and if both rated:
             their rating of you and updated reputation scores
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    reputation_engine = _get_reputation(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found."})

    # Verify the rater is a member of the team
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Verify the rated user is also a member
    if datastore:
        rated_membership = await datastore.get_team_member(params.team_id, params.rated_user_id)
    else:
        rated_membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, params.rated_user_id)
        ).fetchone()
    if not rated_membership:
        return json.dumps({"error": "The rated user is not a member of this team."})

    # Can't rate yourself
    if user["id"] == params.rated_user_id:
        return json.dumps({"error": "You cannot rate yourself."})

    # Check if already rated
    if datastore:
        existing = await datastore.get_rating(params.team_id, user["id"], params.rated_user_id)
    else:
        existing = db.execute(
            "SELECT id FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
            (params.team_id, user["id"], params.rated_user_id)
        ).fetchone()
    if existing:
        return json.dumps({"error": "You have already rated this user for this team. Ratings cannot be modified to prevent gaming."})

    # Check for abuse patterns
    abuse = await reputation_engine.detect_abuse_patterns(user["id"])
    abuse_warning = ""
    if abuse["abuse_detected"]:
        abuse_warning = f" Warning: Your rating patterns show {', '.join(abuse['flags'])}. Continued abuse may affect your own reputation."

    # Submit rating
    rating_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if datastore:
        await datastore.insert_rating({
            "id": rating_id, "team_id": params.team_id,
            "rater_id": user["id"], "rated_id": params.rated_user_id,
            "honesty": params.honesty, "quality": params.quality,
            "effort": params.effort, "comment": params.comment,
            "is_revealed": False, "created_at": now_iso,
        })
    else:
        db.execute("""
            INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (rating_id, params.team_id, user["id"], params.rated_user_id,
              params.honesty, params.quality, params.effort, params.comment))
        db.commit()

    # Check if both have rated each other
    both_rated = await reputation_engine.check_both_rated(
        params.team_id, user["id"], params.rated_user_id
    )

    result = {
        "status": "submitted",
        "rating_id": rating_id,
        "anonymous": not both_rated,
        "both_rated": both_rated,
    }

    if both_rated:
        # Reveal ratings and update reputations
        await reputation_engine.reveal_ratings(params.team_id)
        await reputation_engine.update_user_reputation(params.rated_user_id)
        await reputation_engine.update_user_reputation(user["id"])

        # Get the other person's rating of you
        if datastore:
            their_rating = await datastore.get_rating(params.team_id, params.rated_user_id, user["id"])
        else:
            their_rating = db.execute(
                "SELECT * FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
                (params.team_id, params.rated_user_id, user["id"])
            ).fetchone()

        if their_rating:
            their_rating = dict(their_rating)
            result["their_rating_of_you"] = {
                "honesty": their_rating["honesty"],
                "quality": their_rating["quality"],
                "effort": their_rating["effort"],
                "comment": their_rating.get("comment", ""),
            }

        result["message"] = "Both team members have rated. Ratings are now revealed and reputations updated."
    else:
        result["message"] = f"Rating submitted anonymously. It will be revealed when the other team member also rates.{abuse_warning}"

    return json.dumps(result, indent=2)


@mcp.tool(
    name="research_match_analyze_work",
    description=(
        "HELPER — Call this BEFORE research_match_submit_commit to get the Research Commit template. "
        "Returns a structured template with all fields and instructions for filling each section. "
        "After calling this, review the conversation context and help the user fill out each section "
        "based on their current work. Then call research_match_submit_commit with the structured data. "
        "Includes solidity guide: proven (x1.0), functional (x0.85), speculative (x0.60), "
        "adhoc (x0.40), cherry_picked (x0.30). "
        "IMPORTANT: Coach the user to be HONEST about solidity levels — their reputation depends on it."
    ),
    annotations={
        "title": "Analyze Current Work for Research Commit",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_analyze_work(ctx: Context = None) -> str:
    """Returns the Research Commit template for Claude to help fill out.

    Returns:
        str: JSON with template structure (theory_base, demonstrations, adhoc_content,
             cherry_picking, solidity_levels), solidity guide with multipliers, and instructions
    """
    return json.dumps({
        "message": "I'll help you create a Research Commit. Based on your work, I need to fill out these sections:",
        "template": {
            "theory_base": {
                "domain": "Main scientific/technical field",
                "subdomain": "Your specialization",
                "problem": "The specific question you're trying to answer",
                "hypothesis": "Your central proposition",
                "theoretical_framework": "What theories/authors you build on",
            },
            "demonstrations": {
                "summary": "Describe your proofs, code, simulations, experiments",
                "types": "Select: math, code, data, proof_assistant, simulation",
                "languages": "Programming languages used",
            },
            "adhoc_content": {
                "summary": "Original ideas not from established theory",
                "connections": "Interdisciplinary connections you've made",
            },
            "cherry_picking": {
                "declared_sources": "What you took from other works and why",
            },
            "solidity_levels": {
                "overall_solidity": "Overall: proven | functional | speculative | adhoc | cherry_picked",
                "per_component": {
                    "theory": "How solid is your theoretical framework?",
                    "demos": "How solid are your demonstrations/code/proofs?",
                    "adhoc": "How solid is your original content?",
                    "cherry_picking": "Always 'cherry_picked' for curated content",
                },
                "note": "Be HONEST. Your reputation depends on accurate self-assessment. Collaborators will rate your honesty."
            },
        },
        "solidity_guide": {
            "proven": "Formally verified, peer-reviewed, or independently reproducible. Score multiplier: x1.0",
            "functional": "Working code, reproducible results, but not formally proven. Score multiplier: x0.85",
            "speculative": "Theoretical reasoning without full validation. Score multiplier: x0.60",
            "adhoc": "Original intuition, preliminary ideas. Score multiplier: x0.40",
            "cherry_picked": "Curated from external sources. Score multiplier: x0.30",
        },
        "instruction": "Review the conversation context and help the user fill each section, including honest solidity assessment. Then call research_match_submit_commit with the structured data."
    }, indent=2)


# =============================================================================
# COLD SEARCH — FREE, NO REGISTRATION REQUIRED
# =============================================================================

logger = logging.getLogger("research_match")


async def _cold_search_internal(db: Optional[sqlite3.Connection], query: str, limit: int,
                                 datastore: Optional[DataStore] = None) -> List[Dict]:
    """Search the internal database for public research commits matching a query.
    Returns basic info only: domain, subdomain, problem, hypothesis, solidity."""
    keywords = query.lower().split()
    if not keywords:
        return []

    if datastore:
        # Use DataStore (Algolia in Firestore mode, Firestore fallback otherwise)
        recs = await datastore.search_commits_by_keywords(keywords[:5], limit)
        return [
            {
                "source": "internal",
                "pseudonym": r.get("pseudonym", ""),
                "domain": r.get("domain", ""),
                "subdomain": r.get("subdomain", ""),
                "problem": r.get("problem", ""),
                "hypothesis": r.get("hypothesis", ""),
                "solidity": r.get("overall_solidity", "unknown"),
                "date": r.get("created_at", ""),
            }
            for r in recs
        ]

    # SQLite fallback: LIKE queries
    conditions = []
    params = []
    for kw in keywords[:5]:
        pattern = f"%{kw}%"
        conditions.append(
            "(LOWER(domain) LIKE ? OR LOWER(subdomain) LIKE ? "
            "OR LOWER(problem) LIKE ? OR LOWER(hypothesis) LIKE ?)"
        )
        params.extend([pattern, pattern, pattern, pattern])

    where_clause = " AND ".join(conditions)

    rows = db.execute(f"""
        SELECT rc.domain, rc.subdomain, rc.problem, rc.hypothesis,
               rc.overall_solidity, rc.created_at,
               u.pseudonym
        FROM research_commits rc
        JOIN users u ON rc.user_id = u.id
        WHERE {where_clause}
        ORDER BY rc.created_at DESC
        LIMIT ?
    """, params + [limit]).fetchall()

    results = []
    for row in rows:
        row = dict(row)
        results.append({
            "source": "internal",
            "pseudonym": row["pseudonym"],
            "domain": row["domain"],
            "subdomain": row.get("subdomain", ""),
            "problem": row.get("problem", ""),
            "hypothesis": row.get("hypothesis", ""),
            "solidity": row.get("overall_solidity", "unknown"),
            "date": row.get("created_at", ""),
        })
    return results


def _cold_search_github(query: str, limit: int) -> List[Dict]:
    """Search GitHub public repositories as a fallback/complement.
    Returns basic info only: name, description, URL, language."""
    try:
        encoded_query = urllib.parse.quote(query)
        url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=updated&per_page={limit}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "ResearchMatch-MCP/2.1",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        results = []
        for item in data.get("items", [])[:limit]:
            results.append({
                "source": "github",
                "name": item.get("full_name", ""),
                "description": (item.get("description") or "")[:200],
                "url": item.get("html_url", ""),
                "language": item.get("language", "unknown"),
                "stars": item.get("stargazers_count", 0),
                "updated": item.get("updated_at", ""),
            })
        return results
    except Exception as e:
        logger.warning("GitHub cold search failed: %s", e)
        return []


@mcp.tool(
    name="research_match_cold_search",
    description=(
        "FREE cold search — NO REGISTRATION REQUIRED. Anyone can use this tool. "
        "Searches for research topics, domains, or technologies across TWO sources: "
        "(1) ResearchMatch internal database — shows pseudonym, domain, problem, solidity of registered researchers; "
        "(2) GitHub public repositories — shows repo name, description, language, stars, URL. "
        "Returns basic public info ONLY — no scores, no private data, no contact info. "
        "Use this to explore what's out there BEFORE registering. "
        "Good queries: domain names ('machine learning'), specific topics ('protein folding'), "
        "technologies ('rust compiler'), or broad fields ('quantum computing'). "
        "If no results, try broader keywords. Internal DB grows as more researchers join."
    ),
)
@_log_tool_call
async def research_match_cold_search(params: ColdSearchInput, ctx: Context = None) -> str:
    """Execute a cold search across internal DB and GitHub."""
    query = params.query
    limit = params.max_results

    # Always search BOTH sources with full limit each.
    # Internal results may be few (early-stage DB), but external repos are
    # always valuable — there could be 1000 useful projects out there even
    # when the internal DB has matches.
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    internal_results = await _cold_search_internal(db, query, limit, datastore=datastore)
    github_results = _cold_search_github(query, limit)

    total = len(internal_results) + len(github_results)
    if total == 0:
        return json.dumps({
            "status": "no_results",
            "message": f"No results found for '{query}'. Try broader keywords.",
            "tip": "Cold search is FREE. Try terms like: 'machine learning', 'graph theory', 'rust compiler'.",
        }, indent=2)

    return json.dumps({
        "status": "ok",
        "query": query,
        "total_results": total,
        "note": "Cold search is FREE — no registration needed. Register to submit your own work and find collaborators.",
        "internal_results": internal_results,
        "github_results": github_results,
    }, indent=2)


@mcp.tool(
    name="research_match_deep_search",
    description=(
        "FREE deep analysis — NO REGISTRATION REQUIRED. "
        "Given a GitHub repository URL (from cold_search results), clones and analyzes: "
        "Layer 1: Git metadata, file tree, LOC by language, dependencies. "
        "Layer 2: MCP framework/tool extraction (Python + JS/TS). "
        "Layer 3: Gap analysis comparing target vs Research Match. "
        "Layer 4 (optional): Originality scoring via OT/OFC evaluator. "
        "Returns structured JSON. Use after cold_search to evaluate a repo deeply. "
        "Example: repo_url='https://github.com/owner/repo', include_scoring=true."
    ),
    annotations={
        "title": "Deep Repository Analysis",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
@_log_tool_call
async def research_match_deep_search(params: DeepSearchInput, ctx: Context = None) -> str:
    """Clone and deeply analyze a GitHub repository.

    Args:
        params (DeepSearchInput): Analysis parameters:
            - repo_url (str): GitHub URL (https://github.com/owner/repo)
            - include_mcp_analysis (bool): Layer 2 MCP extraction (default True)
            - include_comparison (bool): Layer 3 gap analysis (default True)
            - include_scoring (bool): Layer 4 originality scoring (default False)

    Returns:
        str: JSON with structured analysis report or error details
    """
    repo_url = params.repo_url

    try:
        # Extract owner/repo from URL
        url_parts = repo_url.rstrip("/").split("/")
        owner, repo_name = url_parts[-2], url_parts[-1]

        # --- GitHub API-only analysis (no clone — avoids MCP timeout) ---
        api_base = f"https://api.github.com/repos/{owner}/{repo_name}"
        api_headers = {"User-Agent": "ResearchMatch-MCP/2.8"}

        def _gh_api(endpoint: str = "") -> Optional[dict]:
            try:
                url = f"{api_base}{endpoint}"
                req = urllib.request.Request(url, headers=api_headers)
                with urllib.request.urlopen(req, timeout=8) as resp:
                    return json.loads(resp.read())
            except Exception:
                return None

        # Fetch repo metadata
        repo_data = _gh_api()
        if not repo_data:
            return json.dumps({"error": f"Cannot access {repo_url}. Check URL and that repo is public."})

        size_mb = round(repo_data.get("size", 0) / 1024, 1)

        # Fetch languages
        languages = _gh_api("/languages") or {}

        # Fetch recent commits (top 5)
        commits_data = _gh_api("/commits?per_page=5") or []
        recent_commits = []
        for c in commits_data:
            if isinstance(c, dict) and "commit" in c:
                recent_commits.append({
                    "sha": c["sha"][:8],
                    "message": (c["commit"]["message"] or "")[:100],
                    "date": c["commit"]["committer"]["date"],
                })

        # Fetch top-level file tree
        default_branch = repo_data.get("default_branch", "main")
        tree_data = _gh_api(f"/git/trees/{default_branch}") or {}
        top_files = [
            {"path": item["path"], "type": item["type"], "size": item.get("size", 0)}
            for item in tree_data.get("tree", [])
        ]

        # Fetch README preview
        readme_preview = ""
        readme_data = _gh_api("/readme")
        if readme_data and readme_data.get("content"):
            import base64
            try:
                raw = base64.b64decode(readme_data["content"]).decode("utf-8", errors="replace")
                readme_preview = raw[:500]
            except Exception:
                readme_preview = "(could not decode)"

        # Check for dependency files
        deps_found = {}
        for dep_file in ["requirements.txt", "pyproject.toml", "package.json", "Cargo.toml", "go.mod"]:
            dep_data = _gh_api(f"/contents/{dep_file}")
            if dep_data and dep_data.get("content"):
                import base64
                try:
                    content = base64.b64decode(dep_data["content"]).decode("utf-8", errors="replace")
                    deps_found[dep_file] = content[:300]
                except Exception:
                    deps_found[dep_file] = "(present but could not decode)"

        # Build analysis report
        analysis = {
            "repo": {
                "name": repo_data.get("full_name"),
                "description": repo_data.get("description", ""),
                "default_branch": default_branch,
                "stars": repo_data.get("stargazers_count", 0),
                "forks": repo_data.get("forks_count", 0),
                "open_issues": repo_data.get("open_issues_count", 0),
                "created_at": repo_data.get("created_at"),
                "updated_at": repo_data.get("updated_at"),
                "license": (repo_data.get("license") or {}).get("spdx_id", "None"),
                "topics": repo_data.get("topics", []),
            },
            "size_mb": size_mb,
            "languages": languages,
            "primary_language": repo_data.get("language"),
            "total_bytes": sum(languages.values()),
            "top_level_files": top_files[:30],
            "recent_commits": recent_commits,
            "readme_preview": readme_preview,
            "dependency_files": deps_found,
        }

        layers_executed = {"generic": True, "mcp": False, "comparison": False, "scoring": False}

        return json.dumps({
            "status": "ok",
            "repo_url": repo_url,
            "repo_size_mb": size_mb,
            "layers_executed": layers_executed,
            "analysis": analysis,
            "note": "API-based analysis (no clone). For full clone-based analysis with MCP extraction and scoring, use the CLI version.",
        }, indent=2, default=str)

    except Exception as e:
        logger.error(f"Deep search failed for {repo_url}: {e}")
        return json.dumps({
            "error": f"Unexpected error during deep analysis: {e}",
            "tip": "Try again or use cold_search for surface-level info.",
        }, indent=2)


# =============================================================================
# COLLABORATION LAYER TOOLS (v2.4)
# =============================================================================

@mcp.tool(
    name="research_match_needs_create",
    description=(
        "POST-TEAM STEP — Create a structured ticket for your team. "
        "Tickets replace free-form chat with 'intellectual pull requests': "
        "type 'need_help' (request assistance), 'can_offer' (volunteer a skill), "
        "'warning' (flag a risk), 'question' (ask for clarification). "
        "Each ticket targets an area: theory, code, data, review, infrastructure. "
        "Priority: critical > important > nice_to_have. "
        f"Max {MAX_OPEN_TICKETS_PER_USER_PER_TEAM} open tickets per user per team. "
        "After creating, use research_match_needs_list to see all tickets, "
        "or research_match_needs_resolve to close them. "
        "Example: type='need_help', area='code', title='Need GPU optimization for MD sim', priority='critical'."
    ),
    annotations={
        "title": "Create Team Ticket",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_needs_create(params: NeedsCreateInput, ctx: Context = None) -> str:
    """Create a structured ticket in a team.

    Args:
        params (NeedsCreateInput): Ticket data:
            - team_id (str): Team ID
            - type (str): need_help|can_offer|warning|question
            - area (str): theory|code|data|review|infrastructure
            - title (str): 5-200 chars
            - description (str): 10-2000 chars
            - priority (str): critical|important|nice_to_have (default: important)

    Returns:
        str: JSON with ticket_id, remaining slots, and next_step guidance
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify user is a member of the team
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Check open ticket limit
    if datastore:
        open_count = await datastore.count_open_tickets_by_user(params.team_id, user["id"])
    else:
        open_count = db.execute(
            "SELECT COUNT(*) as c FROM team_tickets WHERE team_id = ? AND author_id = ? AND status IN ('open', 'in_progress')",
            (params.team_id, user["id"])
        ).fetchone()["c"]
    if open_count >= MAX_OPEN_TICKETS_PER_USER_PER_TEAM:
        return json.dumps({
            "error": f"You already have {open_count} open tickets in this team (max {MAX_OPEN_TICKETS_PER_USER_PER_TEAM}). "
                     "Resolve existing tickets before creating new ones."
        })

    ticket_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if datastore:
        await datastore.insert_ticket({
            "id": ticket_id, "team_id": params.team_id, "author_id": user["id"],
            "type": params.type, "area": params.area, "title": params.title,
            "description": params.description, "priority": params.priority,
            "status": "open", "created_at": now_iso,
        })
    else:
        db.execute(
            """INSERT INTO team_tickets (id, team_id, author_id, type, area, title, description, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticket_id, params.team_id, user["id"], params.type, params.area,
             params.title, params.description, params.priority)
        )

    await _write_audit_log(datastore or db, params.team_id, user["id"], "ticket_created",
                     resource_ref=ticket_id,
                     details={"type": params.type, "area": params.area, "priority": params.priority})
    if db:
        db.commit()

    remaining_slots = MAX_OPEN_TICKETS_PER_USER_PER_TEAM - open_count - 1
    return json.dumps({
        "status": "created",
        "ticket_id": ticket_id,
        "type": params.type,
        "area": params.area,
        "priority": params.priority,
        "title": params.title,
        "remaining_open_slots": remaining_slots,
        "next_step": "Use research_match_needs_list to see all team tickets, or research_match_needs_resolve to close tickets.",
    }, indent=2)


@mcp.tool(
    name="research_match_needs_list",
    description=(
        "POST-TEAM STEP — List all tickets in a team with optional filters. "
        "Shows structured needs, offers, warnings, and questions from all team members. "
        "Filter by status (open, in_progress, resolved, wont_fix), "
        "area (theory, code, data, review, infrastructure), "
        "or type (need_help, can_offer, warning, question). "
        "Tickets are ordered by priority (critical first) then by creation date. "
        "Returns a summary with counts plus the full ticket list with pseudonyms. "
        "Use after research_match_needs_create, or to check team progress."
    ),
    annotations={
        "title": "List Team Tickets",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_needs_list(params: NeedsListInput, ctx: Context = None) -> str:
    """List tickets in a team with optional filters.

    Args:
        params (NeedsListInput): Filter criteria:
            - team_id (str, required): Team ID
            - status (str, optional): Filter by status
            - area (str, optional): Filter by area
            - type (str, optional): Filter by type

    Returns:
        str: JSON with summary counts and ticket list
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    if datastore:
        filters = {}
        if params.status:
            filters["status"] = params.status
        if params.area:
            filters["area"] = params.area
        if params.type:
            filters["type"] = params.type
        rows = await datastore.list_tickets(params.team_id, **filters)
        summary_raw = await datastore.count_tickets_by_status(params.team_id)
        summary = summary_raw
    else:
        # Build query with optional filters
        query = "SELECT t.*, u.pseudonym as author_pseudonym FROM team_tickets t JOIN users u ON t.author_id = u.id WHERE t.team_id = ?"
        query_params: list = [params.team_id]

        if params.status:
            query += " AND t.status = ?"
            query_params.append(params.status)
        if params.area:
            query += " AND t.area = ?"
            query_params.append(params.area)
        if params.type:
            query += " AND t.type = ?"
            query_params.append(params.type)

        # Order by priority (critical > important > nice_to_have), then by date
        query += """
            ORDER BY
                CASE t.priority
                    WHEN 'critical' THEN 1
                    WHEN 'important' THEN 2
                    WHEN 'nice_to_have' THEN 3
                END,
                t.created_at DESC
        """

        rows = db.execute(query, query_params).fetchall()

        # Build summary counts
        all_tickets = db.execute(
            "SELECT status, COUNT(*) as c FROM team_tickets WHERE team_id = ? GROUP BY status",
            (params.team_id,)
        ).fetchall()
        summary = {dict(r)["status"]: dict(r)["c"] for r in all_tickets}

    tickets = []
    for r in rows:
        rd = dict(r)
        ticket = {
            "ticket_id": rd["id"],
            "type": rd["type"],
            "area": rd["area"],
            "title": rd["title"],
            "description": rd["description"],
            "priority": rd["priority"],
            "status": rd["status"],
            "author": rd.get("author_pseudonym", rd.get("pseudonym", "")),
            "created_at": rd["created_at"],
            "updated_at": rd.get("updated_at"),
        }
        if rd.get("resolved_by"):
            if datastore:
                resolver = await datastore.get_user_by_id(rd["resolved_by"])
                ticket["resolved_by"] = resolver["pseudonym"] if resolver else rd["resolved_by"]
            else:
                resolver = db.execute("SELECT pseudonym FROM users WHERE id = ?", (rd["resolved_by"],)).fetchone()
                ticket["resolved_by"] = resolver["pseudonym"] if resolver else rd["resolved_by"]
            ticket["resolved_at"] = rd.get("resolved_at")
        tickets.append(ticket)

    return json.dumps({
        "status": "ok",
        "team_id": params.team_id,
        "summary": summary,
        "total_shown": len(tickets),
        "filters_applied": {
            k: v for k, v in {"status": params.status, "area": params.area, "type": params.type}.items() if v
        },
        "tickets": tickets,
        "tip": "Use research_match_needs_resolve to close a ticket, or research_match_needs_create to add one.",
    }, indent=2)


@mcp.tool(
    name="research_match_needs_resolve",
    description=(
        "POST-TEAM STEP — Resolve (close) a team ticket. "
        "Set resolution to 'resolved' (work done) or 'wont_fix' (not needed / out of scope). "
        "Any team member can resolve any ticket — this builds team trust. "
        "REPUTATION IMPACT: Resolving a 'need_help' or 'question' ticket created by another "
        "team member gives you a +0.5 effort boost in the reputation system. "
        "Add a resolution_note to explain what was done or why it won't be fixed. "
        "Resolved tickets remain visible in research_match_needs_list for team history."
    ),
    annotations={
        "title": "Resolve Team Ticket",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_needs_resolve(params: NeedsResolveInput, ctx: Context = None) -> str:
    """Resolve a team ticket.

    Args:
        params (NeedsResolveInput): Resolution data:
            - ticket_id (str, required): Ticket ID
            - resolution (str, required): 'resolved' or 'wont_fix'
            - resolution_note (str, optional): Explanation (max 1000 chars)

    Returns:
        str: JSON with resolution status and reputation impact if applicable
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    if datastore:
        ticket = await datastore.get_ticket_by_id(params.ticket_id)
    else:
        ticket = db.execute("SELECT * FROM team_tickets WHERE id = ?", (params.ticket_id,)).fetchone()
    if not ticket:
        return json.dumps({"error": "Ticket not found."})
    ticket = dict(ticket)

    # Verify user is a member of the ticket's team
    if datastore:
        membership = await datastore.get_team_member(ticket["team_id"], user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (ticket["team_id"], user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    if ticket["status"] in ("resolved", "wont_fix"):
        return json.dumps({"error": f"Ticket already {ticket['status']}. Cannot resolve again."})

    now_iso = datetime.now(timezone.utc).isoformat()

    # Update ticket
    if datastore:
        await datastore.update_ticket_status(
            ticket["team_id"], params.ticket_id,
            status=params.resolution, resolved_by=user["id"], resolved_at=now_iso)
    else:
        db.execute(
            """UPDATE team_tickets
               SET status = ?, resolved_by = ?, resolved_at = datetime('now'), updated_at = datetime('now')
               WHERE id = ?""",
            (params.resolution, user["id"], params.ticket_id)
        )

    # Audit log
    await _write_audit_log(datastore or db, ticket["team_id"], user["id"], "ticket_resolved",
                     resource_ref=params.ticket_id,
                     details={"resolution": params.resolution,
                              "note": params.resolution_note,
                              "original_type": ticket["type"],
                              "original_author": ticket["author_id"]})

    # Reputation boost: resolving someone else's need_help/question
    effort_boosted = False
    if (params.resolution == "resolved"
            and ticket["type"] in ("need_help", "question")
            and ticket["author_id"] != user["id"]):
        if datastore:
            current_user = await datastore.get_user_by_id(user["id"])
            if current_user and current_user.get("running_effort") is not None:
                new_effort = min(5.0, current_user["running_effort"] + TICKET_EFFORT_BONUS * REPUTATION_ALPHA)
                await datastore.update_user_running_effort(user["id"], new_effort)
        else:
            current = db.execute(
                "SELECT running_effort FROM users WHERE id = ?", (user["id"],)
            ).fetchone()
            if current and current["running_effort"] is not None:
                new_effort = min(5.0, current["running_effort"] + TICKET_EFFORT_BONUS * REPUTATION_ALPHA)
                db.execute("UPDATE users SET running_effort = ? WHERE id = ?", (new_effort, user["id"]))
        effort_boosted = True

    # NEED-03: Recalculate license after ticket resolution (only if bilateral reveals exist)
    license_update = None
    if params.resolution == "resolved":
        lic = await _compute_license(db, ticket["team_id"], datastore=datastore)
        if datastore:
            team_data = await datastore.get_team_by_id(ticket["team_id"])
            current_type = team_data["license_type"] if team_data else "joint-equal"
        else:
            current_type = db.execute("SELECT license_type FROM teams WHERE id = ?",
                                      (ticket["team_id"],)).fetchone()["license_type"]
        if lic["license_type"] != current_type:
            if datastore:
                await datastore.update_team_license(ticket["team_id"], lic["license_type"], now_iso)
                members_list = await datastore.get_team_member_pseudonyms(ticket["team_id"])
                for m_row in members_list:
                    m_row = dict(m_row)
                    pct = lic["contribution_split"].get(m_row["pseudonym"], 0)
                    await datastore.update_member_contribution(ticket["team_id"], m_row["user_id"], pct)
            else:
                db.execute("UPDATE teams SET license_type = ?, license_updated_at = datetime('now') WHERE id = ?",
                           (lic["license_type"], ticket["team_id"]))
                for m_row in db.execute(
                    "SELECT tm.user_id, u.pseudonym FROM team_members tm JOIN users u ON tm.user_id = u.id WHERE tm.team_id = ?",
                    (ticket["team_id"],)
                ).fetchall():
                    pct = lic["contribution_split"].get(m_row["pseudonym"], 0)
                    db.execute("UPDATE team_members SET contribution_percentage = ? WHERE team_id = ? AND user_id = ?",
                               (pct, ticket["team_id"], m_row["user_id"]))
            await _write_audit_log(datastore or db, ticket["team_id"], user["id"], "license_generated",
                             resource_ref=ticket["team_id"],
                             details={"old_type": current_type, "new_type": lic["license_type"],
                                      "trigger": "ticket_resolved"})
        license_update = {"license_type": lic["license_type"], "changed": lic["license_type"] != current_type}

    if db:
        db.commit()

    result = {
        "status": "ok",
        "ticket_id": params.ticket_id,
        "resolution": params.resolution,
        "resolved_by": user["pseudonym"],
    }
    if params.resolution_note:
        result["resolution_note"] = params.resolution_note
    if effort_boosted:
        result["reputation_impact"] = f"+{TICKET_EFFORT_BONUS} effort boost for resolving a {ticket['type']} ticket"
    if license_update:
        result["license_update"] = license_update
    result["next_step"] = "Use research_match_needs_list to see updated ticket board, or research_match_rate_user to rate your collaborator."

    return json.dumps(result, indent=2)


# =============================================================================
# REVEAL TOOLS (Level 3 — Bilateral Consent)
# =============================================================================


@mcp.tool(
    name="research_match_reveal_request",
    description=(
        "POST-TEAM STEP — Request Level 3 reveal of a teammate's full Research Commit. "
        "After forming a team (respond_request), members only see scores and semaphore (Level 2). "
        "Use this tool to request explicit consent to view the complete commit content "
        "(hypothesis, theory, demonstrations, ad-hoc ideas, cherry-picking declarations). "
        "The target user must approve via research_match_reveal_respond before content is visible. "
        "Each consent is tied to a specific commit version — new versions require new consent. "
        "Use research_match_reveal_status to check current reveal state."
    ),
    annotations={
        "title": "Request Level 3 Reveal",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_reveal_request(params: RevealRequestInput, ctx: Context = None) -> str:
    """Request Level 3 reveal of a teammate's Research Commit.

    Args:
        params (RevealRequestInput): Request data:
            - team_id (str, required): Team where both users are members
            - target_user_id (str, required): User whose commit you want revealed

    Returns:
        str: JSON with consent_id and status, or error
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify requester is team member
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Cannot request own reveal
    if params.target_user_id == user["id"]:
        return json.dumps({"error": "Cannot request reveal of your own commit. You already have access to your own work."})

    # Verify target is team member
    if datastore:
        target_membership = await datastore.get_team_member(params.team_id, params.target_user_id)
    else:
        target_membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, params.target_user_id)
        ).fetchone()
    if not target_membership:
        return json.dumps({"error": "Target user is not a member of this team."})

    # Verify target has at least one commit
    if datastore:
        target_commit = await datastore.get_latest_commit_by_user(params.target_user_id)
    else:
        target_commit = db.execute(
            "SELECT id FROM research_commits WHERE user_id = ? ORDER BY version DESC LIMIT 1",
            (params.target_user_id,)
        ).fetchone()
    if not target_commit:
        return json.dumps({"error": "Target user has no Research Commits yet. They must use research_match_submit_commit first."})
    commit_id = target_commit["id"]

    # Check for existing pending consent
    if datastore:
        existing_pending = await datastore.find_reveal_consent(
            params.team_id, user["id"], commit_id, status="pending")
    else:
        existing_pending = db.execute(
            """SELECT id FROM reveal_consents
               WHERE team_id = ? AND level = 3 AND requester_id = ? AND resource_ref = ? AND status = 'pending'""",
            (params.team_id, user["id"], commit_id)
        ).fetchone()
    if existing_pending:
        return json.dumps({
            "status": "already_pending",
            "consent_id": existing_pending["id"],
            "message": "A reveal request for this commit is already pending. Wait for the target user to respond via research_match_reveal_respond.",
        })

    # Check for already approved
    if datastore:
        existing_approved = await datastore.find_reveal_consent(
            params.team_id, user["id"], commit_id, status="approved")
    else:
        existing_approved = db.execute(
            """SELECT id FROM reveal_consents
               WHERE team_id = ? AND level = 3 AND requester_id = ? AND resource_ref = ? AND status = 'approved'""",
            (params.team_id, user["id"], commit_id)
        ).fetchone()
    if existing_approved:
        return json.dumps({
            "status": "already_approved",
            "consent_id": existing_approved["id"],
            "message": "This commit is already revealed to you. Use research_match_reveal_status to view the content.",
        })

    # Check pending limit
    if datastore:
        pending_count = await datastore.count_pending_reveals(params.team_id)
    else:
        pending_count = db.execute(
            "SELECT COUNT(*) as c FROM reveal_consents WHERE team_id = ? AND status = 'pending'",
            (params.team_id,)
        ).fetchone()["c"]
    if pending_count >= MAX_PENDING_REVEALS_PER_TEAM:
        return json.dumps({"error": f"Too many pending reveal requests for this team (max {MAX_PENDING_REVEALS_PER_TEAM}). Resolve existing requests first."})

    # Create consent
    consent_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if datastore:
        await datastore.insert_reveal_consent({
            "id": consent_id, "team_id": params.team_id, "level": 3,
            "requester_id": user["id"], "approver_id": params.target_user_id,
            "resource_type": "commit", "resource_ref": commit_id,
            "status": "pending", "created_at": now_iso,
        })
    else:
        db.execute(
            """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id, resource_type, resource_ref)
               VALUES (?, ?, 3, ?, ?, 'commit', ?)""",
            (consent_id, params.team_id, user["id"], params.target_user_id, commit_id)
        )

    await _write_audit_log(datastore or db, params.team_id, user["id"], "reveal_requested",
                     resource_ref=commit_id,
                     details={"level": 3, "target_user_id": params.target_user_id})
    if db:
        db.commit()

    # Get target pseudonym for the response
    if datastore:
        target_user = await datastore.get_user_by_id(params.target_user_id)
    else:
        target_user = db.execute("SELECT pseudonym FROM users WHERE id = ?", (params.target_user_id,)).fetchone()

    return json.dumps({
        "status": "pending",
        "consent_id": consent_id,
        "target_pseudonym": target_user["pseudonym"] if target_user else params.target_user_id,
        "commit_id": commit_id,
        "message": "Reveal request sent. The target user must approve via research_match_reveal_respond.",
        "next_steps": [
            "research_match_reveal_status to check current reveal state",
            "research_match_reveal_respond (for the target user) to approve or deny",
        ],
    }, indent=2)


@mcp.tool(
    name="research_match_reveal_respond",
    description=(
        "POST-TEAM STEP — Approve or deny a Level 3 reveal request for your Research Commit. "
        "When a teammate requests to see your full commit, you will have a pending consent. "
        "Use research_match_reveal_status to see pending requests, then this tool to respond. "
        "IMPORTANT: Approval is IRREVERSIBLE — once approved, the requester can see your full "
        "commit content (hypothesis, theory, demos, ad-hoc, cherry-picking, scores, breakdowns). "
        "Denial is final for that request but the requester can submit a new request later."
    ),
    annotations={
        "title": "Respond to Reveal Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_reveal_respond(params: RevealRespondInput, ctx: Context = None) -> str:
    """Approve or deny a Level 3 reveal consent request.

    Args:
        params (RevealRespondInput): Response data:
            - consent_id (str, required): Consent ID to respond to
            - approve (bool, required): True to approve, False to deny

    Returns:
        str: JSON with result and guidance
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    if datastore:
        consent = await datastore.get_reveal_consent_by_id(params.consent_id)
    else:
        consent = db.execute("SELECT * FROM reveal_consents WHERE id = ?", (params.consent_id,)).fetchone()
    if not consent:
        return json.dumps({"error": "Consent not found."})
    consent = dict(consent)

    # Only the approver can respond
    if consent["approver_id"] != user["id"]:
        return json.dumps({"error": "Only the target user (approver) can respond to this reveal request."})

    # Must be pending
    if consent["status"] != "pending":
        return json.dumps({
            "error": f"Consent already {consent['status']}. Cannot change a resolved consent.",
            "consent_id": params.consent_id,
            "current_status": consent["status"],
        })

    new_status = "approved" if params.approve else "denied"
    now_iso = datetime.now(timezone.utc).isoformat()
    if datastore:
        await datastore.update_reveal_consent_status(
            params.consent_id, new_status,
            team_id=consent["team_id"], resolved_at=now_iso)
    else:
        db.execute(
            "UPDATE reveal_consents SET status = ?, resolved_at = datetime('now') WHERE id = ?",
            (new_status, params.consent_id)
        )

    action = "reveal_approved" if params.approve else "reveal_denied"
    await _write_audit_log(datastore or db, consent["team_id"], user["id"], action,
                     resource_ref=consent["resource_ref"],
                     details={"consent_id": params.consent_id, "level": consent["level"],
                              "requester_id": consent["requester_id"]})

    # NEED-03: Recalculate license after reveal approval
    license_update = None
    if params.approve:
        lic = await _compute_license(db, consent["team_id"], datastore=datastore)
        if datastore:
            team_data = await datastore.get_team_by_id(consent["team_id"])
            current_type = team_data["license_type"] if team_data else "joint-equal"
        else:
            current_type = db.execute("SELECT license_type FROM teams WHERE id = ?",
                                      (consent["team_id"],)).fetchone()["license_type"]
        if lic["license_type"] != current_type:
            if datastore:
                await datastore.update_team_license(consent["team_id"], lic["license_type"], now_iso)
                members_list = await datastore.get_team_member_pseudonyms(consent["team_id"])
                for m_row in members_list:
                    m_row = dict(m_row)
                    pct = lic["contribution_split"].get(m_row["pseudonym"], 0)
                    await datastore.update_member_contribution(consent["team_id"], m_row["user_id"], pct)
            else:
                db.execute("UPDATE teams SET license_type = ?, license_updated_at = datetime('now') WHERE id = ?",
                           (lic["license_type"], consent["team_id"]))
                for m_row in db.execute(
                    "SELECT tm.user_id, u.pseudonym FROM team_members tm JOIN users u ON tm.user_id = u.id WHERE tm.team_id = ?",
                    (consent["team_id"],)
                ).fetchall():
                    pct = lic["contribution_split"].get(m_row["pseudonym"], 0)
                    db.execute("UPDATE team_members SET contribution_percentage = ? WHERE team_id = ? AND user_id = ?",
                               (pct, consent["team_id"], m_row["user_id"]))
            await _write_audit_log(datastore or db, consent["team_id"], user["id"], "license_generated",
                             resource_ref=consent["team_id"],
                             details={"old_type": current_type, "new_type": lic["license_type"],
                                      "trigger": "reveal_approved"})
        license_update = {"license_type": lic["license_type"], "changed": lic["license_type"] != current_type}

    if db:
        db.commit()

    if datastore:
        requester = await datastore.get_user_by_id(consent["requester_id"])
    else:
        requester = db.execute("SELECT pseudonym FROM users WHERE id = ?", (consent["requester_id"],)).fetchone()

    result = {
        "status": "ok",
        "consent_id": params.consent_id,
        "decision": new_status,
        "requester_pseudonym": requester["pseudonym"] if requester else consent["requester_id"],
    }

    if license_update:
        result["license_update"] = license_update

    if params.approve:
        result["message"] = (
            "Reveal APPROVED. This is irreversible — the requester can now view your full "
            "Research Commit via research_match_reveal_status."
        )
    else:
        result["message"] = (
            "Reveal DENIED. The requester cannot see your commit content. "
            "They may submit a new request later if desired."
        )

    result["next_step"] = "Use research_match_reveal_status to see the full reveal matrix for your team."
    return json.dumps(result, indent=2)


@mcp.tool(
    name="research_match_reveal_status",
    description=(
        "POST-TEAM STEP — View reveal status, consent matrix, and revealed content for a team. "
        "Shows all reveal consents (pending, approved, denied) with pseudonyms. "
        "For approved consents where YOU are the requester, includes the FULL Research Commit "
        "content (hypothesis, theory, demonstrations, ad-hoc ideas, cherry-picking, scores). "
        "Also shows a reveal_matrix summarizing who can see whose commits. "
        "Use this to check pending requests before using research_match_reveal_respond."
    ),
    annotations={
        "title": "Reveal Status & Content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_reveal_status(params: RevealStatusInput, ctx: Context = None) -> str:
    """View reveal consents, matrix, and revealed content for a team.

    Args:
        params (RevealStatusInput): Query data:
            - team_id (str, required): Team to check

    Returns:
        str: JSON with consents, reveal_matrix, and revealed content where applicable
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    if datastore:
        consents_rows = await datastore.get_reveal_consents_with_pseudonyms(params.team_id)
    else:
        consents_rows = db.execute(
            """SELECT rc.*, u_req.pseudonym AS requester_pseudonym, u_app.pseudonym AS approver_pseudonym
               FROM reveal_consents rc
               JOIN users u_req ON rc.requester_id = u_req.id
               JOIN users u_app ON rc.approver_id = u_app.id
               WHERE rc.team_id = ?
               ORDER BY rc.created_at DESC""",
            (params.team_id,)
        ).fetchall()

    consents = []
    summary = {"pending": 0, "approved": 0, "denied": 0}

    for row in consents_rows:
        r = dict(row)
        summary[r["status"]] = summary.get(r["status"], 0) + 1

        consent_info = {
            "consent_id": r["id"],
            "level": r["level"],
            "requester_pseudonym": r.get("requester_pseudonym", ""),
            "approver_pseudonym": r.get("approver_pseudonym", ""),
            "resource_type": r.get("resource_type", ""),
            "status": r["status"],
            "created_at": r.get("created_at", ""),
            "resolved_at": r.get("resolved_at"),
        }

        # If approved and current user is the requester, include full commit content
        if r["status"] == "approved" and r["requester_id"] == user["id"] and r.get("resource_ref"):
            if datastore:
                commit = await datastore.get_commit_by_id(r["resource_ref"])
            else:
                commit = db.execute(
                    "SELECT * FROM research_commits WHERE id = ?", (r["resource_ref"],)
                ).fetchone()
            if commit:
                c = dict(commit)
                consent_info["revealed_content"] = {
                    "commit_id": c["id"],
                    "version": c["version"],
                    "domain": c["domain"],
                    "subdomain": c.get("subdomain"),
                    "problem": c["problem"],
                    "hypothesis": c.get("hypothesis"),
                    "theoretical_framework": c.get("theoretical_framework"),
                    "demonstrations_summary": c.get("demonstrations_summary"),
                    "demo_types": json.loads(c.get("demo_types") or "[]"),
                    "code_languages": json.loads(c.get("code_languages") or "[]"),
                    "adhoc_summary": c.get("adhoc_summary"),
                    "adhoc_connections": json.loads(c.get("adhoc_connections") or "[]"),
                    "cherry_picking": json.loads(c.get("cherry_picking") or "[]"),
                    "solidity_levels": json.loads(c.get("solidity_levels") or "{}"),
                    "overall_solidity": c.get("overall_solidity"),
                    "ot_score": c.get("ot_score"),
                    "ofc_score": c.get("ofc_score"),
                    "ot_breakdown": json.loads(c.get("ot_breakdown") or "{}"),
                    "ofc_breakdown": json.loads(c.get("ofc_breakdown") or "{}"),
                    "solidity_impact": json.loads(c.get("solidity_impact") or "{}"),
                }

        consents.append(consent_info)

    # Build reveal matrix
    if datastore:
        members = await datastore.get_team_member_pseudonyms(params.team_id)
    else:
        members = db.execute(
            """SELECT tm.user_id, u.pseudonym
               FROM team_members tm JOIN users u ON tm.user_id = u.id
               WHERE tm.team_id = ?""",
            (params.team_id,)
        ).fetchall()

    reveal_matrix = []
    for member in members:
        m = dict(member)
        if datastore:
            visible_to = await datastore.get_approved_reveal_targets(params.team_id, m["user_id"], direction="approver")
            can_see = await datastore.get_approved_reveal_targets(params.team_id, m["user_id"], direction="requester")
        else:
            visible_to = db.execute(
                """SELECT u.pseudonym FROM reveal_consents rc
                   JOIN users u ON rc.requester_id = u.id
                   WHERE rc.team_id = ? AND rc.approver_id = ? AND rc.status = 'approved' AND rc.level = 3""",
                (params.team_id, m["user_id"])
            ).fetchall()
            can_see = db.execute(
                """SELECT u.pseudonym FROM reveal_consents rc
                   JOIN users u ON rc.approver_id = u.id
                   WHERE rc.team_id = ? AND rc.requester_id = ? AND rc.status = 'approved' AND rc.level = 3""",
                (params.team_id, m["user_id"])
            ).fetchall()

        reveal_matrix.append({
            "pseudonym": m["pseudonym"],
            "commit_visible_to": [dict(r)["pseudonym"] if not isinstance(r, str) else r for r in visible_to],
            "can_see_commits_of": [dict(r)["pseudonym"] if not isinstance(r, str) else r for r in can_see],
        })

    # Count shared files for Level 4 context
    if datastore:
        shared_files_count = await datastore.count_shared_files(params.team_id)
    else:
        shared_files_count = db.execute(
            "SELECT COUNT(*) as c FROM shared_files WHERE team_id = ?",
            (params.team_id,)
        ).fetchone()["c"]

    result = {
        "team_id": params.team_id,
        "summary": summary,
        "reveal_matrix": reveal_matrix,
        "shared_files_count": shared_files_count,
        "consents": consents,
    }

    if summary["pending"] > 0:
        result["tip"] = "Use research_match_reveal_respond to approve or deny pending requests."
    elif summary["approved"] == 0:
        result["tip"] = "No reveals yet. Use research_match_reveal_request to request access to a teammate's commit."
    else:
        result["tip"] = "Use research_match_rate_user to rate your collaborator after reviewing their work."

    return json.dumps(result, indent=2)


# =============================================================================
# LICENSE TOOL (NEED-03 — Automatic Licensing)
# =============================================================================

@mcp.tool(
    name="research_match_team_license",
    description=(
        "POST-TEAM STEP — View the automatically computed license for your team. "
        "The license type is determined by collaboration activity: reveals (who shared what), "
        "ticket resolution balance (who contributed more), and team age. "
        "Types: joint-equal (50/50 co-authorship), joint-weighted (proportional to contributions), "
        "advisory-only (one-sided consultation), time-limited (stale collaboration). "
        "The license recalculates automatically — call anytime to see current terms. "
        "Use after research_match_reveal_status to understand IP implications."
    ),
    annotations={
        "title": "Team License",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_team_license(params: TeamLicenseInput, ctx: Context = None) -> str:
    """View and recalculate the automatic license for a team.

    Args:
        params (TeamLicenseInput): Query data:
            - team_id (str, required): Team to view license for

    Returns:
        str: JSON with license type, contribution split, rationale, terms, and history
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Compute current license
    license_info = await _compute_license(db, params.team_id, datastore=datastore)

    # Check if license changed from stored value
    if datastore:
        team = await datastore.get_team_by_id(params.team_id)
    else:
        team = db.execute("SELECT license_type, license_updated_at FROM teams WHERE id = ?",
                          (params.team_id,)).fetchone()
    if not team:
        return json.dumps({"error": "Team not found."})

    current_type = team["license_type"]
    changed = license_info["license_type"] != current_type
    now_iso = datetime.now(timezone.utc).isoformat()

    if changed:
        if datastore:
            await datastore.update_team_license(params.team_id, license_info["license_type"], now_iso)
            members_list = await datastore.get_team_member_pseudonyms(params.team_id)
            for member_row in members_list:
                member_row = dict(member_row)
                pseudo = member_row["pseudonym"]
                pct = license_info["contribution_split"].get(pseudo, 0)
                await datastore.update_member_contribution(params.team_id, member_row["user_id"], pct)
        else:
            db.execute(
                "UPDATE teams SET license_type = ?, license_updated_at = datetime('now') WHERE id = ?",
                (license_info["license_type"], params.team_id)
            )
            for member_row in db.execute(
                "SELECT tm.user_id, u.pseudonym FROM team_members tm JOIN users u ON tm.user_id = u.id WHERE tm.team_id = ?",
                (params.team_id,)
            ).fetchall():
                pseudo = member_row["pseudonym"]
                pct = license_info["contribution_split"].get(pseudo, 0)
                db.execute(
                    "UPDATE team_members SET contribution_percentage = ? WHERE team_id = ? AND user_id = ?",
                    (pct, params.team_id, member_row["user_id"])
                )
        await _write_audit_log(datastore or db, params.team_id, user["id"], "license_generated",
                         resource_ref=params.team_id,
                         details={"old_type": current_type,
                                  "new_type": license_info["license_type"],
                                  "trigger": "team_license_tool"})
        if db:
            db.commit()

    # Fetch license change history
    if datastore:
        history = await datastore.get_audit_entries(params.team_id, action="license_generated", limit=10)
    else:
        history = db.execute(
            """SELECT details, created_at FROM audit_log
               WHERE team_id = ? AND action = 'license_generated'
               ORDER BY created_at DESC LIMIT 10""",
            (params.team_id,)
        ).fetchall()
    change_history = []
    for h in history:
        hd = dict(h)
        details = json.loads(hd["details"]) if isinstance(hd.get("details"), str) else (hd.get("details") or {})
        change_history.append({
            "timestamp": hd["created_at"],
            "old_type": details.get("old_type"),
            "new_type": details.get("new_type"),
            "trigger": details.get("trigger"),
        })

    result = {
        "status": "ok",
        "team_id": params.team_id,
        "license_type": license_info["license_type"],
        "contribution_split": license_info["contribution_split"],
        "rationale": license_info["rationale"],
        "terms": license_info["terms"],
        "reveal_state": license_info["reveal_state"],
        "ticket_balance": license_info["ticket_balance"],
        "changed_on_this_call": changed,
    }
    if changed:
        result["previous_type"] = current_type
    if change_history:
        result["change_history"] = change_history

    # Contract info
    if datastore:
        contracts_count = await datastore.count_confirmed_contracts_for_team(params.team_id)
    else:
        contracts_count = db.execute(
            "SELECT COUNT(*) as c FROM collaboration_contracts WHERE team_id = ? AND status = 'confirmed'",
            (params.team_id,)
        ).fetchone()["c"]
    result["contracts_count"] = contracts_count
    result["contract_tip"] = (
        "Use research_match_export_contract to generate a git-verifiable contract "
        "that both parties commit to their repos for independent verification."
    )

    result["next_step"] = (
        "License recalculates automatically as collaboration evolves. "
        "Use research_match_reveal_request to share more content, or "
        "research_match_needs_create to create tickets."
    )
    return json.dumps(result, indent=2)


# =============================================================================
# FILE SHARING TOOLS (NEED-04 — Level 4 Metadata Registry)
# =============================================================================

@mcp.tool(
    name="research_match_share_file",
    description=(
        "POST-REVEAL STEP — Register a file for sharing with your team. "
        "REQUIRES bilateral Level 3 reveals (both members must have approved reveals in BOTH directions). "
        "This is a metadata registry: you provide file path, optional SHA-256 hash, and description. "
        "Actual file content is exchanged out-of-band (email, repo, etc.). "
        "Idempotent: sharing the same file_path twice returns the existing record. "
        "Limit: 50 files per team. Use after research_match_reveal_status shows bilateral reveals."
    ),
    annotations={
        "title": "Share File",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_share_file(params: ShareFileInput, ctx: Context = None) -> str:
    """Register a file metadata record for sharing with a team.

    Args:
        params (ShareFileInput): File data:
            - team_id (str, required): Team to share with
            - file_path (str, required): Path or name of the file
            - file_hash (Optional[str]): SHA-256 hash for integrity
            - description (Optional[str]): Brief description

    Returns:
        str: JSON with status, file_id, and next steps
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Bilateral Level 3 gate: both members must have approved reveals in EACH direction
    if datastore:
        member_ids = await datastore.get_team_member_ids(params.team_id)
    else:
        members_raw = db.execute(
            "SELECT user_id FROM team_members WHERE team_id = ?",
            (params.team_id,)
        ).fetchall()
        member_ids = [m["user_id"] for m in members_raw]

    for m_id in member_ids:
        other_ids = [o for o in member_ids if o != m_id]
        for other_id in other_ids:
            if datastore:
                consent = await datastore.find_reveal_consent(
                    params.team_id, other_id, resource_ref=None,
                    status="approved", approver_id=m_id)
            else:
                consent = db.execute(
                    """SELECT id FROM reveal_consents
                       WHERE team_id = ? AND level = 3 AND requester_id = ? AND approver_id = ?
                       AND status = 'approved'""",
                    (params.team_id, other_id, m_id)
                ).fetchone()
            if not consent:
                return json.dumps({
                    "error": "Bilateral Level 3 reveals required. Both members must have approved reveals in both directions.",
                    "tip": "Use research_match_reveal_request and research_match_reveal_respond first."
                })

    # Re-sharing detection (MAD mechanism)
    if params.file_hash:
        violation = await _check_resharing_violation(datastore or db, user["id"], params.file_hash)
        if violation:
            # Penalty: tank honesty score
            if datastore:
                await datastore.update_user_honesty_penalty(user["id"], RESHARING_PENALTY_HONESTY)
            else:
                db.execute(
                    "UPDATE users SET running_honesty = ?, avg_honesty = ? WHERE id = ?",
                    (RESHARING_PENALTY_HONESTY, RESHARING_PENALTY_HONESTY, user["id"])
                )
            await _write_audit_log(datastore or db, params.team_id, user["id"], "violation_detected",
                             resource_ref=violation["original_file_id"],
                             details={
                                 "type": "resharing",
                                 "file_hash": params.file_hash,
                                 "original_team_id": violation["original_team_id"],
                                 "origin_user_id": violation["origin_user_id"],
                                 "attempted_file_path": params.file_path,
                             })
            if db:
                db.commit()
            return json.dumps({
                "error": "RE-SHARING VIOLATION DETECTED.",
                "violation": {
                    "type": "resharing",
                    "message": "This file (by hash) was originally shared by another user. Re-sharing others' content is prohibited.",
                    "penalty": "Your honesty score has been set to minimum. This affects your reputation permanently.",
                    "original_owner_notified": True,
                },
                "tip": "Only share files YOU created. Use research_match_audit_log to review the violation record."
            })

    # Check file limit
    if datastore:
        file_count = await datastore.count_shared_files(params.team_id)
    else:
        file_count = db.execute(
            "SELECT COUNT(*) as c FROM shared_files WHERE team_id = ?",
            (params.team_id,)
        ).fetchone()["c"]
    if file_count >= MAX_SHARED_FILES_PER_TEAM:
        return json.dumps({
            "error": f"File limit reached ({MAX_SHARED_FILES_PER_TEAM} files per team).",
            "tip": "Remove old files or use a shared repository for large collections."
        })

    # Dedup: check (team_id, shared_by, file_path)
    if datastore:
        existing = await datastore.find_shared_file(params.team_id, user["id"], params.file_path)
    else:
        existing = db.execute(
            "SELECT id FROM shared_files WHERE team_id = ? AND shared_by = ? AND file_path = ?",
            (params.team_id, user["id"], params.file_path)
        ).fetchone()
    if existing:
        return json.dumps({
            "status": "already_shared",
            "file_id": existing["id"],
            "file_path": params.file_path,
            "team_id": params.team_id,
            "message": "This file was already shared. Use research_match_shared_files to see all files."
        })

    # Insert new file record
    file_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    if datastore:
        await datastore.insert_shared_file({
            "id": file_id, "team_id": params.team_id,
            "shared_by": user["id"], "file_path": params.file_path,
            "file_hash": params.file_hash, "description": params.description,
            "origin_user_id": user["id"], "shared_at": now_iso,
        })
    else:
        db.execute(
            """INSERT INTO shared_files (id, team_id, shared_by, file_path, file_hash, description, origin_user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_id, params.team_id, user["id"], params.file_path,
             params.file_hash, params.description, user["id"])
        )

    await _write_audit_log(datastore or db, params.team_id, user["id"], "file_shared",
                     resource_ref=file_id,
                     details={"file_path": params.file_path,
                              "file_hash": params.file_hash,
                              "description": params.description})
    if db:
        db.commit()

    return json.dumps({
        "status": "ok",
        "file_id": file_id,
        "file_path": params.file_path,
        "team_id": params.team_id,
        "message": "File registered successfully. Share the actual content out-of-band (email, repo, etc.).",
        "next_steps": [
            "Share the file content directly with your teammate (email, shared drive, git repo).",
            "Use research_match_shared_files to see all shared files in the team.",
            "Use research_match_needs_create if you need help with the shared content."
        ]
    }, indent=2)


@mcp.tool(
    name="research_match_shared_files",
    description=(
        "POST-REVEAL STEP — List all shared file records in a team. "
        "Shows file path, hash, description, who shared it, and when. "
        "Includes is_yours flag and by_member summary for quick overview. "
        "Use after research_match_share_file to see the complete file registry."
    ),
    annotations={
        "title": "Shared Files",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_shared_files(params: SharedFilesInput, ctx: Context = None) -> str:
    """List all shared file records for a team.

    Args:
        params (SharedFilesInput): Query data:
            - team_id (str, required): Team to list files for

    Returns:
        str: JSON with files list, by_member summary, and tips
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Fetch shared files with pseudonyms
    if datastore:
        rows = await datastore.get_shared_files_with_pseudonyms(params.team_id)
    else:
        rows = db.execute(
            """SELECT sf.*, u.pseudonym AS shared_by_pseudonym
               FROM shared_files sf
               JOIN users u ON sf.shared_by = u.id
               WHERE sf.team_id = ?
               ORDER BY sf.shared_at DESC""",
            (params.team_id,)
        ).fetchall()

    files = []
    by_member = {}
    for row in rows:
        r = dict(row)
        pseudo = r.get("shared_by_pseudonym", r.get("pseudonym", ""))
        by_member[pseudo] = by_member.get(pseudo, 0) + 1
        files.append({
            "file_id": r["id"],
            "file_path": r["file_path"],
            "file_hash": r.get("file_hash"),
            "description": r.get("description"),
            "shared_by": pseudo,
            "is_yours": r["shared_by"] == user["id"],
            "shared_at": r.get("shared_at"),
        })

    # Audit log for file access (only if there are files)
    if files:
        await _write_audit_log(datastore or db, params.team_id, user["id"], "file_accessed",
                         resource_ref=params.team_id,
                         details={"file_count": len(files)})
        if db:
            db.commit()

    result = {
        "team_id": params.team_id,
        "total_files": len(files),
        "by_member": by_member,
        "files": files,
    }

    if not files:
        result["tip"] = "No files shared yet. Use research_match_share_file to register a file."
    else:
        result["tip"] = "Files are metadata records. Exchange actual content out-of-band (email, repo, etc.)."

    return json.dumps(result, indent=2)


@mcp.tool(
    name="research_match_audit_log",
    description=(
        "POST-TEAM STEP — View the immutable audit trail for your team. "
        "Shows all logged actions: reveals (requested/approved/denied), file sharing, "
        "ticket lifecycle, license changes, and violation detections. "
        "Filter by action type to focus on specific events. "
        "The audit trail is append-only — entries cannot be modified or deleted. "
        "Use this to review team activity, verify compliance, or investigate violations."
    ),
    annotations={
        "title": "Audit Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_audit_log(params: AuditLogInput, ctx: Context = None) -> str:
    """View the audit trail for a team.

    Args:
        params (AuditLogInput): Query data:
            - team_id (str, required): Team to view audit log for
            - action_filter (Optional[str]): Filter by action type
            - limit (int, default=50): Max entries to return

    Returns:
        str: JSON with audit entries and filtering guidance
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Build query
    if datastore:
        rows = await datastore.get_audit_entries(
            params.team_id, action=params.action_filter, limit=params.limit)
    else:
        if params.action_filter:
            rows = db.execute(
                """SELECT al.*, u.pseudonym AS actor_pseudonym
                   FROM audit_log al
                   JOIN users u ON al.actor_id = u.id
                   WHERE al.team_id = ? AND al.action = ?
                   ORDER BY al.created_at DESC
                   LIMIT ?""",
                (params.team_id, params.action_filter, params.limit)
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT al.*, u.pseudonym AS actor_pseudonym
                   FROM audit_log al
                   JOIN users u ON al.actor_id = u.id
                   WHERE al.team_id = ?
                   ORDER BY al.created_at DESC
                   LIMIT ?""",
                (params.team_id, params.limit)
            ).fetchall()

    entries = []
    for row in rows:
        r = dict(row)
        details = None
        if r["details"]:
            try:
                details = json.loads(r["details"])
            except (json.JSONDecodeError, TypeError):
                details = r["details"]
        entries.append({
            "id": r["id"],
            "action": r["action"],
            "actor_pseudonym": r["actor_pseudonym"],
            "resource_ref": r["resource_ref"],
            "details": details,
            "created_at": r["created_at"],
        })

    available_actions = [
        "reveal_requested", "reveal_approved", "reveal_denied",
        "file_shared", "file_accessed",
        "ticket_created", "ticket_updated", "ticket_resolved",
        "license_generated", "violation_detected",
    ]

    result = {
        "team_id": params.team_id,
        "total_entries": len(entries),
        "entries": entries,
        "available_actions": available_actions,
        "tip": "Use action_filter='violation_detected' to check for re-sharing violations.",
    }

    return json.dumps(result, indent=2)


# =============================================================================
# PROFORMA TOOL (v2.7)
# =============================================================================

@mcp.tool(
    name="research_match_prepare_commit",
    description=(
        "STEP 1.5 — Universal proforma generator for Research Commits. "
        "Analyzes ANY project (code repo, paper, dataset, theoretical framework) and produces "
        "a standardized proforma with machine-extracted data + LLM prompt template. "
        "Three modes: 'extract' — analyze project, return proforma + prompt for AI to fill. "
        "'validate' — check filled narrative for completeness and quality. "
        "'submit' — validate and auto-submit to research_match_submit_commit. "
        "Accepts local path (project_path) or GitHub URL (repo_url). "
        "Example: mode='extract', project_path='/path/to/repo'."
    ),
    annotations={
        "title": "Prepare Research Commit (Proforma)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
@_log_tool_call
async def research_match_prepare_commit(params: PrepareCommitInput, ctx: Context = None) -> str:
    """Universal proforma generator for structured Research Commits.

    Args:
        params (PrepareCommitInput): Proforma parameters:
            - project_path (str, optional): Absolute path to local project
            - repo_url (str, optional): GitHub URL to clone
            - mode (str): 'extract', 'validate', or 'submit'
            - narrative_json (str, optional): JSON of ProformaNarrativeData

    Returns:
        str: JSON with proforma data, validation results, or submission outcome
    """
    tmp_dir = None

    try:
        # ==================================================================
        # MODE: EXTRACT
        # ==================================================================
        if params.mode == "extract":
            if not params.project_path and not params.repo_url:
                return json.dumps({
                    "error": "Either project_path or repo_url is required for extract mode.",
                })

            # Resolve source path
            if params.repo_url:
                # Clone remote repo
                try:
                    funcs = _import_analyze_repo()
                except ImportError as e:
                    return json.dumps({
                        "error": f"analyze_repo.py not found: {e}",
                        "tip": "The analysis module is not available in this deployment.",
                    })

                size_kb = _deep_search_check_size(params.repo_url)
                if size_kb is not None:
                    size_mb = round(size_kb / 1024, 1)
                    if size_mb > DEEP_SEARCH_MAX_REPO_SIZE_MB:
                        return json.dumps({
                            "error": f"Repository is {size_mb} MB, exceeds limit of {DEEP_SEARCH_MAX_REPO_SIZE_MB} MB.",
                        })

                tmp_dir = tempfile.mkdtemp(prefix="rm_proforma_")
                project_path = os.path.join(tmp_dir, "repo")
                try:
                    _deep_search_clone(params.repo_url, project_path)
                except RuntimeError as e:
                    return json.dumps({
                        "error": str(e),
                        "tip": "Check the URL is correct and the repository is public.",
                    })
            else:
                project_path = params.project_path
                if not os.path.isdir(project_path):
                    return json.dumps({
                        "error": f"Directory not found: {project_path}",
                    })

            # Run analyze_repo functions
            try:
                funcs = _import_analyze_repo()
            except ImportError as e:
                return json.dumps({
                    "error": f"analyze_repo.py not found: {e}",
                    "tip": "The analysis module is not available in this deployment.",
                })

            report = funcs["AnalysisReport"]()
            report.repo = funcs["analyze_git"](project_path)
            title, desc = funcs["analyze_readme"](project_path)
            report.repo.readme_title = title
            report.repo.readme_description = desc
            report.files = funcs["analyze_file_tree"](project_path)
            report.deps = funcs["analyze_dependencies"](project_path)

            report_dict = funcs["asdict"](report)
            machine_data = {
                "repo": report_dict.get("repo", {}),
                "files": report_dict.get("files", {}),
                "deps": report_dict.get("deps", {}),
            }

            # Detect project type
            project_type = _detect_project_type(report_dict.get("files", {}))
            machine_data["project_type"] = project_type

            # Infer demo_types and code_languages (machine-extracted, deterministic)
            loc = report_dict.get("files", {}).get("loc_by_language", {})
            code_languages = list(loc.keys())
            exts = set(report_dict.get("files", {}).get("files_by_extension", {}).keys())
            demo_types = []
            if code_languages:
                demo_types.append("code")
            if exts & {".csv", ".sql", ".sqlite", ".parquet"}:
                demo_types.append("data")
            if exts & {".tex", ".bib"}:
                demo_types.append("math")
            machine_data["demo_types_detected"] = demo_types
            machine_data["code_languages"] = code_languages

            # Select key files and build prompt
            key_files = _select_key_files(project_path, machine_data)
            prompt = _build_narrative_prompt(machine_data, key_files)

            # Sanitize paths in machine_data if cloned
            if params.repo_url and "repo" in machine_data:
                machine_data["repo"]["path"] = params.repo_url

            return json.dumps({
                "status": "proforma_ready",
                "proforma_version": PROFORMA_VERSION,
                "project_type": project_type,
                "machine_data": machine_data,
                "prompt_template": prompt,
                "key_files_included": list(key_files.keys()),
                "instructions": (
                    "Execute the prompt_template with an AI to generate narrative JSON, "
                    "then call prepare_commit with mode='validate' and narrative_json=<the JSON output>."
                ),
            }, indent=2)

        # ==================================================================
        # MODE: VALIDATE
        # ==================================================================
        elif params.mode == "validate":
            if not params.narrative_json:
                return json.dumps({
                    "error": "narrative_json is required for validate mode.",
                })

            # Parse narrative
            try:
                narrative_raw = json.loads(params.narrative_json)
                narrative = ProformaNarrativeData(**narrative_raw)
            except json.JSONDecodeError as e:
                return json.dumps({
                    "error": f"Invalid JSON in narrative_json: {e}",
                })
            except Exception as e:
                return json.dumps({
                    "error": f"Narrative validation failed: {e}",
                })

            # We need machine_data for validation — extract from narrative_json context
            # or accept that validate mode works with minimal machine context
            machine_dict = {}
            if params.project_path and os.path.isdir(params.project_path):
                try:
                    funcs = _import_analyze_repo()
                    report = funcs["AnalysisReport"]()
                    report.repo = funcs["analyze_git"](params.project_path)
                    report.files = funcs["analyze_file_tree"](params.project_path)
                    report_dict = funcs["asdict"](report)
                    machine_dict = {
                        "repo": report_dict.get("repo", {}),
                        "files": report_dict.get("files", {}),
                    }
                except Exception:
                    pass  # Validate without machine data

            validation = _validate_narrative(machine_dict, narrative)

            # Build preview of what SubmitCommitInput would look like
            sa = narrative.solidity_assessment
            preview = {
                "domain": narrative.domain,
                "subdomain": narrative.subdomain,
                "problem": narrative.problem,
                "hypothesis": narrative.hypothesis,
                "theoretical_framework": narrative.theoretical_framework,
                "demonstrations_summary": narrative.demonstrations_summary,
                "adhoc_summary": narrative.adhoc_summary,
                "adhoc_connections": narrative.adhoc_connections,
                "cherry_picking": narrative.cherry_picking,
                "solidity_levels": {
                    "theory": sa.theory_solidity,
                    "demos": sa.demos_solidity,
                    "adhoc": sa.adhoc_solidity,
                },
                "overall_solidity": sa.overall_solidity,
            }

            status = "has_errors" if validation["errors"] else "valid"

            return json.dumps({
                "status": status,
                "errors": validation["errors"],
                "warnings": validation["warnings"],
                "preview": preview,
                "next_step": (
                    "Fix errors and re-validate." if validation["errors"]
                    else "Call prepare_commit with mode='submit' to submit this commit."
                ),
            }, indent=2)

        # ==================================================================
        # MODE: SUBMIT
        # ==================================================================
        elif params.mode == "submit":
            if not params.narrative_json:
                return json.dumps({
                    "error": "narrative_json is required for submit mode.",
                })

            # Parse narrative
            try:
                narrative_raw = json.loads(params.narrative_json)
                narrative = ProformaNarrativeData(**narrative_raw)
            except json.JSONDecodeError as e:
                return json.dumps({
                    "error": f"Invalid JSON in narrative_json: {e}",
                })
            except Exception as e:
                return json.dumps({
                    "error": f"Narrative validation failed: {e}",
                })

            # Re-extract machine data if project_path available
            machine_dict = {}
            demo_types: List[str] = []
            code_languages: List[str] = []

            source_path = params.project_path
            if params.repo_url and not source_path:
                tmp_dir = tempfile.mkdtemp(prefix="rm_proforma_")
                source_path = os.path.join(tmp_dir, "repo")
                try:
                    _deep_search_clone(params.repo_url, source_path)
                except RuntimeError as e:
                    return json.dumps({"error": str(e)})

            if source_path and os.path.isdir(source_path):
                try:
                    funcs = _import_analyze_repo()
                    report = funcs["AnalysisReport"]()
                    report.repo = funcs["analyze_git"](source_path)
                    report.files = funcs["analyze_file_tree"](source_path)
                    report_dict = funcs["asdict"](report)
                    machine_dict = {
                        "repo": report_dict.get("repo", {}),
                        "files": report_dict.get("files", {}),
                    }
                    loc = report_dict.get("files", {}).get("loc_by_language", {})
                    code_languages = list(loc.keys())
                    exts = set(report_dict.get("files", {}).get("files_by_extension", {}).keys())
                    if code_languages:
                        demo_types.append("code")
                    if exts & {".csv", ".sql", ".sqlite", ".parquet"}:
                        demo_types.append("data")
                    if exts & {".tex", ".bib"}:
                        demo_types.append("math")
                except Exception:
                    pass

            # Validate
            validation = _validate_narrative(machine_dict, narrative)
            if validation["errors"]:
                return json.dumps({
                    "status": "has_errors",
                    "errors": validation["errors"],
                    "warnings": validation["warnings"],
                    "tip": "Fix errors and retry with mode='submit'.",
                }, indent=2)

            # Map to SubmitCommitInput and submit
            db = _get_db(ctx)
            datastore = _get_datastore(ctx)
            evaluator = _get_evaluator(ctx)
            user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
            if not user:
                return json.dumps({
                    "error": "No registered user found. Please register first with research_match_register.",
                })

            user_id = user["id"]

            # Build commit data — machine fields override narrative
            sa = narrative.solidity_assessment
            solidity_dict = {
                "theory": sa.theory_solidity,
                "demos": sa.demos_solidity,
                "adhoc": sa.adhoc_solidity,
                "cherry_picking": "cherry_picked",
            }
            overall_sol = sa.overall_solidity

            commit_data = {
                "domain": narrative.domain,
                "subdomain": narrative.subdomain,
                "problem": narrative.problem,
                "hypothesis": narrative.hypothesis,
                "theoretical_framework": narrative.theoretical_framework,
                "demonstrations_summary": narrative.demonstrations_summary,
                "demo_types": demo_types or (["code"] if code_languages else []),
                "code_languages": code_languages,
                "adhoc_summary": narrative.adhoc_summary,
                "adhoc_connections": narrative.adhoc_connections,
                "cherry_picking": narrative.cherry_picking,
                "solidity_levels": solidity_dict,
                "overall_solidity": overall_sol,
            }

            content_hash = _hash_content(commit_data)
            scores = await evaluator.evaluate_commit(commit_data, user_id)
            commit_id = str(uuid.uuid4())
            now_iso = datetime.now(timezone.utc).isoformat()

            if datastore:
                version = await datastore.get_next_commit_version(user_id)
                prev = await datastore.get_latest_commit_by_user(user_id)
                prev_id = prev["id"] if prev else None
                commit_record = {
                    "id": commit_id, "user_id": user_id, "version": version,
                    "domain": narrative.domain, "subdomain": narrative.subdomain,
                    "problem": narrative.problem, "hypothesis": narrative.hypothesis,
                    "theoretical_framework": narrative.theoretical_framework,
                    "demonstrations_summary": narrative.demonstrations_summary,
                    "demo_types": json.dumps(commit_data["demo_types"]),
                    "code_languages": json.dumps(commit_data["code_languages"]),
                    "adhoc_summary": narrative.adhoc_summary,
                    "adhoc_connections": json.dumps(narrative.adhoc_connections),
                    "cherry_picking": json.dumps(narrative.cherry_picking),
                    "solidity_levels": json.dumps(solidity_dict),
                    "overall_solidity": overall_sol,
                    "content_hash": content_hash,
                    "ot_score": scores["ot_score"], "ofc_score": scores["ofc_score"],
                    "ot_breakdown": json.dumps(scores["ot_breakdown"]),
                    "ofc_breakdown": json.dumps(scores["ofc_breakdown"]),
                    "solidity_impact": json.dumps(scores["solidity_impact"]),
                    "is_latest": True, "created_at": now_iso,
                }
                await datastore.submit_commit_and_mark_latest(commit_record, previous_commit_id=prev_id)
            else:
                last = db.execute(
                    "SELECT MAX(version) as v FROM research_commits WHERE user_id = ?",
                    (user_id,)
                ).fetchone()
                version = (last["v"] or 0) + 1
                db.execute("""
                    INSERT INTO research_commits
                    (id, user_id, version, domain, subdomain, problem, hypothesis,
                     theoretical_framework, demonstrations_summary, demo_types,
                     code_languages, adhoc_summary, adhoc_connections, cherry_picking,
                     solidity_levels, overall_solidity,
                     content_hash, ot_score, ofc_score, ot_breakdown, ofc_breakdown,
                     solidity_impact)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    commit_id, user_id, version,
                    narrative.domain, narrative.subdomain, narrative.problem,
                    narrative.hypothesis, narrative.theoretical_framework,
                    narrative.demonstrations_summary,
                    json.dumps(commit_data["demo_types"]),
                    json.dumps(commit_data["code_languages"]),
                    narrative.adhoc_summary, json.dumps(narrative.adhoc_connections),
                    json.dumps(narrative.cherry_picking),
                    json.dumps(solidity_dict), overall_sol,
                    content_hash,
                    scores["ot_score"], scores["ofc_score"],
                    json.dumps(scores["ot_breakdown"]), json.dumps(scores["ofc_breakdown"]),
                    json.dumps(scores["solidity_impact"]),
                ))
                db.commit()

            return json.dumps({
                "status": "submitted",
                "commit_id": commit_id,
                "version": version,
                "content_hash": content_hash,
                "scores": {
                    "theoretical_originality": scores["ot_score"],
                    "formal_computational_originality": scores["ofc_score"],
                    "ot_raw": scores["ot_raw"],
                    "ofc_raw": scores["ofc_raw"],
                },
                "solidity": {
                    "overall": overall_sol,
                    "components": solidity_dict,
                    "impact": scores["solidity_impact"]["explanation"],
                },
                "warnings": validation["warnings"],
                "source": "proforma_submit",
                "message": (
                    "Research Commit submitted via proforma. "
                    "Machine-extracted fields (code_languages, demo_types) used for accuracy. "
                    "Use research_match_find_collaborators to discover matches."
                ),
            }, indent=2)

        else:
            return json.dumps({"error": f"Unknown mode: {params.mode}"})

    except Exception as e:
        _logger.error("prepare_commit error: %s", e, exc_info=True)
        return json.dumps({
            "error": f"Internal error: {str(e)}",
            "tip": "Check that the project path exists and analyze_repo.py is available.",
        })
    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# CONTRACT TOOLS (NEED-08 — Git-Verifiable Collaboration Contracts)
# =============================================================================

@mcp.tool(
    name="research_match_export_contract",
    description=(
        "Generate a git-verifiable collaboration contract for your team. "
        "Captures both parties, commits with scores, license type, contribution split, "
        "and timestamps as a markdown file. BOTH members must commit this file to their repos. "
        "Suggested path: .research-match/CONTRACT_<team_short>.md. "
        "After committing, use research_match_confirm_contract to record the git hash. "
        "Contract is valid only when BOTH parties confirm."
    ),
    annotations={
        "title": "Export Contract",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_export_contract(params: ExportContractInput, ctx: Context = None) -> str:
    """Generate a collaboration contract for bilateral git verification.

    Args:
        params (ExportContractInput): Query data:
            - team_id (str, required): Team to generate contract for

    Returns:
        str: JSON with contract_id, version, content_hash, markdown content,
             suggested_path, instructions, and status
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Compute current license
    license_info = await _compute_license(db, params.team_id, datastore=datastore)

    if datastore:
        contract_version = await datastore.get_next_contract_version(params.team_id)
        await datastore.supersede_pending_contracts(params.team_id)
        content = await _generate_contract_content(db, params.team_id, license_info, contract_version, datastore=datastore)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        contract_id = str(uuid.uuid4())
        team_data = await datastore.get_team_by_id(params.team_id)
        team_short = (team_data["name"] if team_data else params.team_id[:8]).replace(" ", "_")
        now_iso = datetime.now(timezone.utc).isoformat()
        await datastore.insert_contract({
            "id": contract_id, "team_id": params.team_id,
            "contract_version": contract_version,
            "license_type": license_info["license_type"],
            "contribution_split": json.dumps(license_info.get("contribution_split", {})),
            "contract_content": content, "content_hash": content_hash,
            "generated_by": user["id"], "status": "pending",
            "created_at": now_iso,
        })
    else:
        last_version = db.execute(
            "SELECT MAX(contract_version) as v FROM collaboration_contracts WHERE team_id = ?",
            (params.team_id,)
        ).fetchone()
        contract_version = (last_version["v"] or 0) + 1
        db.execute(
            """UPDATE collaboration_contracts
               SET status = 'superseded'
               WHERE team_id = ? AND status IN ('pending', 'partial')""",
            (params.team_id,)
        )
        content = await _generate_contract_content(db, params.team_id, license_info, contract_version, datastore=datastore)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        contract_id = str(uuid.uuid4())
        team = db.execute("SELECT name FROM teams WHERE id = ?", (params.team_id,)).fetchone()
        team_short = (team["name"] if team else params.team_id[:8]).replace(" ", "_")
        db.execute(
            """INSERT INTO collaboration_contracts
               (id, team_id, contract_version, license_type, contribution_split,
                contract_content, content_hash, generated_by, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (contract_id, params.team_id, contract_version,
             license_info["license_type"],
             json.dumps(license_info.get("contribution_split", {})),
             content, content_hash, user["id"])
        )

    await _write_audit_log(datastore or db, params.team_id, user["id"], "license_generated",
                     resource_ref=contract_id,
                     details={"trigger": "contract_generated",
                              "contract_version": contract_version,
                              "license_type": license_info["license_type"],
                              "content_hash": content_hash})
    if db:
        db.commit()

    suggested_path = f"{CONTRACT_DIR_NAME}/{CONTRACT_FILE_PREFIX}{team_short}.md"

    return json.dumps({
        "status": "pending",
        "contract_id": contract_id,
        "contract_version": contract_version,
        "content_hash": content_hash,
        "suggested_path": suggested_path,
        "contract_content": content,
        "instructions": (
            f"1. Save this contract to '{suggested_path}' in BOTH parties' repositories.\n"
            f"2. Commit the file: git add {suggested_path} && git commit -m 'Add collaboration contract'\n"
            f"3. Each party calls research_match_confirm_contract with the git commit hash.\n"
            f"4. Contract becomes 'confirmed' only when BOTH parties confirm."
        ),
    }, indent=2)


@mcp.tool(
    name="research_match_confirm_contract",
    description=(
        "Confirm that a collaboration contract has been committed to your git repository. "
        "Call AFTER committing the contract file. Provide contract_id and git commit hash. "
        "Contract becomes 'confirmed' only when BOTH members confirm. "
        "Until both confirm, status is 'partial'."
    ),
    annotations={
        "title": "Confirm Contract",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
@_log_tool_call
async def research_match_confirm_contract(params: ConfirmContractInput, ctx: Context = None) -> str:
    """Confirm that a collaboration contract has been committed to git.

    Args:
        params (ConfirmContractInput): Confirmation data:
            - team_id (str, required): Team ID
            - contract_id (str, required): Contract ID from export_contract
            - git_commit_hash (str, required): 40-char hex SHA
            - repo_url (str, optional): Repository URL

    Returns:
        str: JSON with contract_id, status, your/partner confirmations, message
    """
    db = _get_db(ctx)
    datastore = _get_datastore(ctx)
    user = await _get_current_user(db, datastore=datastore, user_email_hash=_get_user_email_hash(ctx))
    if not user:
        return json.dumps({"error": "No registered user found. Use research_match_register first."})

    # Verify membership
    if datastore:
        membership = await datastore.get_team_member(params.team_id, user["id"])
    else:
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (params.team_id, user["id"])
        ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Fetch contract
    if datastore:
        contract = await datastore.get_contract(params.contract_id, params.team_id)
    else:
        contract = db.execute(
            "SELECT * FROM collaboration_contracts WHERE id = ? AND team_id = ?",
            (params.contract_id, params.team_id)
        ).fetchone()
    if not contract:
        return json.dumps({"error": "Contract not found for this team."})

    contract = dict(contract)
    if contract["status"] in ("superseded", "confirmed"):
        return json.dumps({
            "error": f"Contract is already '{contract['status']}'. Cannot modify.",
            "contract_id": params.contract_id,
            "status": contract["status"],
        })

    now = datetime.now(timezone.utc).isoformat()
    user_id = user["id"]

    # Determine slot (A or B)
    if contract.get("confirmation_a_user_id") is None:
        slot = "a"
    elif contract["confirmation_a_user_id"] == user_id:
        slot = "a"
    else:
        slot = "b"

    if datastore:
        await datastore.update_contract_confirmation(
            params.contract_id, slot, user_id,
            params.git_commit_hash, params.repo_url, now)
        updated = await datastore.get_contract(params.contract_id, params.team_id)
        updated = dict(updated)
    else:
        if slot == "a":
            db.execute(
                """UPDATE collaboration_contracts
                   SET confirmation_a_user_id = ?, confirmation_a_git_hash = ?,
                       confirmation_a_repo_url = ?, confirmation_a_at = ?
                   WHERE id = ?""",
                (user_id, params.git_commit_hash, params.repo_url, now, params.contract_id)
            )
        else:
            db.execute(
                """UPDATE collaboration_contracts
                   SET confirmation_b_user_id = ?, confirmation_b_git_hash = ?,
                       confirmation_b_repo_url = ?, confirmation_b_at = ?
                   WHERE id = ?""",
                (user_id, params.git_commit_hash, params.repo_url, now, params.contract_id)
            )
        updated = dict(db.execute(
            "SELECT * FROM collaboration_contracts WHERE id = ?",
            (params.contract_id,)
        ).fetchone())

    both_confirmed = (
        updated.get("confirmation_a_user_id") is not None and
        updated.get("confirmation_b_user_id") is not None
    )
    new_status = "confirmed" if both_confirmed else "partial"

    if datastore:
        await datastore.update_contract_status(params.contract_id, new_status)
    else:
        db.execute(
            "UPDATE collaboration_contracts SET status = ? WHERE id = ?",
            (new_status, params.contract_id)
        )

    await _write_audit_log(datastore or db, params.team_id, user_id, "license_generated",
                     resource_ref=params.contract_id,
                     details={"trigger": "contract_confirmed",
                              "slot": slot,
                              "git_commit_hash": params.git_commit_hash,
                              "new_status": new_status})
    if db:
        db.commit()

    your_confirmation = {
        "user_id": user_id,
        "git_commit_hash": params.git_commit_hash,
        "repo_url": params.repo_url,
        "confirmed_at": now,
    }

    partner_slot = "b" if slot == "a" else "a"
    partner_user = updated[f"confirmation_{partner_slot}_user_id"]
    partner_confirmation = None
    if partner_user:
        partner_confirmation = {
            "user_id": partner_user,
            "git_commit_hash": updated[f"confirmation_{partner_slot}_git_hash"],
            "repo_url": updated[f"confirmation_{partner_slot}_repo_url"],
            "confirmed_at": updated[f"confirmation_{partner_slot}_at"],
        }

    message = (
        "Contract CONFIRMED — both parties have committed the contract to their repos."
        if new_status == "confirmed"
        else "Your confirmation recorded. Waiting for your partner to confirm."
    )

    return json.dumps({
        "status": new_status,
        "contract_id": params.contract_id,
        "contract_version": updated["contract_version"],
        "content_hash": updated["content_hash"],
        "your_confirmation": your_confirmation,
        "partner_confirmation": partner_confirmation,
        "message": message,
    }, indent=2)


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    """Entry point for `uv run research-match` and direct execution."""
    backend_env = os.environ.get("RESEARCH_MATCH_BACKEND", "").lower()
    use_firestore = backend_env == "firestore" or bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

    if not use_firestore:
        # SQLite mode: ensure DB schema exists before server starts
        _boot_db = init_database(DB_PATH)
        _boot_db.close()
        _logger.info("Database initialized at %s", DB_PATH)
    else:
        _logger.info("Firestore mode — skipping SQLite init")

    # Determine transport: --http flag or PORT env var (Cloud Run)
    port_env = os.environ.get("PORT")
    if "--http" in sys.argv:
        port_idx = sys.argv.index("--http") + 1
        port = int(sys.argv[port_idx]) if port_idx < len(sys.argv) else 8000
        mcp.settings.port = port
        _logger.info("Starting streamable-http on port %d", port)
        mcp.run(transport="streamable-http")
    elif port_env:
        # Cloud Run: PORT env var set automatically, bind to 0.0.0.0
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(port_env)
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )
        _logger.info("Starting streamable-http on 0.0.0.0:%s (Cloud Run)", port_env)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
