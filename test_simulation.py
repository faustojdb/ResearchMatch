"""
Research Match — Simulación de Flujo Completo v2
==================================================
Simula un escenario real con 4 investigadores trabajando en
biología molecular / plegamiento de proteínas, cada uno con
diferentes fortalezas teóricas y computacionales.

v2: Incluye niveles de solidez, sistema de rating, y reputación.
"""

import sys
import os
import json
import sqlite3

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Set test database
os.environ["RESEARCH_MATCH_DB"] = os.path.join(
    os.path.dirname(__file__), "test_research_match.db"
)

# Remove old test DB if exists
if os.path.exists(os.environ["RESEARCH_MATCH_DB"]):
    os.remove(os.environ["RESEARCH_MATCH_DB"])

from research_match_server import (
    init_database, OriginalityEvaluator, MatchingEngine, ReputationEngine,
    _get_or_create_user, _hash_content, _reputation_badge,
    SOLIDITY_MULTIPLIERS, SERVER_VERSION
)

# =============================================================================
# SETUP
# =============================================================================

db = init_database(os.environ["RESEARCH_MATCH_DB"])
evaluator = OriginalityEvaluator(db)
matcher = MatchingEngine(db)
reputation = ReputationEngine(db)

def register_user(email, pseudonym):
    user_id = _get_or_create_user(db, email, pseudonym)
    print(f"  ✅ Registrado: {pseudonym} (ID: {user_id[:8]}...)")
    return user_id

def submit_commit(user_id, commit_data):
    """Submit and evaluate a research commit (v2 with solidity)."""
    # Get version
    last = db.execute(
        "SELECT MAX(version) as v FROM research_commits WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    version = (last["v"] or 0) + 1

    content_hash = _hash_content(commit_data)
    scores = evaluator.evaluate_commit(commit_data, user_id)

    import uuid
    commit_id = str(uuid.uuid4())

    # v2: Extract solidity info
    solidity_levels = commit_data.get("solidity_levels", {})
    overall_solidity = commit_data.get("overall_solidity", "speculative")

    db.execute("""
        INSERT INTO research_commits
        (id, user_id, version, domain, subdomain, problem, hypothesis,
         theoretical_framework, demonstrations_summary, demo_types,
         code_languages, adhoc_summary, adhoc_connections, cherry_picking,
         content_hash, ot_score, ofc_score, ot_breakdown, ofc_breakdown,
         solidity_levels, overall_solidity, solidity_impact)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        commit_id, user_id, version,
        commit_data.get("domain"), commit_data.get("subdomain"),
        commit_data.get("problem"), commit_data.get("hypothesis"),
        commit_data.get("theoretical_framework"),
        commit_data.get("demonstrations_summary"),
        json.dumps(commit_data.get("demo_types", [])),
        json.dumps(commit_data.get("code_languages", [])),
        commit_data.get("adhoc_summary"),
        json.dumps(commit_data.get("adhoc_connections", [])),
        json.dumps(commit_data.get("cherry_picking", [])),
        content_hash,
        scores["ot_score"], scores["ofc_score"],
        json.dumps(scores["ot_breakdown"]), json.dumps(scores["ofc_breakdown"]),
        json.dumps(solidity_levels),
        overall_solidity,
        json.dumps(scores.get("solidity_impact", {})),
    ))
    db.commit()
    return commit_id, scores

def print_separator(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}\n")

def print_scores(name, scores):
    ot = scores["ot_score"]
    ofc = scores["ofc_score"]
    ot_bar = '█' * int(ot/5) + '░' * (20 - int(ot/5))
    ofc_bar = '█' * int(ofc/5) + '░' * (20 - int(ofc/5))

    print(f"  🔬 {name}")
    print(f"     OT  (Teórica):          [{ot_bar}] {ot:.1f}%")
    print(f"     OFC (Formal-Computac.):  [{ofc_bar}] {ofc:.1f}%")

    # v2: Show solidity impact
    impact = scores.get("solidity_impact", {})
    if impact:
        print(f"     Solidity Impact:         {impact.get('explanation', 'N/A')}")
        print(f"     OT multiplier:           x{impact.get('ot_multiplier', 1.0):.2f}")
        print(f"     OFC multiplier:          x{impact.get('ofc_multiplier', 1.0):.2f}")

    print(f"     Breakdown OT:  {json.dumps(scores['ot_breakdown'])}")
    print(f"     Breakdown OFC: {json.dumps(scores['ofc_breakdown'])}")
    print()

def semaphore_emoji(s):
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(s, "⚪")

# =============================================================================
# HEADER
# =============================================================================

print(f"\n{'='*70}")
print(f"  Research Match v{SERVER_VERSION} — Simulación de Flujo Completo")
print(f"  Solidity Multipliers: {SOLIDITY_MULTIPLIERS}")
print(f"{'='*70}")

# =============================================================================
# FASE 1: REGISTRO
# =============================================================================

print_separator("FASE 1: REGISTRO DE INVESTIGADORES")

user_you = register_user("faustojdb@hotmail.com", "ProteinTheorist_AR")
user_maria = register_user("maria.comp@example.com", "CompBio_Maria")
user_kenji = register_user("kenji.math@example.com", "MathBio_Kenji")
user_alex = register_user("alex.gen@example.com", "BioGeneral_Alex")

# =============================================================================
# FASE 2: SUBMIT COMMITS (v2: con niveles de solidez)
# =============================================================================

print_separator("FASE 2: SUBMIT DE RESEARCH COMMITS (v2: con solidez)")

print("  📝 Submitting commit para ProteinTheorist_AR (Tú)...")
commit_you_data = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "How to predict tertiary structure of intrinsically disordered proteins using local electrostatic interactions as primary determinants instead of global energy minimization",
    "hypothesis": "Local electrostatic interaction patterns between adjacent amino acid residues are sufficient to predict stable conformational states of intrinsically disordered proteins without requiring full energy landscape computation",
    "theoretical_framework": "Levinthal paradox, Anfinsen dogma, energy landscape theory, funnel model of protein folding, recent work on IDPs by Forman-Kay and Mittag",
    "demonstrations_summary": "Basic Python scripts for electrostatic potential calculation between residue pairs using Coulomb approximation. Preliminary Jupyter notebook with visualization of charge distributions.",
    "demo_types": ["code", "data"],
    "code_languages": ["Python"],
    "adhoc_summary": "Novel framework proposing that IDP conformational sampling can be reduced from O(n^3) to O(n) by focusing exclusively on nearest-neighbor electrostatic interactions. Preliminary evidence from molecular dynamics snapshots of 5 IDP families shows strong correlation (r=0.82) between local electrostatic patterns and observed conformational states.",
    "adhoc_connections": [
        "Applied Ising model concepts from statistical mechanics to model residue-residue electrostatic coupling",
        "Borrowed dimensionality reduction techniques from manifold learning to visualize conformational spaces",
        "Connected protein disorder prediction with concepts from complex systems theory and emergence"
    ],
    "cherry_picking": [
        "AlphaFold2 attention mechanism concept - adapted as inspiration for local interaction focus, not directly used",
        "Forman-Kay 2022 IDP classification - used taxonomy of disorder types as starting framework",
        "Debye-Hückel theory - standard electrostatic screening model, applied without modification"
    ],
    # v2: Solidity declaration
    "overall_solidity": "speculative",
    "solidity_levels": {
        "theory": "speculative",
        "demos": "functional",
        "adhoc": "adhoc",
        "cherry_picking": "cherry_picked"
    }
}
cid_you, scores_you = submit_commit(user_you, commit_you_data)
print_scores("ProteinTheorist_AR (Tú)", scores_you)

print("  📝 Submitting commit para CompBio_Maria...")
commit_maria_data = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "Developing high-performance computational pipeline for protein structure prediction using enhanced sampling molecular dynamics with machine learning force fields",
    "hypothesis": "Combining graph neural network-based force fields with replica exchange molecular dynamics can achieve sub-angstrom accuracy for small to medium proteins within hours on consumer GPU hardware",
    "theoretical_framework": "Classical molecular dynamics, enhanced sampling methods (REMD, metadynamics), neural network potentials, equivariant graph neural networks for molecular systems",
    "demonstrations_summary": "Complete GPU-accelerated MD pipeline in Julia and CUDA. Custom GNN force field trained on 50K protein structures from PDB. Benchmark suite showing 0.8Å RMSD on CASP15 targets. Automated pipeline for structure prediction from sequence with full CI/CD and reproducibility.",
    "demo_types": ["code", "data", "simulation", "math"],
    "code_languages": ["Julia", "Python", "CUDA", "C++"],
    "adhoc_summary": "Novel adaptive timestep algorithm that adjusts integration step based on local force field uncertainty estimates from the GNN ensemble. Reduces simulation time by 40% without accuracy loss.",
    "adhoc_connections": [
        "Applied uncertainty quantification from Bayesian deep learning to force field confidence estimation"
    ],
    "cherry_picking": [
        "SchNet architecture - used as base for GNN, modified attention mechanism",
        "OpenMM framework - used for MD engine, extended with custom integrators",
        "CASP15 evaluation metrics - standard benchmark protocol, no modifications"
    ],
    # v2: Solidity — mostly proven/functional
    "overall_solidity": "functional",
    "solidity_levels": {
        "theory": "proven",
        "demos": "functional",
        "adhoc": "functional",
        "cherry_picking": "cherry_picked"
    }
}
cid_maria, scores_maria = submit_commit(user_maria, commit_maria_data)
print_scores("CompBio_Maria", scores_maria)

print("  📝 Submitting commit para MathBio_Kenji...")
commit_kenji_data = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "Developing a topological framework for understanding protein folding pathways using persistent homology and algebraic topology to characterize the folding energy landscape",
    "hypothesis": "The folding pathway of any globular protein can be uniquely characterized by its persistent homology barcode, and proteins with similar topological invariants share folding mechanisms regardless of sequence similarity",
    "theoretical_framework": "Persistent homology theory, Morse theory applied to energy landscapes, algebraic topology, topological data analysis, Conley index theory for dynamical systems",
    "demonstrations_summary": "Formal mathematical proofs establishing correspondence between Betti numbers of sublevel sets and folding intermediates. Theorem proving folding pathway uniqueness under topological equivalence. Proofs formalized in Lean4.",
    "demo_types": ["math", "proof_assistant"],
    "code_languages": ["Lean4"],
    "adhoc_summary": "Completely novel topological invariant ('folding barcode') that captures the essential geometric features of the folding landscape. Proof that this invariant is complete for single-domain proteins. New theorem connecting Reeb graph structure to folding kinetics.",
    "adhoc_connections": [
        "Applied persistent homology from computational topology to energy landscapes in biochemistry",
        "Connected Morse theory from differential topology to protein folding kinetics",
        "Drew parallels between Conley index in dynamical systems and folding pathway branching",
        "Applied concepts from knot theory to disulfide bond topology in folding",
        "Connected algebraic topology with statistical mechanics partition functions"
    ],
    "cherry_picking": [
        "Edelsbrunner persistent homology algorithm - used standard implementation",
        "Frauenfelder energy landscape theory - used as physical motivation, not mathematical framework"
    ],
    # v2: Solidity — proven theory, speculative connections
    "overall_solidity": "proven",
    "solidity_levels": {
        "theory": "proven",
        "demos": "proven",
        "adhoc": "speculative",
        "cherry_picking": "cherry_picked"
    }
}
cid_kenji, scores_kenji = submit_commit(user_kenji, commit_kenji_data)
print_scores("MathBio_Kenji", scores_kenji)

print("  📝 Submitting commit para BioGeneral_Alex...")
commit_alex_data = {
    "domain": "molecular biology",
    "subdomain": "protein folding",
    "problem": "Using AlphaFold predictions to study protein folding mechanisms",
    "hypothesis": "AlphaFold confidence scores correlate with folding difficulty and can predict folding intermediates",
    "theoretical_framework": "AlphaFold2 architecture, protein structure databases, standard bioinformatics tools",
    "demonstrations_summary": "Python notebook analyzing pLDDT scores from AlphaFold predictions on a set of 100 proteins",
    "demo_types": ["code"],
    "code_languages": ["Python"],
    "adhoc_summary": "Observation that low pLDDT regions often correspond to known folding nucleation sites",
    "adhoc_connections": [],
    "cherry_picking": [
        "AlphaFold2 - used standard model and predictions without modification",
        "UniProt database - standard protein data source",
        "BioPython - standard library for analysis"
    ],
    # v2: Solidity — mostly cherry-picked
    "overall_solidity": "cherry_picked",
    "solidity_levels": {
        "theory": "cherry_picked",
        "demos": "adhoc",
        "adhoc": "adhoc",
        "cherry_picking": "cherry_picked"
    }
}
cid_alex, scores_alex = submit_commit(user_alex, commit_alex_data)
print_scores("BioGeneral_Alex", scores_alex)

# =============================================================================
# FASE 3: BÚSQUEDA DE MATCHES
# =============================================================================

print_separator("FASE 3: BÚSQUEDA DE MATCHES PARA TI (ProteinTheorist_AR)")

matches = matcher.find_matches(user_you, limit=10)

if not matches:
    print("  ⚠️  No se encontraron matches.")
else:
    print(f"  🔍 Se encontraron {len(matches)} candidatos:\n")

    for i, m in enumerate(matches, 1):
        sem = semaphore_emoji(m['semaphore'])
        print(f"  {'─'*60}")
        print(f"  Candidato #{i}: {m['candidate_pseudonym']}")
        print(f"  {sem} Semáforo: {m['semaphore'].upper()}")
        print(f"  ")
        print(f"     Similitud de base:      {m['base_similarity']:.1f}%")
        print(f"     Complementariedad:       {m['complementarity_score']:.1f}%")
        print(f"     Tú ganas de él/ella:     {m['a_gains_from_b']:.1f}%")
        print(f"     Él/ella gana de ti:      {m['b_gains_from_a']:.1f}%")
        print(f"     Sus scores:              OT: {m['candidate_ot']:.1f}% / OFC: {m['candidate_ofc']:.1f}%")
        print(f"     Dominio:                 {m['candidate_domain']} / {m.get('candidate_subdomain', '')}")
        print(f"     Solidez:                 {m.get('candidate_solidity', 'unknown')}")
        rep_score = m.get('candidate_reputation', 100)
        rep_ratings = m.get('candidate_total_ratings', 0)
        print(f"     Reputación:              {_reputation_badge(rep_score, rep_ratings)}")
        print(f"  ")
        print(f"     💡 POR QUÉ ESTE SEMÁFORO:")
        print(f"        Para ti:    {m.get('semaphore_reason', 'N/A')}")
        print(f"        Para ellos: {m.get('semaphore_reason_for_candidate', 'N/A')}")
        print(f"        Resumen:    {m.get('semaphore_summary', 'N/A')}")
        print()

# =============================================================================
# FASE 4: ANÁLISIS DE COMPLEMENTARIEDAD
# =============================================================================

print_separator("FASE 4: ANÁLISIS DE COMPLEMENTARIEDAD")

print("  📊 TUS SCORES:")
print(f"     OT:  {scores_you['ot_score']:.1f}%  (Teoría fuerte, conexiones interdisciplinarias)")
print(f"     OFC: {scores_you['ofc_score']:.1f}%  (Código básico, Python simple)")
print()

print("  🔍 ANÁLISIS POR CANDIDATO:\n")

for i, m in enumerate(matches, 1):
    sem = semaphore_emoji(m['semaphore'])
    print(f"  {sem} {m['candidate_pseudonym']}:")

    if m['candidate_pseudonym'] == 'CompBio_Maria':
        print(f"     → María tiene OFC altísimo ({m['candidate_ofc']:.1f}%) con pipeline completo")
        print(f"       en Julia/CUDA/C++. Tú aportas teoría original sobre IDPs.")
        print(f"       Ella puede implementar tus ideas a escala GPU.")
        print(f"       MATCH IDEAL: Tu teoría + su código = validación computacional masiva.")

    elif m['candidate_pseudonym'] == 'MathBio_Kenji':
        print(f"     → Kenji tiene OT excepcional ({m['candidate_ot']:.1f}%) con topología algebraica.")
        print(f"       Ambos son fuertes en teoría pero en ejes diferentes:")
        print(f"       tú en electrostática local, él en topología del landscape.")
        print(f"       Potencial: fusionar ambos marcos en una teoría unificada.")

    elif m['candidate_pseudonym'] == 'BioGeneral_Alex':
        print(f"     → Alex tiene scores bajos en ambos ejes.")
        print(f"       Usa herramientas estándar sin modificación.")
        print(f"       Baja complementariedad - poco aporte mutuo.")

    print()

# =============================================================================
# FASE 5: SIMULACIÓN DE SOLICITUD + EQUIPO
# =============================================================================

print_separator("FASE 5: SIMULACIÓN DE SOLICITUD DE COLABORACIÓN")

import uuid

best = None
if matches:
    for m in matches:
        if m['semaphore'] == 'green':
            best = m
            break
    if not best:
        best = matches[0]

    print(f"  📨 Enviando solicitud a {best['candidate_pseudonym']}...")

    match_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO matches (id, user_a_id, user_b_id, base_similarity,
            complementarity_score, semaphore, semaphore_reason_a, semaphore_reason_b,
            semaphore_summary, a_gains_from_b, b_gains_from_a)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (match_id, user_you, best['candidate_user_id'],
          best['base_similarity'], best['complementarity_score'],
          best['semaphore'],
          best.get('semaphore_reason', ''),
          best.get('semaphore_reason_for_candidate', ''),
          best.get('semaphore_summary', ''),
          best['a_gains_from_b'], best['b_gains_from_a']))

    req_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO collaboration_requests (id, match_id, requester_id, recipient_id, message, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (req_id, match_id, user_you, best['candidate_user_id'],
          "Estoy trabajando en predicción de IDPs por electrostática local. Tu pipeline computacional podría validar mi framework a escala. ¿Te interesa explorar una colaboración?"))
    db.commit()

    print(f"  ✅ Solicitud enviada (ID: {req_id[:8]}...)")
    print(f"     Semáforo: {semaphore_emoji(best['semaphore'])} {best['semaphore'].upper()}")
    print()

    # Simulate acceptance
    print(f"  🤝 {best['candidate_pseudonym']} acepta la solicitud...")

    team_id = str(uuid.uuid4())
    team_name = f"IDP-Electrostatics-{team_id[:6]}"

    db.execute(
        "UPDATE collaboration_requests SET status = 'accepted', responded_at = datetime('now') WHERE id = ?",
        (req_id,))
    db.execute(
        "INSERT INTO teams (id, name, license_type) VALUES (?, ?, 'joint-equal')",
        (team_id, team_name))
    db.execute(
        "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')",
        (team_id, user_you))
    db.execute(
        "INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')",
        (team_id, best['candidate_user_id']))
    db.commit()

    print(f"  ✅ ¡EQUIPO CREADO!")
    print(f"     Nombre: {team_name}")
    print(f"     Licencia: joint-equal (50/50)")
    print(f"     Miembros: ProteinTheorist_AR + {best['candidate_pseudonym']}")
    print()

    # =========================================================================
    # FASE 6: SISTEMA DE RATING (NEW in v2)
    # =========================================================================

    print_separator("FASE 6: SISTEMA DE RATING (v2)")

    print("  ⭐ Simulando ratings mutuos después de colaborar...\n")

    # You rate the collaborator
    rating_id_1 = str(uuid.uuid4())
    db.execute("""
        INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (rating_id_1, team_id, user_you, best['candidate_user_id'],
          5, 5, 4, "Excelente pipeline computacional. Declarò solidez 'functional' y fue preciso."))
    db.commit()

    print(f"  📝 ProteinTheorist_AR → {best['candidate_pseudonym']}")
    print(f"     Honesty: 5/5  Quality: 5/5  Effort: 4/5")
    print(f"     Estado: ANÓNIMO (esperando rating del otro miembro)")
    print()

    # Check both_rated
    both = reputation.check_both_rated(team_id, user_you, best['candidate_user_id'])
    print(f"  🔒 ¿Ambos han calificado? {both}")
    print()

    # Collaborator rates you
    rating_id_2 = str(uuid.uuid4())
    db.execute("""
        INSERT INTO ratings (id, team_id, rater_id, rated_id, honesty, quality, effort, comment)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (rating_id_2, team_id, best['candidate_user_id'], user_you,
          4, 4, 5, "Teoría muy original. Solidez 'speculative' honesta - buen punto de partida."))
    db.commit()

    both = reputation.check_both_rated(team_id, user_you, best['candidate_user_id'])
    print(f"  📝 {best['candidate_pseudonym']} → ProteinTheorist_AR")
    print(f"     Honesty: 4/5  Quality: 4/5  Effort: 5/5")
    print(f"  🔓 ¿Ambos han calificado? {both} → ¡RATINGS REVELADOS!")
    print()

    # Reveal and update reputations
    reputation.reveal_ratings(team_id)
    reputation.update_user_reputation(user_you)
    reputation.update_user_reputation(best['candidate_user_id'])

    # Show reputations
    rep_you = reputation.calculate_reputation(user_you)
    rep_other = reputation.calculate_reputation(best['candidate_user_id'])

    print(f"  🏅 REPUTACIONES ACTUALIZADAS:")
    print(f"     ProteinTheorist_AR:  {_reputation_badge(rep_you['reputation_score'], rep_you['total_ratings'])}")
    print(f"       Avg honesty: {rep_you['avg_honesty']:.1f}  quality: {rep_you['avg_quality']:.1f}  effort: {rep_you['avg_effort']:.1f}")
    print(f"     {best['candidate_pseudonym']}:  {_reputation_badge(rep_other['reputation_score'], rep_other['total_ratings'])}")
    print(f"       Avg honesty: {rep_other['avg_honesty']:.1f}  quality: {rep_other['avg_quality']:.1f}  effort: {rep_other['avg_effort']:.1f}")
    print()

    # =========================================================================
    # FASE 7: DETECCIÓN DE ABUSO (NEW in v2)
    # =========================================================================

    print_separator("FASE 7: DETECCIÓN DE ABUSO EN RATINGS (v2)")

    print("  🔍 Verificando patrones de abuso...\n")

    abuse_you = reputation.detect_abuse_patterns(user_you)
    abuse_other = reputation.detect_abuse_patterns(best['candidate_user_id'])

    print(f"  ProteinTheorist_AR:")
    print(f"     Abuse detected: {abuse_you['abuse_detected']}")
    print(f"     Flags: {abuse_you['flags']}")
    print()
    print(f"  {best['candidate_pseudonym']}:")
    print(f"     Abuse detected: {abuse_other['abuse_detected']}")
    print(f"     Flags: {abuse_other['flags']}")
    print()

# =============================================================================
# RESUMEN FINAL
# =============================================================================

print_separator("RESUMEN FINAL")

print(f"  🎯 Research Match v{SERVER_VERSION} — Simulación completada")
print()
print("  Flujo completo v2:")
print("    1. Registro → 4 investigadores registrados")
print("    2. Commit  → Con declaración de solidez por componente")
print("    3. Evaluación → OT/OFC scores con multiplicadores de solidez")
print("    4. Match → Semáforo + badge de reputación + solidez")
print("    5. Solicitud → Enviada y aceptada, equipo creado")
print("    6. Rating → Anónimo hasta que ambos califican, luego revelado")
print("    7. Reputación → Calculada con honesty=50%, quality=30%, effort=20%")
print("    8. Anti-abuso → Detección de patrones sospechosos")
print()
print(f"  📦 Base de datos de test: {os.environ['RESEARCH_MATCH_DB']}")
print()
