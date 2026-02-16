"""Tests for ReputationEngine — ratings, reputation, and abuse detection."""
import uuid
import pytest


def _create_team_with_ratings(db, reputation, user_a, user_b, ratings_a_to_b, ratings_b_to_a):
    """Helper: create a team and mutual ratings."""
    team_id = str(uuid.uuid4())
    db.execute("INSERT INTO teams (id, name) VALUES (?, ?)", (team_id, f"team-{team_id[:6]}"))
    db.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')", (team_id, user_a))
    db.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')", (team_id, user_b))

    h, q, e = ratings_a_to_b
    db.execute("""
        INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), team_id, user_a, user_b, h, q, e))

    h, q, e = ratings_b_to_a
    db.execute("""
        INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (str(uuid.uuid4()), team_id, user_b, user_a, h, q, e))

    db.commit()
    reputation.reveal_ratings(team_id)
    return team_id


class TestCalculateReputation:
    """Test calculate_reputation() logic."""

    def test_insufficient_ratings(self, db, reputation):
        """Users with < MIN_RATINGS ratings should get default 100."""
        from research_match_server import _get_or_create_user
        uid = _get_or_create_user(db, "new@test.com", "newbie")
        rep = reputation.calculate_reputation(uid)
        assert rep["reputation_score"] == 100.0
        assert rep["status"] == "insufficient_data"

    def test_perfect_ratings(self, db, reputation):
        """Perfect 5/5/5 ratings should produce high reputation."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "a@test.com", "user_a")
        user_b = _get_or_create_user(db, "b@test.com", "user_b")
        user_c = _get_or_create_user(db, "c@test.com", "user_c")

        _create_team_with_ratings(db, reputation, user_a, user_b, (5, 5, 5), (5, 5, 5))
        _create_team_with_ratings(db, reputation, user_a, user_c, (5, 5, 5), (5, 5, 5))

        rep = reputation.calculate_reputation(user_a)
        assert rep["reputation_score"] >= 95.0
        assert rep["status"] == "calculated"

    def test_low_honesty_penalty(self, db, reputation):
        """Very low honesty should trigger harsh penalty."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "dishonest@test.com", "dishonest")
        user_b = _get_or_create_user(db, "b2@test.com", "user_b2")
        user_c = _get_or_create_user(db, "c2@test.com", "user_c2")

        _create_team_with_ratings(db, reputation, user_b, user_a, (1, 3, 3), (3, 3, 3))
        _create_team_with_ratings(db, reputation, user_c, user_a, (1, 3, 3), (3, 3, 3))

        rep = reputation.calculate_reputation(user_a)
        assert rep["reputation_score"] < 50.0, f"Expected < 50 for low honesty, got {rep['reputation_score']}"

    def test_reputation_score_range(self, db, reputation):
        """Reputation should always be between 0 and 100."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "range@test.com", "range_user")
        user_b = _get_or_create_user(db, "range2@test.com", "range_user2")
        user_c = _get_or_create_user(db, "range3@test.com", "range_user3")

        _create_team_with_ratings(db, reputation, user_b, user_a, (3, 3, 3), (3, 3, 3))
        _create_team_with_ratings(db, reputation, user_c, user_a, (4, 4, 4), (4, 4, 4))

        rep = reputation.calculate_reputation(user_a)
        assert 0 <= rep["reputation_score"] <= 100


class TestCheckBothRated:
    """Test check_both_rated() logic."""

    def test_only_one_rated(self, db, reputation):
        """Should return False when only one side has rated."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "one@test.com", "one_rater")
        user_b = _get_or_create_user(db, "two@test.com", "two_rater")

        team_id = str(uuid.uuid4())
        db.execute("INSERT INTO teams (id, name) VALUES (?, ?)", (team_id, "test-team"))
        db.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')", (team_id, user_a))
        db.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')", (team_id, user_b))
        db.execute("""
            INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort)
            VALUES (?, ?, ?, ?, 4, 4, 4)
        """, (str(uuid.uuid4()), team_id, user_a, user_b))
        db.commit()

        assert reputation.check_both_rated(team_id, user_a, user_b) is False


class TestExponentialSmoothing:
    """Test apply_new_rating() and _batch_recalculate()."""

    def test_apply_new_rating_initializes(self, db, reputation):
        """First apply_new_rating should initialize from batch."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "es_a@test.com", "es_a")
        user_b = _get_or_create_user(db, "es_b@test.com", "es_b")
        user_c = _get_or_create_user(db, "es_c@test.com", "es_c")

        _create_team_with_ratings(db, reputation, user_b, user_a, (4, 4, 4), (4, 4, 4))
        _create_team_with_ratings(db, reputation, user_c, user_a, (5, 5, 5), (5, 5, 5))

        reputation.apply_new_rating(user_a, 3, 3, 3)
        user = db.execute("SELECT running_honesty FROM users WHERE id = ?", (user_a,)).fetchone()
        assert user["running_honesty"] is not None

    def test_running_averages_used_after_batch(self, db, reputation):
        """After batch recalculate, running averages should be set."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "ra_a@test.com", "ra_a")
        user_b = _get_or_create_user(db, "ra_b@test.com", "ra_b")
        user_c = _get_or_create_user(db, "ra_c@test.com", "ra_c")

        _create_team_with_ratings(db, reputation, user_b, user_a, (5, 5, 5), (5, 5, 5))
        _create_team_with_ratings(db, reputation, user_c, user_a, (5, 5, 5), (5, 5, 5))

        rep = reputation.calculate_reputation(user_a)
        assert rep["status"] == "calculated"
        user = db.execute("SELECT running_honesty FROM users WHERE id = ?", (user_a,)).fetchone()
        assert user["running_honesty"] is not None

    def test_smoothing_weights_recent_more(self, db, reputation):
        """After applying a low rating, running avg should decrease."""
        from research_match_server import _get_or_create_user
        user_a = _get_or_create_user(db, "sw_a@test.com", "sw_a")
        user_b = _get_or_create_user(db, "sw_b@test.com", "sw_b")
        user_c = _get_or_create_user(db, "sw_c@test.com", "sw_c")

        _create_team_with_ratings(db, reputation, user_b, user_a, (5, 5, 5), (5, 5, 5))
        _create_team_with_ratings(db, reputation, user_c, user_a, (5, 5, 5), (5, 5, 5))

        reputation.apply_new_rating(user_a, 5, 5, 5)
        before = db.execute("SELECT running_honesty FROM users WHERE id = ?", (user_a,)).fetchone()["running_honesty"]

        reputation.apply_new_rating(user_a, 1, 1, 1)
        after = db.execute("SELECT running_honesty FROM users WHERE id = ?", (user_a,)).fetchone()["running_honesty"]

        assert after < before, f"Expected decrease after low rating: {before} -> {after}"


class TestAbuseDetection:
    """Test detect_abuse_patterns()."""

    def test_no_abuse_few_ratings(self, db, reputation):
        """Should not flag abuse with fewer than 3 ratings."""
        from research_match_server import _get_or_create_user
        uid = _get_or_create_user(db, "few@test.com", "few_rater")
        result = reputation.detect_abuse_patterns(uid)
        assert result["abuse_detected"] is False

    def test_vindictive_pattern(self, db, reputation):
        """All 1-star honesty ratings should be flagged."""
        from research_match_server import _get_or_create_user
        rater = _get_or_create_user(db, "vind@test.com", "vindictive")

        for i in range(5):
            rated = _get_or_create_user(db, f"victim{i}@test.com", f"victim{i}")
            team_id = str(uuid.uuid4())
            db.execute("INSERT INTO teams (id, name) VALUES (?, ?)", (team_id, f"team-{i}"))
            db.execute("""
                INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort)
                VALUES (?, ?, ?, ?, 1, 1, 1)
            """, (str(uuid.uuid4()), team_id, rater, rated))
        db.commit()

        result = reputation.detect_abuse_patterns(rater)
        assert result["abuse_detected"] is True
        assert "vindictive_pattern" in result["flags"]
