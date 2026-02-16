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

import numpy as np
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict, field_validator


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

DB_PATH = os.environ.get("RESEARCH_MATCH_DB", "research_match.db")
SERVER_VERSION = "2.3.0-mvp"

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

        CREATE INDEX IF NOT EXISTS idx_commits_user ON research_commits(user_id);
        CREATE INDEX IF NOT EXISTS idx_commits_domain ON research_commits(domain, subdomain);
        CREATE INDEX IF NOT EXISTS idx_matches_users ON matches(user_a_id, user_b_id);
        CREATE INDEX IF NOT EXISTS idx_requests_recipient ON collaboration_requests(recipient_id, status);
        CREATE INDEX IF NOT EXISTS idx_ratings_rated ON ratings(rated_id);
        CREATE INDEX IF NOT EXISTS idx_ratings_team ON ratings(team_id);
    """)

    conn.commit()

    # Migration: add running average columns for exponential smoothing
    for col in ("running_honesty", "running_quality", "running_effort"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} REAL DEFAULT NULL")
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

    def __init__(self, db: sqlite3.Connection, embeddings: Optional[EmbeddingEngine] = None):
        self.db = db
        self.embeddings = embeddings or EmbeddingEngine()

    def evaluate_commit(self, commit_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Evaluate a Research Commit and return originality scores."""
        eval_logger = logging.getLogger("research_match.evaluator")

        # Get existing commits in the same domain for comparison
        corpus = self._get_corpus(commit_data["domain"], commit_data.get("subdomain"), user_id)
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

    def _get_corpus(self, domain: str, subdomain: Optional[str], exclude_user: str) -> List[Dict]:
        """Get existing commits in the same domain for comparison."""
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

    def __init__(self, db: sqlite3.Connection):
        self.db = db

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

    def calculate_reputation(self, user_id: str) -> Dict[str, Any]:
        """Calculate composite reputation for a user.

        Uses running averages if available (O(1)), falls back to batch recalculation.
        """
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
            avgs = self._batch_recalculate(user_id)
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

    def apply_new_rating(self, user_id: str, honesty: int, quality: int, effort: int) -> None:
        """Apply a single new rating using exponential smoothing O(1).

        Formula: new_avg = alpha * new_value + (1 - alpha) * old_avg
        """
        user = self.db.execute(
            "SELECT running_honesty, running_quality, running_effort FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()

        alpha = REPUTATION_ALPHA

        if user and user["running_honesty"] is not None:
            new_honesty = alpha * honesty + (1 - alpha) * user["running_honesty"]
            new_quality = alpha * quality + (1 - alpha) * user["running_quality"]
            new_effort = alpha * effort + (1 - alpha) * user["running_effort"]
        else:
            # First rating or migration: initialize from batch
            avgs = self._batch_recalculate(user_id)
            new_honesty = avgs["avg_honesty"]
            new_quality = avgs["avg_quality"]
            new_effort = avgs["avg_effort"]

        self.db.execute("""
            UPDATE users SET running_honesty = ?, running_quality = ?, running_effort = ?
            WHERE id = ?
        """, (new_honesty, new_quality, new_effort, user_id))
        self.db.commit()

    def _batch_recalculate(self, user_id: str) -> Dict[str, float]:
        """Recalculate running averages from all ratings (migration/fallback).

        Uses temporal weighting: recent ratings count more.
        Also stores the result as running averages for future O(1) updates.
        """
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

    def update_user_reputation(self, user_id: str) -> None:
        """Recalculate and store reputation for a user.

        Uses apply_new_rating for incremental path when possible.
        """
        rep = self.calculate_reputation(user_id)
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

    def check_both_rated(self, team_id: str, user_a_id: str, user_b_id: str) -> bool:
        """Check if both team members have rated each other."""
        a_rated_b = self.db.execute(
            "SELECT id FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
            (team_id, user_a_id, user_b_id)
        ).fetchone()
        b_rated_a = self.db.execute(
            "SELECT id FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
            (team_id, user_b_id, user_a_id)
        ).fetchone()
        return bool(a_rated_b and b_rated_a)

    def reveal_ratings(self, team_id: str) -> None:
        """Mark all ratings in a team as revealed (both have rated)."""
        self.db.execute(
            "UPDATE ratings SET is_revealed = 1 WHERE team_id = ?",
            (team_id,)
        )
        self.db.commit()

    def detect_abuse_patterns(self, rater_id: str) -> Dict[str, Any]:
        """Detect if a rater shows patterns of abusive rating behavior.

        Flags:
        - Always gives 1-star (vindictive)
        - Always gives 5-star (inflating)
        - Rates too quickly after team formation (didn't actually collaborate)
        """
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

    def __init__(self, db: sqlite3.Connection, embeddings: Optional[EmbeddingEngine] = None):
        self.db = db
        self.embeddings = embeddings or EmbeddingEngine()

    def find_matches(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Find potential collaborators for a user."""
        match_logger = logging.getLogger("research_match.matcher")

        # Get user's latest commit
        user_commit = self.db.execute(
            "SELECT * FROM research_commits WHERE user_id = ? ORDER BY version DESC LIMIT 1",
            (user_id,)
        ).fetchone()

        if not user_commit:
            return []

        user_commit = dict(user_commit)

        # Find commits in same/similar domain
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


# =============================================================================
# LIFESPAN & SERVER INITIALIZATION
# =============================================================================

_server_start_time: Optional[str] = None


@asynccontextmanager
async def app_lifespan():
    """Initialize database and engines."""
    global _server_start_time
    _server_start_time = datetime.now(timezone.utc).isoformat()
    db = init_database(DB_PATH)
    embeddings = EmbeddingEngine()
    evaluator = OriginalityEvaluator(db, embeddings)
    matcher = MatchingEngine(db, embeddings)
    reputation = ReputationEngine(db)
    yield {
        "db": db, "evaluator": evaluator, "matcher": matcher,
        "reputation": reputation, "embeddings": embeddings,
    }
    db.close()


mcp = FastMCP("research_match_mcp", lifespan=app_lifespan)


# =============================================================================
# HEALTH ENDPOINT (HTTP only)
# =============================================================================

def _health_stats() -> Dict[str, Any]:
    """Gather health statistics from the database."""
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

def _get_db(ctx) -> sqlite3.Connection:
    return ctx.request_context.lifespan_state["db"]

def _get_evaluator(ctx) -> OriginalityEvaluator:
    return ctx.request_context.lifespan_state["evaluator"]

def _get_matcher(ctx) -> MatchingEngine:
    return ctx.request_context.lifespan_state["matcher"]

def _get_reputation(ctx) -> ReputationEngine:
    return ctx.request_context.lifespan_state["reputation"]

def _get_or_create_user(db: sqlite3.Connection, email: str, pseudonym: Optional[str] = None) -> str:
    """Get existing user or create new one by email hash."""
    email_hash = hashlib.sha256(email.lower().strip().encode()).hexdigest()

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

def _get_current_user(db: sqlite3.Connection) -> Optional[Dict]:
    """Get the most recently created user (for single-user MVP)."""
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


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool(
    name="research_match_register",
    description=(
        "STEP 1 OF THE RESEARCH MATCH FLOW — Call this tool FIRST before any other research_match tool. "
        "Registers the user with a pseudonymous identity. The email is hashed with SHA-256 and NEVER stored in plain text. "
        "If the user is already registered (same email), returns existing profile. "
        "After registration, guide the user to submit a Research Commit using research_match_analyze_work or research_match_submit_commit. "
        "Example flow: register → analyze_work → submit_commit → find_collaborators → send_request."
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
async def research_match_register(params: RegisterInput, ctx=None) -> str:
    """Register a new user on Research Match. Creates a pseudonymous profile.
    Email is hashed and never stored in plain text. Idempotent: safe to call multiple times.

    Args:
        params (RegisterInput): Registration data containing:
            - email (str): Email address for identity (will be SHA-256 hashed)
            - pseudonym (Optional[str]): Preferred display name (auto-generated if omitted)

    Returns:
        str: JSON with user_id, pseudonym, and welcome message
    """
    from mcp.server.fastmcp import Context
    db = _get_db(ctx)
    user_id = _get_or_create_user(db, params.email, params.pseudonym)
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
async def research_match_submit_commit(params: SubmitCommitInput, ctx=None) -> str:
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
    evaluator = _get_evaluator(ctx)

    user = _get_current_user(db)
    if not user:
        return json.dumps({"error": "No registered user found. Please register first with research_match_register."})

    user_id = user["id"]

    # Get next version
    last = db.execute(
        "SELECT MAX(version) as v FROM research_commits WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    version = (last["v"] or 0) + 1

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
    scores = evaluator.evaluate_commit(commit_data, user_id)

    commit_id = str(uuid.uuid4())

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
    ))
    db.commit()

    return json.dumps({
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
    }, indent=2)


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
async def research_match_my_profile(ctx=None) -> str:
    """View current originality profile, scores, reputation, and commit history.

    Returns:
        str: JSON with pseudonym, reputation (badge/score/ratings), latest commit scores,
             OT/OFC breakdowns, solidity impact, and team list
    """
    db = _get_db(ctx)
    reputation_engine = _get_reputation(ctx)
    user = _get_current_user(db)
    if not user:
        return json.dumps({"error": "No registered user found. Please register first."})

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

    teams = db.execute("""
        SELECT t.* FROM teams t
        JOIN team_members tm ON t.id = tm.team_id
        WHERE tm.user_id = ?
    """, (user["id"],)).fetchall()

    # Get reputation details
    rep = reputation_engine.calculate_reputation(user["id"])

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
async def research_match_find_collaborators(params: FindCollaboratorsInput, ctx=None) -> str:
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
    matcher = _get_matcher(ctx)
    user = _get_current_user(db)

    if not user:
        return json.dumps({"error": "No registered user found. Please register first."})

    matches = matcher.find_matches(user["id"], params.limit or 5)

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

    return json.dumps({
        "your_profile": f"OT: {dict(db.execute('SELECT ot_score, ofc_score FROM research_commits WHERE user_id = ? ORDER BY version DESC LIMIT 1', (user['id'],)).fetchone())}",
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
async def research_match_send_request(params: SendRequestInput, ctx=None) -> str:
    """Send a collaboration request to a matched researcher.

    Args:
        params (SendRequestInput): Request data:
            - candidate_user_id (str, required): Target user ID from find_collaborators results
            - message (str, optional): Describe what you're looking for (max 1000 chars)

    Returns:
        str: JSON with request_id, status, semaphore, reason, and next steps
    """
    db = _get_db(ctx)
    user = _get_current_user(db)
    if not user:
        return json.dumps({"error": "No registered user found."})

    # Find the match record
    match = db.execute("""
        SELECT * FROM matches
        WHERE (user_a_id = ? AND user_b_id = ?) OR (user_a_id = ? AND user_b_id = ?)
        ORDER BY created_at DESC LIMIT 1
    """, (user["id"], params.candidate_user_id, params.candidate_user_id, user["id"])).fetchone()

    if not match:
        return json.dumps({"error": "No match found with this user. Run find_collaborators first."})

    match = dict(match)

    # Check for existing pending request
    existing = db.execute("""
        SELECT * FROM collaboration_requests
        WHERE requester_id = ? AND recipient_id = ? AND status = 'pending'
    """, (user["id"], params.candidate_user_id)).fetchone()

    if existing:
        return json.dumps({"error": "You already have a pending request to this user."})

    request_id = str(uuid.uuid4())
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
async def research_match_inbox(ctx=None) -> str:
    """View incoming and outgoing collaboration requests with semaphore indicators.

    Returns:
        str: JSON with 'incoming' and 'outgoing' arrays, each entry containing:
             request_id, from/to pseudonym, semaphore (emoji + level), reason,
             complementarity %, message, status, and date
    """
    db = _get_db(ctx)
    user = _get_current_user(db)
    if not user:
        return json.dumps({"error": "No registered user found."})

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
async def research_match_respond_request(params: RespondRequestInput, ctx=None) -> str:
    """Accept or reject a collaboration request.

    Args:
        params (RespondRequestInput): Response data:
            - request_id (str, required): ID of the request (from research_match_inbox)
            - accept (bool, required): true to accept, false to reject

    Returns:
        str: JSON with status ('accepted'/'rejected'), and if accepted: team_id, team_name, license type
    """
    db = _get_db(ctx)
    user = _get_current_user(db)
    if not user:
        return json.dumps({"error": "No registered user found."})

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
    db.execute("""
        UPDATE collaboration_requests
        SET status = ?, responded_at = datetime('now')
        WHERE id = ?
    """, (new_status, params.request_id))

    result = {"status": new_status, "request_id": params.request_id}

    if params.accept:
        # Create team
        team_id = str(uuid.uuid4())
        team_name = f"team-{team_id[:8]}"
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
        db.commit()

        result["team"] = {
            "team_id": team_id,
            "team_name": team_name,
            "license": "joint-equal",
            "message": "Team created! Gradual revelation process begins. You can now rate each other after collaborating using research_match_rate_user."
        }
    else:
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
async def research_match_rate_user(params: RateUserInput, ctx=None) -> str:
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
    reputation_engine = _get_reputation(ctx)
    user = _get_current_user(db)
    if not user:
        return json.dumps({"error": "No registered user found."})

    # Verify the rater is a member of the team
    membership = db.execute(
        "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
        (params.team_id, user["id"])
    ).fetchone()
    if not membership:
        return json.dumps({"error": "You are not a member of this team."})

    # Verify the rated user is also a member
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
    existing = db.execute(
        "SELECT id FROM ratings WHERE team_id = ? AND rater_id = ? AND rated_id = ?",
        (params.team_id, user["id"], params.rated_user_id)
    ).fetchone()
    if existing:
        return json.dumps({"error": "You have already rated this user for this team. Ratings cannot be modified to prevent gaming."})

    # Check for abuse patterns
    abuse = reputation_engine.detect_abuse_patterns(user["id"])
    abuse_warning = ""
    if abuse["abuse_detected"]:
        abuse_warning = f" Warning: Your rating patterns show {', '.join(abuse['flags'])}. Continued abuse may affect your own reputation."

    # Submit rating
    rating_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (rating_id, params.team_id, user["id"], params.rated_user_id,
          params.honesty, params.quality, params.effort, params.comment))
    db.commit()

    # Check if both have rated each other
    both_rated = reputation_engine.check_both_rated(
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
        reputation_engine.reveal_ratings(params.team_id)
        reputation_engine.update_user_reputation(params.rated_user_id)
        reputation_engine.update_user_reputation(user["id"])

        # Get the other person's rating of you
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
async def research_match_analyze_work(ctx=None) -> str:
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


def _cold_search_internal(db: sqlite3.Connection, query: str, limit: int) -> List[Dict]:
    """Search the internal database for public research commits matching a query.
    Returns basic info only: domain, subdomain, problem, hypothesis, solidity."""
    keywords = query.lower().split()
    if not keywords:
        return []

    # Build a LIKE filter across multiple columns
    conditions = []
    params = []
    for kw in keywords[:5]:  # Limit to 5 keywords
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
async def research_match_cold_search(params: ColdSearchInput, ctx=None) -> str:
    """Execute a cold search across internal DB and GitHub."""
    query = params.query
    limit = params.max_results

    # Split limit between sources
    internal_limit = max(1, limit // 2)
    github_limit = max(1, limit - internal_limit)

    # Search internal DB
    db = _get_db(ctx)
    internal_results = _cold_search_internal(db, query, internal_limit)

    # If few internal results, give more slots to GitHub
    if len(internal_results) < internal_limit:
        github_limit += (internal_limit - len(internal_results))

    # Search GitHub
    github_results = _cold_search_github(query, github_limit)

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


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    if "--http" in sys.argv:
        port_idx = sys.argv.index("--http") + 1
        port = int(sys.argv[port_idx]) if port_idx < len(sys.argv) else 8000
        mcp.settings.port = port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
