"""Tests for EmbeddingEngine — Jaccard fallback and edge cases."""
import pytest


class TestJaccardFallback:
    """Test Jaccard similarity (the deterministic fallback)."""

    def test_identical_text(self, embeddings):
        """Identical texts should have similarity 1.0."""
        sim = embeddings.similarity("protein folding prediction", "protein folding prediction")
        assert sim == 1.0

    def test_completely_different(self, embeddings):
        """Completely different texts should have similarity 0.0."""
        sim = embeddings.similarity("quantum gravity black holes", "cooking recipes pasta sauce")
        assert sim == 0.0

    def test_partial_overlap(self, embeddings):
        """Partially overlapping texts should have 0 < sim < 1."""
        sim = embeddings.similarity("protein folding prediction", "protein structure analysis")
        assert 0.0 < sim < 1.0

    def test_empty_text(self, embeddings):
        """Empty text should return 0.0."""
        assert embeddings.similarity("", "some text") == 0.0
        assert embeddings.similarity("some text", "") == 0.0
        assert embeddings.similarity("", "") == 0.0

    def test_method_is_jaccard(self, embeddings):
        """Forced fallback should report jaccard method."""
        assert embeddings.method == "jaccard-fallback"

    def test_is_not_loaded(self, embeddings):
        """Forced fallback should not have model loaded."""
        assert embeddings.is_loaded is False

    def test_symmetry(self, embeddings):
        """Similarity should be symmetric."""
        a = "molecular dynamics simulation"
        b = "protein dynamics molecular"
        assert embeddings.similarity(a, b) == embeddings.similarity(b, a)
