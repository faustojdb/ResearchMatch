"""Tests for MatchingEngine — semaphore calibration and gain calculation."""
import pytest


class TestCalculateGain:
    """Test _calculate_gain() produces expected ranges."""

    def test_complementary_profiles_high_gain(self, matcher):
        """High OFC vs high OT should produce significant gain."""
        # PT-like (low OFC) gains from Maria-like (high OFC)
        gain = matcher._calculate_gain(35, 48, 48, 75)
        assert gain > 20, f"Expected gain > 20 for complementary profiles, got {gain:.1f}"

    def test_similar_profiles_low_gain(self, matcher):
        """Similar profiles should produce low gain."""
        gain = matcher._calculate_gain(50, 50, 52, 48)
        assert gain < 15, f"Expected gain < 15 for similar profiles, got {gain:.1f}"

    def test_weak_gains_from_strong(self, matcher):
        """Weak researcher gains a lot from strong researcher."""
        gain = matcher._calculate_gain(20, 20, 80, 80)
        assert gain > 40, f"Expected gain > 40 for weak-from-strong, got {gain:.1f}"

    def test_strong_gains_little_from_weak(self, matcher):
        """Strong researcher gains little from weak researcher."""
        gain = matcher._calculate_gain(80, 80, 20, 20)
        assert gain < 10, f"Expected gain < 10 for strong-from-weak, got {gain:.1f}"

    def test_gain_capped_at_100(self, matcher):
        """Gain should never exceed 100."""
        gain = matcher._calculate_gain(0, 0, 100, 100)
        assert gain <= 100.0

    def test_zero_gain_when_identical(self, matcher):
        """Identical profiles should have near-zero gain."""
        gain = matcher._calculate_gain(50, 50, 50, 50)
        assert gain < 20, f"Expected low gain for identical profiles, got {gain:.1f}"


class TestCalculateSemaphore:
    """Test _calculate_semaphore() rule ordering and output."""

    def test_green_mutual_both_high(self, matcher):
        """Both gains >= 20 should be GREEN."""
        result = matcher._calculate_semaphore(25, 30)
        assert result["color"] == "green"

    def test_green_complementary(self, matcher):
        """max >= 40, avg >= 20, min >= 4 should be GREEN."""
        result = matcher._calculate_semaphore(50, 5)
        assert result["color"] == "green"

    def test_yellow_high_max_low_min(self, matcher):
        """max >= 25 but min < 4 should be YELLOW."""
        result = matcher._calculate_semaphore(30, 2)
        assert result["color"] == "yellow"

    def test_yellow_moderate_bilateral(self, matcher):
        """avg >= 12, min >= 3 but below GREEN thresholds should be YELLOW."""
        result = matcher._calculate_semaphore(15, 10)
        assert result["color"] == "yellow"

    def test_red_low_gains(self, matcher):
        """Both gains low should be RED."""
        result = matcher._calculate_semaphore(5, 5)
        assert result["color"] == "red"

    def test_red_very_low(self, matcher):
        """Near-zero gains should be RED."""
        result = matcher._calculate_semaphore(1, 1)
        assert result["color"] == "red"

    def test_semaphore_has_required_keys(self, matcher):
        """All semaphore results must have color, reason_for_a, reason_for_b, summary."""
        for a, b in [(50, 50), (30, 2), (5, 5)]:
            result = matcher._calculate_semaphore(a, b)
            assert "color" in result
            assert "reason_for_a" in result
            assert "reason_for_b" in result
            assert "summary" in result
            assert result["color"] in ("green", "yellow", "red")


class TestFindMatches:
    """Integration tests for find_matches with the 4-researcher scenario."""

    def test_pt_maria_is_green(self, matcher, four_researchers):
        """PT ↔ Maria should be GREEN (strong complementarity)."""
        users, _, _ = four_researchers
        matches = matcher.find_matches(users["PT"])
        maria_match = next((m for m in matches if m["candidate_pseudonym"] == "Maria"), None)
        assert maria_match is not None, "Maria not found in matches"
        assert maria_match["semaphore"] == "green", f"Expected GREEN for PT↔Maria, got {maria_match['semaphore']}"

    def test_pt_kenji_is_green(self, matcher, four_researchers):
        """PT ↔ Kenji should be GREEN (complementary theory types)."""
        users, _, _ = four_researchers
        matches = matcher.find_matches(users["PT"])
        kenji_match = next((m for m in matches if m["candidate_pseudonym"] == "Kenji"), None)
        assert kenji_match is not None, "Kenji not found in matches"
        assert kenji_match["semaphore"] == "green", f"Expected GREEN for PT↔Kenji, got {kenji_match['semaphore']}"

    def test_pt_alex_is_not_green(self, matcher, four_researchers):
        """PT ↔ Alex should NOT be GREEN (low complementarity)."""
        users, _, _ = four_researchers
        matches = matcher.find_matches(users["PT"])
        alex_match = next((m for m in matches if m["candidate_pseudonym"] == "Alex"), None)
        assert alex_match is not None, "Alex not found in matches"
        assert alex_match["semaphore"] != "green", f"Expected non-GREEN for PT↔Alex, got {alex_match['semaphore']}"

    def test_matches_sorted_by_complementarity(self, matcher, four_researchers):
        """Matches should be sorted by complementarity_score descending."""
        users, _, _ = four_researchers
        matches = matcher.find_matches(users["PT"])
        scores = [m["complementarity_score"] for m in matches]
        assert scores == sorted(scores, reverse=True)

    def test_no_self_match(self, matcher, four_researchers):
        """User should never appear in their own matches."""
        users, _, _ = four_researchers
        matches = matcher.find_matches(users["PT"])
        for m in matches:
            assert m["candidate_user_id"] != users["PT"]

    def test_gain_values_reasonable(self, matcher, four_researchers):
        """All gain values should be between 0 and 100."""
        users, _, _ = four_researchers
        matches = matcher.find_matches(users["PT"])
        for m in matches:
            assert 0 <= m["a_gains_from_b"] <= 100
            assert 0 <= m["b_gains_from_a"] <= 100
