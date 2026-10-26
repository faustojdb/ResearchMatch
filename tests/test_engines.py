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
    MatchingEngine,
    ReputationEngine,
    init_database,
    _get_current_user,
    NEUTRAL_NOVELTY_SCORE,
    NEUTRAL_DIVERGENCE_SCORE,
    PEER_GREEN_FLOOR,
    PEER_YELLOW_FLOOR,
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


# =====================================================================
# MatchingEngine — bilateral semaphore, including the peer-match rules
# =====================================================================

def _match_commit(uid: str, ot: float | None, ofc: float | None, **overrides):
    """A commit row as `_calculate_match` sees it (same domain → base similarity >= 40)."""
    base = {
        "user_id": uid,
        "pseudonym": f"p-{uid}",
        "domain": "computer_science",
        "subdomain": "machine_learning",
        "problem": "Detecting anomalies in streaming sensor data efficiently.",
        "ot_score": ot,
        "ofc_score": ofc,
        "overall_solidity": "functional",
    }
    base.update(overrides)
    return base


class TestMatchingSemaphore:
    """`_calculate_gain` rewards the OTHER side's strength in MY weakness, so similar
    profiles always gain ~0 by complementarity. Rules 5-6 of `_calculate_semaphore`
    must separate strong similar pairs (peers) from weak similar pairs (RED)."""

    def _engine(self):
        return MatchingEngine(db=None, embeddings=_jaccard_embeddings())

    def _semaphore(self, a_ot, a_ofc, b_ot, b_ofc):
        eng = self._engine()
        m = eng._calculate_match(_match_commit("a", a_ot, a_ofc), _match_commit("b", b_ot, b_ofc))
        assert m is not None, "same domain/problem must pass the base-similarity gate"
        return m

    def test_complementary_pair_is_green_mutual(self):
        """A strong theorist + a strong engineer: each covers the other's weakness."""
        m = self._semaphore(85, 30, 30, 85)
        assert m["semaphore"] == "green"
        assert m["semaphore_rule"] == "green_mutual"
        assert m["a_gains_from_b"] >= 20 and m["b_gains_from_a"] >= 20

    def test_strong_similar_pair_is_a_peer_match_not_red(self):
        """ROADMAP Stage 1: two equally strong profiles used to fall through to RED."""
        m = self._semaphore(80, 75, 80, 75)
        assert m["semaphore"] == "green"
        assert m["semaphore_rule"] == "green_peer"
        assert m["peer_strength"] == 75
        # The reason must be honest about the low complementarity numbers.
        assert "Par fuerte" in m["semaphore_reason"]
        assert m["a_gains_from_b"] < 20  # complementarity really is low here

    def test_solid_similar_pair_is_yellow_peer(self):
        """Both above the YELLOW floor but below the GREEN floor on one axis."""
        m = self._semaphore(72, 66, 70, 68)
        assert m["semaphore"] == "yellow"
        assert m["semaphore_rule"] == "yellow_peer"
        assert PEER_YELLOW_FLOOR <= m["peer_strength"] < PEER_GREEN_FLOOR

    def test_shared_strength_one_axis_is_yellow_peer(self):
        """Two strong theorists who are both weak-ish on OFC: a peer, not a RED."""
        m = self._semaphore(90, 55, 88, 58)
        assert m["semaphore"] == "yellow"
        assert m["semaphore_rule"] == "yellow_peer"
        assert "OFC" in m["semaphore_reason"]  # names the uncovered weakness

    def test_weak_similar_pair_stays_red(self):
        """Similar AND weak: nobody gains and there is no shared strength → RED."""
        m = self._semaphore(25, 20, 25, 20)
        assert m["semaphore"] == "red"
        assert m["semaphore_rule"] == "red"

    def test_missing_scores_default_to_50_and_stay_red(self):
        """Commits without scores default to 50/50; the peer floors must not fire on defaults."""
        m = self._semaphore(None, None, None, None)
        assert m["semaphore"] == "red"
        assert m["peer_strength"] == 50

    def test_asymmetric_pair_is_yellow(self):
        """One side gains a lot, the other almost nothing → YELLOW asimétrico."""
        m = self._semaphore(40, 40, 85, 80)
        assert m["semaphore"] == "yellow"
        assert m["semaphore_rule"] == "yellow_asymmetric"
        assert m["a_gains_from_b"] > m["b_gains_from_a"]

    def test_complementarity_rules_win_over_peer_rules(self):
        """Strong peers with a real complementarity gap are still ranked by that gap."""
        m = self._semaphore(70, 70, 95, 95)
        # Both >= 70 on both axes, but B gains ~1% from A: asymmetric YELLOW, not green_peer.
        assert m["semaphore"] == "yellow"
        assert m["semaphore_rule"] == "yellow_asymmetric"

    def test_semaphore_is_symmetric(self):
        eng = self._engine()
        for a, b in [((80, 75), (80, 75)), ((85, 30), (30, 85)), ((40, 40), (85, 80)), ((90, 55), (88, 58))]:
            ab = eng._calculate_match(_match_commit("a", *a), _match_commit("b", *b))
            ba = eng._calculate_match(_match_commit("b", *b), _match_commit("a", *a))
            assert ab["semaphore"] == ba["semaphore"]
            assert ab["semaphore_rule"] == ba["semaphore_rule"]
            assert ab["a_gains_from_b"] == ba["b_gains_from_a"]

    def test_semaphore_without_shared_strengths_keeps_old_behaviour(self):
        """Callers that pass only gains (defaults 0) never trigger the peer rules."""
        eng = self._engine()
        assert eng._calculate_semaphore(5.0, 5.0)["rule"] == "red"
        assert eng._calculate_semaphore(30.0, 30.0)["rule"] == "green_mutual"


# =====================================================================
# _resolve_db_path — host defaults and unexpanded placeholders
# =====================================================================

class TestResolveDbPath:
    def test_primary_wins(self, monkeypatch):
        from src import research_match_server as s
        monkeypatch.setenv("RESEARCH_MATCH_DB", "C:/data/primary.db")
        monkeypatch.setenv("RESEARCH_MATCH_DB_DEFAULT", "C:/data/default.db")
        assert s._resolve_db_path() == "C:/data/primary.db"

    def test_unexpanded_primary_falls_to_host_default(self, monkeypatch):
        from src import research_match_server as s
        monkeypatch.setenv("RESEARCH_MATCH_DB", "${user_config.database_path}")
        monkeypatch.setenv("RESEARCH_MATCH_DB_DEFAULT", "C:/data/default.db")
        assert s._resolve_db_path() == "C:/data/default.db"

    def test_empty_everything_is_relative(self, monkeypatch):
        from src import research_match_server as s
        monkeypatch.setenv("RESEARCH_MATCH_DB", "")
        monkeypatch.setenv("RESEARCH_MATCH_DB_DEFAULT", "")
        assert s._resolve_db_path() == "research_match.db"

    def test_unset_everything_is_relative(self, monkeypatch):
        from src import research_match_server as s
        monkeypatch.delenv("RESEARCH_MATCH_DB", raising=False)
        monkeypatch.delenv("RESEARCH_MATCH_DB_DEFAULT", raising=False)
        assert s._resolve_db_path() == "research_match.db"

    def test_unexpanded_placeholders_fall_to_the_home_folder(self, monkeypatch):
        """The Claude Desktop plugin bridge leaves ${CLAUDE_PLUGIN_DATA} as is: never use the plugin folder."""
        import os
        from src import research_match_server as s
        expected = os.path.join(os.path.expanduser("~"), ".research-match", "research_match.db")
        monkeypatch.setenv("RESEARCH_MATCH_DB", "${CLAUDE_PLUGIN_DATA}/research_match.db")
        monkeypatch.delenv("RESEARCH_MATCH_DB_DEFAULT", raising=False)
        assert s._resolve_db_path() == expected
        monkeypatch.setenv("RESEARCH_MATCH_DB", "")
        monkeypatch.setenv("RESEARCH_MATCH_DB_DEFAULT", "${HOME}/never-expanded.db")
        assert s._resolve_db_path() == expected

    def test_expanded_value_still_beats_an_unexpanded_one(self, monkeypatch):
        from src import research_match_server as s
        monkeypatch.setenv("RESEARCH_MATCH_DB", "${CLAUDE_PLUGIN_DATA}/research_match.db")
        monkeypatch.setenv("RESEARCH_MATCH_DB_DEFAULT", "C:/data/default.db")
        assert s._resolve_db_path() == "C:/data/default.db"
