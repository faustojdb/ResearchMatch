"""
Offline unit tests for the pure/self-contained engines.

These tests DO NOT require the Firestore emulator or any network access:
- They use an in-memory SQLite database (`init_database(":memory:")`).
- The embedding engine is forced into its Jaccard fallback (`_load_failed = True`)
  so no ~90MB sentence-transformers model is ever downloaded.
- The evaluator is given `literature=None` so OpenAlex is never called.

Run standalone with:
    RESEARCH_MATCH_DISABLE_OPENALEX=1 pytest tests/test_engines.py -q
"""

from __future__ import annotations

import pytest

from src.research_match_server import (
    OriginalityEvaluator,
    EmbeddingEngine,
    ReputationEngine,
    init_database,
    _get_current_user,
    NEUTRAL_NOVELTY_SCORE,
    NEUTRAL_DIVERGENCE_SCORE,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _insert_user(db, uid: str, pseudonym: str, email_hash: str) -> None:
    db.execute(
        "INSERT INTO users (id, pseudonym, email_hash) VALUES (?, ?, ?)",
        (uid, pseudonym, email_hash),
    )
    db.commit()


def _jaccard_embeddings() -> EmbeddingEngine:
    """An EmbeddingEngine pinned to the fast, offline Jaccard fallback."""
    eng = EmbeddingEngine()
    eng._load_failed = True  # force Jaccard; never load / download a model
    return eng


@pytest.fixture
def db():
    conn = init_database(":memory:")
    try:
        yield conn
    finally:
        conn.close()


def _commit(**overrides):
    """A minimal, valid commit_data dict for the evaluator."""
    base = {
        "domain": "computer_science",
        "subdomain": "machine_learning",
        "problem": "Detecting anomalies in streaming sensor data efficiently.",
        "hypothesis": "A sparse online autoencoder detects anomalies with less memory.",
        "theoretical_framework": "Online learning with sparse coding.",
        "adhoc_summary": "",
        "adhoc_connections": [],
        "demo_types": [],
        "code_languages": [],
        "solidity_levels": {},
        "overall_solidity": "speculative",
    }
    base.update(overrides)
    return base


# =====================================================================
# _get_current_user — fail-closed identity resolution
# =====================================================================

class TestGetCurrentUserFailClosed:
    async def test_single_user_no_hash_returns_that_user(self, db):
        """(a) SQLite with exactly one user + no hash → that user."""
        _insert_user(db, "u1", "p1", "h1")
        user = await _get_current_user(db, datastore=None, user_email_hash="")
        assert user is not None
        assert user["id"] == "u1"

    async def test_two_users_no_hash_returns_none(self, db):
        """(b) Two users + no hash → None (refuses to guess)."""
        _insert_user(db, "u1", "p1", "h1")
        _insert_user(db, "u2", "p2", "h2")
        user = await _get_current_user(db, datastore=None, user_email_hash="")
        assert user is None

    async def test_unknown_email_hash_returns_none(self, db):
        """(c) Unknown email hash → None."""
        _insert_user(db, "u1", "p1", "h1")
        user = await _get_current_user(db, datastore=None, user_email_hash="does-not-exist")
        assert user is None

    async def test_matching_email_hash_returns_user(self, db):
        """(d) Matching email hash → that specific user (even with several users)."""
        _insert_user(db, "u1", "p1", "h1")
        _insert_user(db, "u2", "p2", "h2")
        user = await _get_current_user(db, datastore=None, user_email_hash="h2")
        assert user is not None
        assert user["id"] == "u2"

    async def test_empty_db_no_hash_returns_none(self, db):
        """Zero users + no hash → None (no fallback account)."""
        user = await _get_current_user(db, datastore=None, user_email_hash="")
        assert user is None


# =====================================================================
# OriginalityEvaluator — neutral fallback when no reference corpus
# =====================================================================

class TestOriginalityNeutralFallback:
    async def test_no_reference_yields_neutral_scores(self, db):
        """literature=None + empty DB → honest neutral novelty/divergence."""
        _insert_user(db, "u1", "p1", "h1")
        evaluator = OriginalityEvaluator(
            db=db, embeddings=_jaccard_embeddings(), literature=None
        )
        result = await evaluator.evaluate_commit(_commit(), user_id="u1")

        assert result["novelty_grounding"] == "none"
        assert result["reference_works"] == 0
        assert result["ot_breakdown"]["hypothesis_novelty"] == NEUTRAL_NOVELTY_SCORE == 55.0
        assert result["ot_breakdown"]["corpus_divergence"] == NEUTRAL_DIVERGENCE_SCORE == 50.0

        # Transparency keys must always be present.
        assert "scoring_version" in result
        assert result["similarity_method"] == "jaccard-fallback"

    async def test_grounding_via_local_corpus(self, db):
        """A second user's commit in the same domain grounds novelty in the corpus.

        With a real reference in `research_commits`, novelty is COMPUTED (not the
        neutral constant) and the grounding is reported as coming from the corpus.
        """
        _insert_user(db, "u1", "p1", "h1")
        _insert_user(db, "u2", "p2", "h2")
        # A prior work by a DIFFERENT user, same domain/subdomain, overlapping wording.
        db.execute(
            """
            INSERT INTO research_commits
                (id, user_id, domain, subdomain, problem, hypothesis,
                 theoretical_framework, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "c_other", "u2", "computer_science", "machine_learning",
                "Detecting anomalies in streaming sensor data efficiently.",
                "A sparse online autoencoder detects anomalies with less memory.",
                "Online learning with sparse coding.",
                "hash_other",
            ),
        )
        db.commit()

        evaluator = OriginalityEvaluator(
            db=db, embeddings=_jaccard_embeddings(), literature=None
        )
        result = await evaluator.evaluate_commit(_commit(), user_id="u1")

        assert "corpus" in result["novelty_grounding"]
        assert result["reference_works"] >= 1
        # Because a near-identical prior work exists, novelty must be LOW and clearly
        # different from the neutral fallback constant.
        assert result["ot_breakdown"]["hypothesis_novelty"] != NEUTRAL_NOVELTY_SCORE
        assert result["ot_breakdown"]["hypothesis_novelty"] < 55.0

    def test_evaluate_theoretical_uses_grounded_similarity(self, db):
        """Direct unit test of the scoring math with a supplied novelty context.

        nearest=0.8 → hypothesis_novelty ≈ 100 - 80 = 20
        avg=0.6     → corpus_divergence  ≈ 100 - 60 = 40
        """
        evaluator = OriginalityEvaluator(
            db=db, embeddings=_jaccard_embeddings(), literature=None
        )
        breakdown = evaluator._evaluate_theoretical(
            _commit(),
            [],
            {"has_reference": True, "nearest": 0.8, "avg": 0.6},
        )
        assert breakdown["hypothesis_novelty"] == pytest.approx(20.0, abs=0.5)
        assert breakdown["corpus_divergence"] == pytest.approx(40.0, abs=0.5)


# =====================================================================
# ReputationEngine — regression: sqlite3.Row.get() no longer crashes
# =====================================================================

class TestReputationEngine:
    async def test_apply_new_rating_does_not_raise(self, db):
        """A single SQLite user with no prior ratings must not crash the update.

        Regression for the sqlite3.Row.get() bug: the row is now normalised to a
        plain dict before `.get()` is called.
        """
        _insert_user(db, "u1", "p1", "h1")
        re = ReputationEngine(db=db)
        # Should complete without raising (falls back to batch recalculation → zeros).
        await re.apply_new_rating("u1", honesty=5, quality=4, effort=3)

        row = db.execute(
            "SELECT running_honesty, running_quality, running_effort FROM users WHERE id = 'u1'"
        ).fetchone()
        # Values were written (no ratings → 0.0), and the call returned cleanly.
        assert row is not None
        assert row["running_honesty"] is not None


# =====================================================================
# EmbeddingEngine.rank_similarity — Jaccard mode
# =====================================================================

class TestEmbeddingEngineJaccard:
    def test_rank_similarity_basic(self):
        eng = _jaccard_embeddings()
        candidates = [
            "machine learning models for anomaly detection",
            "deep learning for images",
            "a completely unrelated topic about cooking",
        ]
        ranked = eng.rank_similarity("machine learning anomaly detection", candidates)
        assert ranked["n"] == len(candidates)
        assert ranked["max"] >= ranked["avg"]
        assert 0.0 <= ranked["avg"] <= ranked["max"] <= 1.0
        assert ranked["max"] > 0.0  # there is real word overlap

    def test_rank_similarity_empty(self):
        eng = _jaccard_embeddings()
        assert eng.rank_similarity("", []) == {"max": 0.0, "avg": 0.0, "n": 0}
        # Empty candidate list short-circuits regardless of the query.
        assert eng.rank_similarity("some query", []) == {"max": 0.0, "avg": 0.0, "n": 0}
        # Empty query short-circuits regardless of candidates.
        assert eng.rank_similarity("", ["a candidate"]) == {"max": 0.0, "avg": 0.0, "n": 0}

    def test_similarity_symmetry_and_bounds(self):
        eng = _jaccard_embeddings()
        s = eng.similarity("shared words here", "shared words there")
        assert 0.0 <= s <= 1.0
        # Identical text → maximal Jaccard.
        assert eng.similarity("same text", "same text") == pytest.approx(1.0)
        # Empty input → 0.0.
        assert eng.similarity("", "anything") == 0.0
