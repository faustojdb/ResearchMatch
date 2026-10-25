"""Research Match embedding worker (sidecar process).

The MCP server never imports torch / sentence-transformers itself: on Windows, importing
that stack inside an already-running MCP server freezes on a compiled-module load
(observed with scipy.special's ``_ufuncs`` during a tool call, reproducible with the
import in a background thread as well). A fresh process imports it without trouble, so
the server starts this script on first use and talks to it over pipes.

Protocol — one JSON object per line on stdin, one JSON object per line on stdout:

    {"id": 1, "op": "ping"}
        -> {"id": 1, "ok": true, "backend": "sentence-transformers", "model": "all-MiniLM-L6-v2"}
    {"id": 2, "op": "similarity", "a": "text", "b": "text"}
        -> {"id": 2, "ok": true, "value": 0.42}
    {"id": 3, "op": "rank", "query": "text", "candidates": ["text", ...]}
        -> {"id": 3, "ok": true, "max": 0.7, "avg": 0.4, "n": 3}
    {"id": 4, "op": "shutdown"}
        -> {"id": 4, "ok": true}   (then the process exits)

Any failure answers {"id": n, "ok": false, "error": "..."}; a failure to load the model at
startup answers {"id": null, "ok": false, "fatal": true, "error": "..."} and exits with 1.

The model name comes from argv[1] or RESEARCH_MATCH_EMBEDDING_MODEL. Two special names
exist for the offline test-suite and never touch the network or ML libraries:
``__test__`` (deterministic hashed bag-of-words vectors) and ``__slow__`` (same, but sleeps
``RESEARCH_MATCH_EMBEDDING_SLOW_SECONDS`` before becoming ready).

Everything that is not protocol output goes to stderr: stdout is reserved for the JSON
lines, and the real stdout is captured before any library can print to it.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import traceback
from typing import List, Sequence

# Keep ML libraries quiet: progress bars and chatter would only end up in the host's log.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TQDM_DISABLE", "1")

TEST_MODEL = "__test__"
SLOW_TEST_MODEL = "__slow__"
_TEST_DIM = 256


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


class HashBackend:
    """Deterministic bag-of-words embedding for tests (no ML libraries involved)."""

    name = "test-hash"

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        out = []
        for text in texts:
            vec = [0.0] * _TEST_DIM
            for word in text.lower().split():
                h = int(hashlib.sha1(word.encode("utf-8")).hexdigest(), 16)
                vec[h % _TEST_DIM] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceTransformerBackend:
    name = "sentence-transformers"

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # heavy import, this process only

        self._model = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        return self._model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False).tolist()


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def load_backend(model_name: str):
    if model_name == SLOW_TEST_MODEL:
        time.sleep(float(os.environ.get("RESEARCH_MATCH_EMBEDDING_SLOW_SECONDS", "5")))
        return HashBackend()
    if model_name == TEST_MODEL:
        return HashBackend()
    return SentenceTransformerBackend(model_name)


def handle(backend, model_name: str, req: dict) -> dict:
    op = req.get("op")
    rid = req.get("id")
    if op == "ping":
        return {"id": rid, "ok": True, "backend": backend.name, "model": model_name, "pid": os.getpid()}
    if op == "similarity":
        a, b = req.get("a") or "", req.get("b") or ""
        if not a or not b:
            return {"id": rid, "ok": True, "value": 0.0}
        va, vb = backend.encode([a, b])
        return {"id": rid, "ok": True, "value": _clamp(_dot(va, vb))}
    if op == "rank":
        query = req.get("query") or ""
        cands = [c for c in (req.get("candidates") or []) if c]
        if not query or not cands:
            return {"id": rid, "ok": True, "max": 0.0, "avg": 0.0, "n": 0}
        vectors = backend.encode([query] + cands)
        q, rest = vectors[0], vectors[1:]
        sims = [_clamp(_dot(q, v)) for v in rest]
        return {"id": rid, "ok": True, "max": max(sims), "avg": sum(sims) / len(sims), "n": len(sims)}
    if op == "shutdown":
        return {"id": rid, "ok": True, "shutdown": True}
    return {"id": rid, "ok": False, "error": f"unknown op {op!r}"}


def main() -> int:
    # Capture the protocol stream first, then point sys.stdout at stderr so that nothing a
    # library prints can corrupt the JSON lines.
    proto = open(sys.stdout.fileno(), "w", encoding="utf-8", buffering=1, closefd=False)
    sys.stdout = sys.stderr
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 — older streams without reconfigure
        pass

    model_name = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get(
        "RESEARCH_MATCH_EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    def send(obj: dict) -> None:
        proto.write(json.dumps(obj, ensure_ascii=True) + "\n")
        proto.flush()

    started = time.time()
    try:
        backend = load_backend(model_name)
    except Exception as e:  # noqa: BLE001 — report and exit; the server falls back to Jaccard
        print(f"[embedding-worker] failed to load model {model_name!r}: {e!r}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        send({"id": None, "ok": False, "fatal": True, "error": f"{type(e).__name__}: {e}"})
        return 1
    print(f"[embedding-worker] ready: backend={backend.name} model={model_name} "
          f"in {time.time() - started:.1f}s", file=sys.stderr, flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError as e:
            send({"id": None, "ok": False, "error": f"invalid JSON: {e}"})
            continue
        try:
            resp = handle(backend, model_name, req)
        except Exception as e:  # noqa: BLE001 — never die on a bad request
            resp = {"id": req.get("id"), "ok": False, "error": f"{type(e).__name__}: {e}"}
        send(resp)
        if resp.get("shutdown"):
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
