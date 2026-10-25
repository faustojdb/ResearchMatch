"""
Offline tests for the embedding worker process and its client (EmbeddingEngine).

They use the worker's built-in ``__test__`` backend (deterministic hashed bag-of-words
vectors), so no model is downloaded and torch is never imported. What they cover:

- the JSON-lines protocol of ``src/embedding_worker.py`` itself;
- the client starting the worker lazily, answering similarity / rank requests, and
  reporting which backend produced the numbers;
- graceful degradation to Jaccard when the worker cannot start, is too slow to become
  ready, or dies mid-flight;
- idle shutdown and transparent restart.

Run standalone with:
    pytest tests/test_embedding_worker.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from src.research_match_server import EmbeddingEngine

WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "embedding_worker.py")


def _engine(model: str = "__test__", **kw) -> EmbeddingEngine:
    kw.setdefault("ready_timeout", 60)
    kw.setdefault("request_timeout", 30)
    kw.setdefault("idle_seconds", 0)  # no idle watcher unless a test asks for it
    return EmbeddingEngine(model_name=model, **kw)


# =====================================================================
# The worker script, spoken to directly
# =====================================================================

class TestWorkerProtocol:
    def test_ping_similarity_rank_shutdown(self):
        proc = subprocess.Popen(
            [sys.executable, WORKER, "__test__"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        requests = [
            {"id": 1, "op": "ping"},
            {"id": 2, "op": "similarity", "a": "graph neural networks", "b": "graph neural networks"},
            {"id": 3, "op": "rank", "query": "protein folding", "candidates": ["protein folding", "stock markets", ""]},
            "this is not json",
            {"id": 5, "op": "nope"},
            {"id": 6, "op": "shutdown"},
        ]
        payload = "\n".join(r if isinstance(r, str) else json.dumps(r) for r in requests) + "\n"
        out, err = proc.communicate(payload, timeout=60)
        replies = [json.loads(l) for l in out.splitlines() if l.strip()]

        assert proc.returncode == 0, err
        assert replies[0]["ok"] and replies[0]["backend"] == "test-hash" and replies[0]["model"] == "__test__"
        assert replies[1]["value"] == pytest.approx(1.0)
        assert replies[2]["n"] == 2 and replies[2]["max"] == pytest.approx(1.0) and replies[2]["avg"] < 1.0
        assert replies[3]["ok"] is False and "invalid JSON" in replies[3]["error"]
        assert replies[4]["ok"] is False and "unknown op" in replies[4]["error"]
        assert replies[5]["ok"] and replies[5]["shutdown"] is True
        # Nothing but protocol lines may reach stdout.
        assert all(l.startswith("{") for l in out.splitlines() if l.strip())


# =====================================================================
# EmbeddingEngine as the worker's client
# =====================================================================

class TestEmbeddingEngineClient:
    def test_lazy_start_and_similarity(self):
        eng = _engine()
        try:
            assert eng.method == "jaccard-fallback"      # nothing started yet
            same = eng.similarity("sparse online autoencoder", "sparse online autoencoder")
            diff = eng.similarity("sparse online autoencoder", "medieval poetry archive")
            assert same == pytest.approx(1.0)
            assert 0.0 <= diff < same
            assert eng.similarity("", "anything") == 0.0
            assert eng.is_loaded
            assert eng.method == "test-hash"              # the worker's backend, not Jaccard
        finally:
            eng.close()
        assert not eng.is_loaded
        assert eng.method == "jaccard-fallback"

    def test_rank_similarity(self):
        eng = _engine()
        try:
            ranked = eng.rank_similarity("anomaly detection in streams",
                                         ["anomaly detection in streams", "cooking pasta", ""])
            assert ranked["n"] == 2
            assert ranked["max"] == pytest.approx(1.0)
            assert 0.0 <= ranked["avg"] <= ranked["max"]
            assert eng.rank_similarity("", ["x"]) == {"max": 0.0, "avg": 0.0, "n": 0}
        finally:
            eng.close()

    def test_restart_after_close(self):
        eng = _engine()
        try:
            eng.similarity("a b", "a b")
            first_pid = eng._proc.pid
            eng.close()
            assert eng.similarity("a b", "a b") == pytest.approx(1.0)
            assert eng._proc.pid != first_pid
            assert eng.method == "test-hash"
        finally:
            eng.close()

    def test_forced_fallback_never_spawns(self):
        eng = _engine()
        eng._load_failed = True  # what the offline engine tests do
        assert eng.similarity("same words", "same words") == pytest.approx(1.0)  # Jaccard
        assert eng._proc is None
        assert eng.method == "jaccard-fallback"

    def test_missing_interpreter_falls_back(self):
        eng = _engine(python=os.path.join(os.path.dirname(WORKER), "no-such-python.exe"))
        assert eng.similarity("alpha beta", "alpha gamma") == pytest.approx(1 / 3)  # Jaccard
        assert eng._load_failed is True
        assert eng.method == "jaccard-fallback"

    def test_slow_worker_falls_back_within_ready_timeout(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_MATCH_EMBEDDING_SLOW_SECONDS", "20")
        eng = _engine("__slow__", ready_timeout=1.5)
        t0 = time.time()
        value = eng.similarity("alpha beta", "alpha gamma")
        assert time.time() - t0 < 10
        assert value == pytest.approx(1 / 3)
        assert eng._load_failed is True and eng._proc is None

    def test_worker_death_is_recovered_by_restart(self):
        eng = _engine()
        try:
            assert eng.similarity("x y", "x y") == pytest.approx(1.0)
            first_pid = eng._proc.pid
            eng._proc.kill()
            eng._proc.wait(timeout=10)
            assert eng.method == "jaccard-fallback"      # honest while the worker is dead
            # The next call notices the dead worker, restarts it, and still answers with
            # embeddings (hash backend: one shared word out of two each -> cosine 0.5).
            assert eng.similarity("alpha beta", "alpha gamma") == pytest.approx(0.5)
            assert eng._proc.pid != first_pid
            assert eng.method == "test-hash"
            assert eng._load_failed is False
        finally:
            eng.close()

    def test_idle_shutdown_and_restart(self):
        eng = _engine(idle_seconds=1, idle_poll_seconds=0.2)
        try:
            eng.similarity("x y", "x y")
            first_pid = eng._proc.pid
            deadline = time.time() + 10
            while eng._alive() and time.time() < deadline:
                time.sleep(0.2)
            assert not eng._alive(), "idle watcher should have stopped the worker"
            assert eng.method == "jaccard-fallback"      # honest while stopped
            assert eng.similarity("x y", "x y") == pytest.approx(1.0)
            assert eng._proc.pid != first_pid             # restarted on demand
        finally:
            eng.close()
