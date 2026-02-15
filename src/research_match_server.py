"""
Research Match MCP Server
=========================
MCP Server that integrates Research Match into Claude.
Allows researchers to submit work, get originality scores,
find collaborators, rate collaborators, and manage collaboration requests.

v2.0 — Added: Rating system, solidity levels, reputation engine.

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
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from enum import Enum

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict, field_validator


# =============================================================================
# CONSTANTS
# =============================================================================

DB_PATH = os.environ.get("RESEARCH_MATCH_DB", "research_match.db")
SERVER_VERSION = "2.0.0-mvp"

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

# Semaphore thresholds
GREEN_THRESHOLD = 30   # Both users contribute >30% complementary originality
YELLOW_ASYMMETRY = 15  # Asymmetry >15 points
RED_THRESHOLD = 15     # Both contribute <15% or overlap >75%

# Rating constants
RATING_MIN = 1
RATING_MAX = 5
MIN_RATINGS_FOR_REPUTATION = 2  # Need at least 2 ratings to affect reputation


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
    """

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def evaluate_commit(self, commit_data: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Evaluate a Research Commit and return originality scores."""

        # Get existing commits in the same domain for comparison
        corpus = self._get_corpus(commit_data["domain"], commit_data.get("subdomain"), user_id)

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
        """Simple word-overlap similarity. Production would use embeddings."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a & words_b
        union = words_a | words_b
        return len(intersection) / len(union)

    def _commit_similarity(self, a: Dict, b: Dict) -> float:
        """Calculate overall similarity between two commits."""
        scores = []
        for field in ["problem", "hypothesis", "theoretical_framework"]:
            va = (a.get(field) or "").lower()
            vb = (b.get(field) or "").lower()
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

    Anti-retaliation: Ratings are anonymous until BOTH team members
    have rated each other. This prevents strategic rating.
    """

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def calculate_reputation(self, user_id: str) -> Dict[str, Any]:
        """Calculate composite reputation for a user."""
        ratings = self.db.execute(
            "SELECT * FROM ratings WHERE rated_id = ? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()

        if len(ratings) < MIN_RATINGS_FOR_REPUTATION:
            return {
                "reputation_score": 100.0,  # Default for new users
                "total_ratings": len(ratings),
                "avg_honesty": 0.0,
                "avg_quality": 0.0,
                "avg_effort": 0.0,
                "status": "insufficient_data",
                "message": f"Need at least {MIN_RATINGS_FOR_REPUTATION} ratings to calculate reputation."
            }

        # Temporal weighting: recent ratings count more
        total_weight = 0.0
        weighted_honesty = 0.0
        weighted_quality = 0.0
        weighted_effort = 0.0

        for i, r in enumerate(ratings):
            r = dict(r)
            # More recent = higher weight (exponential decay)
            weight = 0.9 ** i  # Most recent = 1.0, then 0.9, 0.81, etc.
            total_weight += weight
            weighted_honesty += r["honesty"] * weight
            weighted_quality += r["quality"] * weight
            weighted_effort += r["effort"] * weight

        avg_honesty = weighted_honesty / total_weight
        avg_quality = weighted_quality / total_weight
        avg_effort = weighted_effort / total_weight

        # Composite reputation (0-100 scale)
        # Honesty weighs most heavily — a dishonest user poisons the ecosystem
        reputation = (
            (avg_honesty / 5.0) * 50.0 +   # 50% weight on honesty
            (avg_quality / 5.0) * 30.0 +     # 30% weight on quality
            (avg_effort / 5.0) * 20.0        # 20% weight on effort
        )

        # Penalty for very low honesty (busca/dishonest users)
        if avg_honesty < 2.0:
            reputation *= 0.5  # Harsh penalty for dishonesty

        # Bonus for consistent high ratings
        if len(ratings) >= 5 and avg_honesty >= 4.0 and avg_quality >= 3.5:
            reputation = min(100.0, reputation * 1.1)

        return {
            "reputation_score": round(reputation, 1),
            "total_ratings": len(ratings),
            "avg_honesty": round(avg_honesty, 2),
            "avg_quality": round(avg_quality, 2),
            "avg_effort": round(avg_effort, 2),
            "status": "calculated",
        }

    def update_user_reputation(self, user_id: str) -> None:
        """Recalculate and store reputation for a user."""
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
    """Calculates matches and bilateral convenience semaphores."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def find_matches(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Find potential collaborators for a user."""
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
        return matches[:limit]

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
        """Calculate how similar the theoretical base is."""
        score = 0.0
        if a.get("domain") == b.get("domain"):
            score += 40.0
        if a.get("subdomain") and a.get("subdomain") == b.get("subdomain"):
            score += 30.0

        # Problem similarity
        prob_a = (a.get("problem") or "").lower()
        prob_b = (b.get("problem") or "").lower()
        if prob_a and prob_b:
            words_a = set(prob_a.split())
            words_b = set(prob_b.split())
            if words_a and words_b:
                overlap = len(words_a & words_b) / len(words_a | words_b)
                score += overlap * 30.0

        return min(100.0, score)

    def _calculate_gain(self, my_ot: float, my_ofc: float, their_ot: float, their_ofc: float) -> float:
        """Calculate what I gain from the other person's strengths in my weaknesses."""
        ot_diff = max(0, their_ot - my_ot)
        ofc_diff = max(0, their_ofc - my_ofc)

        ot_gain = ot_diff * (their_ot / 100.0) * 1.5
        ofc_gain = ofc_diff * (their_ofc / 100.0) * 1.5

        weakness_bonus_ot = max(0, (100 - my_ot) * (their_ot / 100.0) * 0.3)
        weakness_bonus_ofc = max(0, (100 - my_ofc) * (their_ofc / 100.0) * 0.3)

        total = ot_gain + ofc_gain + weakness_bonus_ot + weakness_bonus_ofc
        return min(100.0, total)

    def _calculate_semaphore(self, a_gains: float, b_gains: float) -> Dict[str, str]:
        """Calculate the bilateral convenience semaphore with reasoning."""
        asymmetry = abs(a_gains - b_gains)
        a_stronger = a_gains > b_gains

        if a_gains >= GREEN_THRESHOLD and b_gains >= GREEN_THRESHOLD:
            return {
                "color": "green",
                "reason_for_a": f"Alta conveniencia mutua. Ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. Colaboración equilibrada.",
                "reason_for_b": f"Alta conveniencia mutua. Ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. Colaboración equilibrada.",
                "summary": "Ambos se benefician significativamente. Match recomendado."
            }
        elif a_gains < RED_THRESHOLD and b_gains < RED_THRESHOLD:
            return {
                "color": "red",
                "reason_for_a": f"Baja conveniencia. Solo ganás {a_gains:.0f}% y aportás {b_gains:.0f}%. Perfiles demasiado similares o sin complementariedad.",
                "reason_for_b": f"Baja conveniencia. Solo ganás {b_gains:.0f}% y aportás {a_gains:.0f}%. Perfiles demasiado similares o sin complementariedad.",
                "summary": "Alta redundancia o bajo aporte mutuo. No se recomienda."
            }
        elif asymmetry > YELLOW_ASYMMETRY:
            if a_stronger:
                return {
                    "color": "yellow",
                    "reason_for_a": f"Asimetría a tu favor. Ganás {a_gains:.0f}% pero solo aportás {b_gains:.0f}%. El otro usuario podría no aceptar sin negociación de términos.",
                    "reason_for_b": f"Asimetría en tu contra. Solo ganás {b_gains:.0f}% pero aportás {a_gains:.0f}%. Considerá negociar términos de licencia antes de aceptar.",
                    "summary": f"Asimetría significativa ({asymmetry:.0f} puntos). El solicitante se beneficia más."
                }
            else:
                return {
                    "color": "yellow",
                    "reason_for_a": f"Asimetría en tu contra. Solo ganás {a_gains:.0f}% pero aportás {b_gains:.0f}%. Considerá negociar términos de licencia antes de aceptar.",
                    "reason_for_b": f"Asimetría a tu favor. Ganás {b_gains:.0f}% pero solo aportás {a_gains:.0f}%. El otro usuario podría no aceptar sin negociación de términos.",
                    "summary": f"Asimetría significativa ({asymmetry:.0f} puntos). El receptor se beneficia más."
                }
        elif a_gains >= GREEN_THRESHOLD or b_gains >= GREEN_THRESHOLD:
            if a_gains >= GREEN_THRESHOLD:
                return {
                    "color": "yellow",
                    "reason_for_a": f"Conveniencia moderada. Ganás {a_gains:.0f}% pero el otro solo gana {b_gains:.0f}%. Podrías necesitar ofrecer incentivos adicionales.",
                    "reason_for_b": f"Conveniencia moderada. Ganás {b_gains:.0f}% — el beneficio para vos es limitado. Evaluá si los términos compensan.",
                    "summary": "Un lado se beneficia claramente más. Funcional con negociación."
                }
            else:
                return {
                    "color": "yellow",
                    "reason_for_a": f"Conveniencia moderada. Ganás {a_gains:.0f}% — el beneficio para vos es limitado. Evaluá si los términos compensan.",
                    "reason_for_b": f"Conveniencia moderada. Ganás {b_gains:.0f}% pero el otro solo gana {a_gains:.0f}%. Podrías necesitar ofrecer incentivos adicionales.",
                    "summary": "Un lado se beneficia claramente más. Funcional con negociación."
                }
        else:
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


# =============================================================================
# LIFESPAN & SERVER INITIALIZATION
# =============================================================================

@asynccontextmanager
async def app_lifespan():
    """Initialize database and engines."""
    db = init_database(DB_PATH)
    evaluator = OriginalityEvaluator(db)
    matcher = MatchingEngine(db)
    reputation = ReputationEngine(db)
    yield {"db": db, "evaluator": evaluator, "matcher": matcher, "reputation": reputation}
    db.close()


mcp = FastMCP("research_match_mcp", lifespan=app_lifespan)


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
        return f '�a Good ({score:.0f}/100, {total_ratings} ratings)"
    elif score >= 40:
        return f"⚠️ Mixed ({score:.0f}/100, {total_ratings} ratings)"
    else:
        return f"🚩 Low ({score:.0f}/100, {total_ratings} ratings)"


# =============================================================================
# MCP TOOLS
# =============================================================================

@mcp.tool(
    name="research_match_register",
    annotations={
        "title": "Register on Research Match",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_register(params: RegisterInput, ctx=None) -> str:
    """Register a new user on Research Match. Creates a pseudonymous profile.
    Email is hashed and never stored in plain text.

    Args:
        params (RegisterInput): Registration data containing:
            - email (str): Email address for identity (hashed)
            - pseudonym (Optional[str]): Preferred display name

    Returns:
        str: JSON with user ID and pseudonym
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
    annotations={
        "title": "Submit Research Commit",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def research_match_submit_commit(params: SubmitCommitInput, ctx=None) -> str:
    """Submit a Research Commit for AI evaluation. The commit is analyzed
    across two axes: Theoretical Originality (OT) and Formal-Computational
    Originality (OFC). Content is hashed for integrity verification.

    NEW in v2: Solidity levels affect score confidence. Declaring honestly
    builds reputation — dishonest declarations will be detected by
    collaborators and penalized through the rating system.

    Args:
        params (SubmitCommitInput): Structured research commit with:
            - Theory Base fields
            - Demonstrations fields
            - Ad Hoc Content fields
            - Cherry-Picking Declared
            - Solidity levels (NEW): per-component or overall

    Returns:
        str: JSON with commit ID, scores, solidity impact, and breakdown
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
    annotations={
        "title": "View My Originality Profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_my_profile(ctx=None) -> str:
    """View your current originality profile, scores, reputation, and commit history.
    Shows OT/OFC scores, solidity levels, reputation from ratings, and teams.

    Returns:
        str: Formatted profile with scores, reputation, breakdowns, and history
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
    annotations={
        "title": "Find Potential Collaborators",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_find_collaborators(params: FindCollaboratorsInput, ctx=None) -> str:
    """Find researchers with complementary skills and knowledge.
    Uses AI-powered matching to identify candidates with high
    complementarity. Shows semaphore, reputation badge, and solidity.

    Args:
        params (FindCollaboratorsInput): Search parameters:
            - limit (int): Max candidates to return (1-20)
            - min_semaphore (str): Filter by minimum semaphore level

    Returns:
        str: JSON array of candidates with scores, semaphores, and reputation
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
    annotations={
        "title": "Send Collaboration Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    }
)
async def research_match_send_request(params: SendRequestInput, ctx=None) -> str:
    """Send a collaboration request to a matched researcher.
    The recipient sees the semaphore and relative scores from their
    perspective, but never your actual content.

    Args:
        params (SendRequestInput): Request data:
            - candidate_user_id (str): Target user ID from find_collaborators
            - message (str): Optional message about what you're looking for

    Returns:
        str: JSON with request status and details
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
    annotations={
        "title": "View Collaboration Requests",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_inbox(ctx=None) -> str:
    """View incoming and outgoing collaboration requests.
    Shows pending, accepted, and rejected requests with semaphore indicators.

    Returns:
        str: JSON with incoming and outgoing requests
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
    annotations={
        "title": "Respond to Collaboration Request",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_respond_request(params: RespondRequestInput, ctx=None) -> str:
    """Accept or reject a collaboration request. If both parties accept,
    a team is created with a shared repository and joint license.

    Args:
        params (RespondRequestInput): Response data:
            - request_id (str): ID of the request to respond to
            - accept (bool): True to accept, False to reject

    Returns:
        str: JSON with response status and team details if accepted
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
    annotations={
        "title": "Rate a Collaborator",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_rate_user(params: RateUserInput, ctx=None) -> str:
    """Rate a collaborator after working together in a team.

    Ratings are ANONYMOUS until both team members have rated each other.
    This prevents retaliation — you can rate honestly without fear.

    Rating dimensions:
    - Honesty (1-5): Did they accurately declare solidity levels?
    - Quality (1-5): Was their work well-structured and valuable?
    - Effort (1-5): Did they contribute meaningfully?

    Low honesty ratings have the biggest impact on reputation.
    The system also detects abusive rating patterns (always 1-star, etc.)

    Args:
        params (RateUserInput): Rating data:
            - team_id: Team where you collaborated
            - rated_user_id: User to rate
            - honesty (1-5): Honesty/transparency rating
            - quality (1-5): Work quality rating
            - effort (1-5): Contribution effort rating
            - comment: Optional private comment

    Returns:
        str: JSON with rating status and whether both have rated
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
    annotations={
        "title": "Analyze Current Work for Research Commit",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def research_match_analyze_work(ctx=None) -> str:
    """Returns the Research Commit template structure so Claude can help
    the user fill it out based on their current work in the conversation.

    v2: Now includes solidity level declaration for each component.

    Returns:
        str: JSON template with instructions for each field
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
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    if "--http" in sys.argv:
        port_idx = sys.argv.index("--http") + 1
        port = int(sys.argv[port_idx]) if port_idx < len(sys.argv) else 8000
        mcp.run(transport="streamable_http", port=port)
    else:
        mcp.run()
