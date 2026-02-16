"""Tests for OriginalityEvaluator — scoring and solidity multipliers."""
import pytest
from tests.conftest import COMMIT_PT, COMMIT_MARIA, COMMIT_KENJI, COMMIT_ALEX


class TestEvaluateCommit:
    """Test evaluate_commit() produces reasonable scores."""

    def test_scores_in_range(self, evaluator, db):
        from research_match_server import _get_or_create_user
        user_id = _get_or_create_user(db, "test@test.com", "tester")
        scores = evaluator.evaluate_commit(COMMIT_PT, user_id)
        assert 0 <= scores["ot_score"] <= 100
        assert 0 <= scores["ofc_score"] <= 100

    def test_functional_solidity_higher_than_cherry_picked(self, evaluator, db):
        """Functional solidity should produce higher scores than cherry_picked."""
        from research_match_server import _get_or_create_user
        uid = _get_or_create_user(db, "sol@test.com", "sol_tester")
        scores_maria = evaluator.evaluate_commit(COMMIT_MARIA, uid)
        scores_alex = evaluator.evaluate_commit(COMMIT_ALEX, uid)
        # Maria (functional) should generally score higher than Alex (cherry_picked)
        assert scores_maria["ofc_score"] > scores_alex["ofc_score"]

    def test_rich_adhoc_higher_ot(self, evaluator, db):
        """Commits with rich ad hoc content should score higher OT."""
        from research_match_server import _get_or_create_user
        uid = _get_or_create_user(db, "adhoc@test.com", "adhoc_tester")
        scores_kenji = evaluator.evaluate_commit(COMMIT_KENJI, uid)
        scores_alex = evaluator.evaluate_commit(COMMIT_ALEX, uid)
        assert scores_kenji["ot_score"] > scores_alex["ot_score"]

    def test_breakdown_keys_present(self, evaluator, db):
        """Score breakdowns should contain all expected keys."""
        from research_match_server import _get_or_create_user
        uid = _get_or_create_user(db, "keys@test.com", "key_tester")
        scores = evaluator.evaluate_commit(COMMIT_PT, uid)
        ot_keys = {"hypothesis_novelty", "interdisciplinary_connections", "adhoc_content", "corpus_divergence"}
        ofc_keys = {"formal_method_originality", "code_quality", "validation_power", "technical_sophistication", "coverage"}
        assert set(scores["ot_breakdown"].keys()) == ot_keys
        assert set(scores["ofc_breakdown"].keys()) == ofc_keys

    def test_solidity_impact_present(self, evaluator, db):
        """Solidity impact should be included in results."""
        from research_match_server import _get_or_create_user
        uid = _get_or_create_user(db, "impact@test.com", "impact_tester")
        scores = evaluator.evaluate_commit(COMMIT_PT, uid)
        assert "solidity_impact" in scores
        assert "ot_multiplier" in scores["solidity_impact"]
        assert "ofc_multiplier" in scores["solidity_impact"]


class TestSolidityMultipliers:
    """Test _apply_solidity() applies correct multipliers."""

    def test_proven_multiplier_is_highest(self, evaluator):
        result = evaluator._apply_solidity(
            80.0, 80.0,
            {"theory": "proven", "demos": "proven", "adhoc": "proven", "cherry_picking": "cherry_picked"},
            "proven"
        )
        assert result["ot_multiplier"] > 0.8

    def test_cherry_picked_multiplier_is_lowest(self, evaluator):
        result = evaluator._apply_solidity(
            80.0, 80.0,
            {"theory": "cherry_picked", "demos": "cherry_picked", "adhoc": "cherry_picked", "cherry_picking": "cherry_picked"},
            "cherry_picked"
        )
        assert result["ot_multiplier"] < 0.5

    def test_adjusted_scores_less_than_raw(self, evaluator):
        """Adjusted scores should be <= raw scores (multipliers are <= 1.0)."""
        result = evaluator._apply_solidity(
            80.0, 80.0,
            {"theory": "speculative", "demos": "functional"},
            "speculative"
        )
        assert result["adjusted_ot"] <= 80.0
        assert result["adjusted_ofc"] <= 80.0
