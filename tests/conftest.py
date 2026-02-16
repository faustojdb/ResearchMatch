"""Shared fixtures for Research Match tests.

Uses in-memory SQLite DB and forces EmbeddingEngine to Jaccard fallback
so tests are deterministic and don't require the ML model.
"""
import sys
import os
import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

os.environ["RESEARCH_MATCH_DB"] = ":memory:"

from research_match_server import (
    init_database,
    EmbeddingEngine,
    OriginalityEvaluator,
    MatchingEngine,
    ReputationEngine,
    _get_or_create_user,
)


class JaccardOnlyEmbeddingEngine(EmbeddingEngine):
    """EmbeddingEngine that always uses Jaccard fallback (no ML model)."""

    def __init__(self):
        super().__init__()
        self._load_failed = True  # Force Jaccard fallback


@pytest.fixture
def db():
    """Fresh in-memory database for each test."""
    conn = init_database(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def embeddings():
    """Jaccard-only embedding engine for deterministic tests."""
    return JaccardOnlyEmbeddingEngine()


@pytest.fixture
def evaluator(db, embeddings):
    return OriginalityEvaluator(db, embeddings)


@pytest.fixture
def matcher(db, embeddings):
    return MatchingEngine(db, embeddings)


@pytest.fixture
def reputation(db):
    return ReputationEngine(db)


# --- Researcher data fixtures ---

COMMIT_PT = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "How to predict tertiary structure of intrinsically disordered proteins using local electrostatic interactions",
    "hypothesis": "Local electrostatic interaction patterns between adjacent amino acid residues are sufficient to predict stable conformational states",
    "theoretical_framework": "Levinthal paradox, Anfinsen dogma, energy landscape theory",
    "demonstrations_summary": "Basic Python scripts for electrostatic potential calculation",
    "demo_types": ["code", "data"],
    "code_languages": ["Python"],
    "adhoc_summary": "Novel framework proposing IDP conformational sampling reduction from O(n^3) to O(n)",
    "adhoc_connections": [
        "Applied Ising model from statistical mechanics",
        "Borrowed dimensionality reduction from manifold learning",
        "Connected disorder prediction with complex systems theory",
    ],
    "cherry_picking": ["AlphaFold2 attention mechanism", "Forman-Kay 2022 IDP classification"],
    "overall_solidity": "speculative",
    "solidity_levels": {"theory": "speculative", "demos": "functional", "adhoc": "adhoc", "cherry_picking": "cherry_picked"},
}

COMMIT_MARIA = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "Developing high-performance computational pipeline for protein structure prediction using enhanced sampling molecular dynamics",
    "hypothesis": "Combining graph neural network force fields with replica exchange molecular dynamics can achieve sub-angstrom accuracy",
    "theoretical_framework": "Classical molecular dynamics, enhanced sampling methods, neural network potentials",
    "demonstrations_summary": "Complete GPU-accelerated MD pipeline in Julia and CUDA. Custom GNN force field trained on 50K structures.",
    "demo_types": ["code", "data", "simulation", "math"],
    "code_languages": ["Julia", "Python", "CUDA", "C++"],
    "adhoc_summary": "Novel adaptive timestep algorithm adjusting integration step based on GNN ensemble uncertainty",
    "adhoc_connections": ["Applied uncertainty quantification from Bayesian deep learning"],
    "cherry_picking": ["SchNet architecture", "OpenMM framework"],
    "overall_solidity": "functional",
    "solidity_levels": {"theory": "proven", "demos": "functional", "adhoc": "functional", "cherry_picking": "cherry_picked"},
}

COMMIT_KENJI = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "Developing a topological framework for protein folding pathways using persistent homology and algebraic topology",
    "hypothesis": "The folding pathway of any globular protein can be uniquely characterized by its persistent homology barcode",
    "theoretical_framework": "Persistent homology theory, Morse theory, algebraic topology, topological data analysis",
    "demonstrations_summary": "Formal mathematical proofs establishing correspondence between Betti numbers and folding intermediates. Proofs in Lean4.",
    "demo_types": ["math", "proof_assistant"],
    "code_languages": ["Lean4"],
    "adhoc_summary": "Novel topological invariant capturing essential geometric features of the folding landscape",
    "adhoc_connections": [
        "Applied persistent homology from computational topology",
        "Connected Morse theory to folding kinetics",
        "Parallels between Conley index and folding pathway branching",
        "Applied knot theory to disulfide bond topology",
        "Connected algebraic topology with statistical mechanics",
    ],
    "cherry_picking": ["Edelsbrunner persistent homology algorithm"],
    "overall_solidity": "proven",
    "solidity_levels": {"theory": "proven", "demos": "proven", "adhoc": "speculative", "cherry_picking": "cherry_picked"},
}

COMMIT_ALEX = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "Using AlphaFold predictions to study protein folding mechanisms",
    "hypothesis": "AlphaFold confidence scores correlate with folding difficulty",
    "theoretical_framework": "AlphaFold2 architecture, standard bioinformatics tools",
    "demonstrations_summary": "Python notebook analyzing pLDDT scores from AlphaFold predictions",
    "demo_types": ["code"],
    "code_languages": ["Python"],
    "adhoc_summary": "Observation that low pLDDT regions correspond to folding nucleation sites",
    "adhoc_connections": [],
    "cherry_picking": ["AlphaFold2", "UniProt database", "BioPython"],
    "overall_solidity": "cherry_picked",
    "solidity_levels": {"theory": "cherry_picked", "demos": "adhoc", "adhoc": "adhoc", "cherry_picking": "cherry_picked"},
}


@pytest.fixture
def four_researchers(db, evaluator):
    """Register 4 researchers and submit their commits. Returns (user_ids, commit_ids, scores)."""
    import json, uuid

    users = {}
    commits = {}
    scores = {}

    for name, email, data in [
        ("PT", "pt@test.com", COMMIT_PT),
        ("Maria", "maria@test.com", COMMIT_MARIA),
        ("Kenji", "kenji@test.com", COMMIT_KENJI),
        ("Alex", "alex@test.com", COMMIT_ALEX),
    ]:
        user_id = _get_or_create_user(db, email, name)
        users[name] = user_id

        sc = evaluator.evaluate_commit(data, user_id)
        scores[name] = sc

        commit_id = str(uuid.uuid4())
        solidity_levels = data.get("solidity_levels", {})
        overall_solidity = data.get("overall_solidity", "speculative")

        db.execute("""
            INSERT INTO research_commits
            (id, user_id, version, domain, subdomain, problem, hypothesis,
             theoretical_framework, demonstrations_summary, demo_types,
             code_languages, adhoc_summary, adhoc_connections, cherry_picking,
             content_hash, ot_score, ofc_score, ot_breakdown, ofc_breakdown,
             solidity_levels, overall_solidity, solidity_impact)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            commit_id, user_id, 1,
            data.get("domain"), data.get("subdomain"),
            data.get("problem"), data.get("hypothesis"),
            data.get("theoretical_framework"),
            data.get("demonstrations_summary"),
            json.dumps(data.get("demo_types", [])),
            json.dumps(data.get("code_languages", [])),
            data.get("adhoc_summary"),
            json.dumps(data.get("adhoc_connections", [])),
            json.dumps(data.get("cherry_picking", [])),
            "test_hash",
            sc["ot_score"], sc["ofc_score"],
            json.dumps(sc["ot_breakdown"]), json.dumps(sc["ofc_breakdown"]),
            json.dumps(solidity_levels),
            overall_solidity,
            json.dumps(sc.get("solidity_impact", {})),
        ))
        commits[name] = commit_id

    db.commit()
    return users, commits, scores
