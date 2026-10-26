"""
Offline tests for how the tools behave while the embedding model is still loading.

A cold start loads the model in 40-60 s, longer than an MCP client waits for one request
(it then gives up and restarts the server). The engine therefore raises
``EmbeddingsWarmingUp`` instead of blocking, and the tools must turn that into a clear
``warming_up`` answer without persisting anything scored without embeddings.

No network, no model, no database: everything the tools touch is stubbed.

Run standalone with:
    pytest tests/test_warming_up_tools.py -q
"""

from __future__ import annotations

import asyncio
import io
import json
import urllib.request

import pytest

import src.research_match_server as server
from src.research_match_server import (
    DeepSearchInput,
    EmbeddingsWarmingUp,
    OriginalityEvaluator,
    _log_tool_call,
)


class _WarmingEngine:
    """Stands in for an EmbeddingEngine whose model has not finished loading."""

    method = "jaccard-fallback"

    def __init__(self, retry_after: int = 25):
        self.retry_after = retry_after
        self.calls = 0

    def rank_similarity(self, query, candidates):
        self.calls += 1
        raise EmbeddingsWarmingUp(self.retry_after)

    def similarity(self, a, b):
        self.calls += 1
        raise EmbeddingsWarmingUp(self.retry_after)


# =====================================================================
# The decorator every tool goes through
# =====================================================================

class TestLogToolCallDecorator:
    def test_warming_up_becomes_a_structured_answer(self):
        @_log_tool_call
        async def research_match_fake(params=None, ctx=None):
            raise EmbeddingsWarmingUp(25)

        payload = json.loads(asyncio.run(research_match_fake()))
        assert payload["status"] == "warming_up"
        assert payload["retry_after_seconds"] == 25
        assert "Nothing was saved" in payload["message"]

    def test_other_errors_still_propagate(self):
        @_log_tool_call
        async def research_match_fake(params=None, ctx=None):
            raise ValueError("boom")

        with pytest.raises(ValueError):
            asyncio.run(research_match_fake())


# =====================================================================
# Scoring and matching propagate the signal instead of swallowing it
# =====================================================================

class TestScoringPropagatesWarmingUp:
    def test_novelty_context_raises_when_the_model_is_loading(self):
        engine = _WarmingEngine()
        evaluator = OriginalityEvaluator(db=None, embeddings=engine)
        commit = {"domain": "ml", "problem": "sparse online autoencoders", "hypothesis": "h"}
        corpus = [{"problem": "dense offline autoencoders", "hypothesis": "g"}]
        with pytest.raises(EmbeddingsWarmingUp):
            asyncio.run(evaluator._build_novelty_context(commit, corpus))
        assert engine.calls == 1

    def test_no_reference_material_never_needs_the_model(self):
        engine = _WarmingEngine()
        evaluator = OriginalityEvaluator(db=None, embeddings=engine)
        ctx = asyncio.run(evaluator._build_novelty_context({"domain": "ml", "problem": "x y z"}, []))
        assert ctx["has_reference"] is False
        assert engine.calls == 0


# =====================================================================
# deep_search keeps the repository metadata when scoring is not ready
# =====================================================================

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_github(url, *args, **kwargs):
    """Minimal GitHub REST stand-in keyed on the endpoint suffix."""
    u = url.full_url if hasattr(url, "full_url") else str(url)
    payloads = {
        "/languages": {"Python": 1000},
        "/commits?per_page=5": [],
        "/git/trees/main": {"tree": [{"path": "README.md", "type": "blob", "size": 12}]},
        "/readme": {},
    }
    suffix = u.split("/repos/o/r", 1)[-1]
    if suffix == "":
        body = {"full_name": "o/r", "size": 2048, "default_branch": "main", "description": "a repo",
                "topics": ["ml"], "language": "Python", "stargazers_count": 3}
    elif suffix in payloads:
        body = payloads[suffix]
    else:
        raise OSError("not found")  # dependency files etc.: _gh_api swallows it and returns None
    return _FakeResponse(json.dumps(body).encode())


class _EvaluatorStub:
    def __init__(self, error: Exception):
        self.error = error

    async def evaluate_commit(self, commit_data, user_id):
        raise self.error


class TestDeepSearchWhileWarming:
    def _run(self, monkeypatch, evaluator):
        monkeypatch.setattr(urllib.request, "urlopen", _fake_github)
        monkeypatch.setattr(server, "_get_evaluator", lambda ctx: evaluator)
        params = DeepSearchInput(repo_url="https://github.com/o/r", include_scoring=True)
        return json.loads(asyncio.run(server.research_match_deep_search(params, ctx=None)))

    def test_metadata_is_kept_and_scoring_reports_warming_up(self, monkeypatch):
        result = self._run(monkeypatch, _EvaluatorStub(EmbeddingsWarmingUp(20)))
        assert result["status"] == "ok"
        assert result["layers_executed"]["scoring"] is False
        assert result["analysis"]["repo"]["name"] == "o/r"
        assert result["analysis"]["languages"] == {"Python": 1000}
        assert result["originality"]["status"] == "warming_up"
        assert result["originality"]["retry_after_seconds"] == 20
        assert "metadata is included" in result["originality"]["message"]

    def test_other_scoring_errors_are_still_reported_as_unavailable(self, monkeypatch):
        result = self._run(monkeypatch, _EvaluatorStub(RuntimeError("scoring is down")))
        assert result["layers_executed"]["scoring"] is False
        assert "scoring unavailable" in result["originality"]["error"]
        assert result["analysis"]["repo"]["name"] == "o/r"
