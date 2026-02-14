"""
Research Match — Simulación de Flujo Completo
==============================================
Simula un escenario real con 4 investigadores trabajando en
biología molecular / plegamiento de proteínas, cada uno con
diferentes fortalezas teóricas y computacionales.
"""

import sys
import os
import json
import sqlite3

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# Set test database
os.environ["RESEARCH_MATCH_DB"] = "/home/claude/ResearchMatch/test_research_match.db"

# Remove old test DB if exists
if os.path.exists(os.environ["RESEARCH_MATCH_DB"]):
    os.remove(os.environ["RESEARCH_MATCH_DB"])

from research_match_server import (
    init_database, OriginalityEvaluator, MatchingEngine,
    _get_or_create_user, _hash_content
)

# =============================================================================
# SETUP
# =============================================================================

db = init_database(os.environ["RESEARCH_MATCH_DB"])
evaluator = OriginalityEvaluator(db)
matcher = MatchingEngine(db)

def register_user(email, pseudonym):
    user_id = _get_or_create_user(db, email, pseudonym)
    print(f"  ✅ Registrado: {pseudonym} (ID: {user_id[:8]}...)")
    return user_id

def submit_commit(user_id, commit_data):
    """Submit and evaluate a research commit."""
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
    
    db.execute("""
        INSERT INTO research_commits
        (id, user_id, version, domain, subdomain, problem, hypothesis,
         theoretical_framework, demonstrations_summary, demo_types,
         code_languages, adhoc_summary, adhoc_connections, cherry_picking,
         content_hash, ot_score, ofc_score, ot_breakdown, ofc_breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    
    print(f"  📊 {name}")
    print(f"     OT  (Teórica):          [{ot_bar}] {ot:.1f}%")
    print(f"     OFC (Formal-Computac.):  [{ofc_bar}] {ofc:.1f}%")
    print(f"     Breakdown OT:  {json.dumps(scores['ot_breakdown'])}")
    print(f"     Breakdown OFC: {json.dumps(scores['ofc_breakdown'])}")
    print()

def semaphore_emoji(s):
    return {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(s, "⚪")

# =============================================================================
# ESCENARIO: Plegamiento de Proteínas
# =============================================================================

print_separator("FASE 1: REGISTRO DE INVESTIGADORES")

# TÚ — Investigador con teoría fuerte, código básico
user_you = register_user("faustojdb@hotmail.com", "ProteinTheorist_AR")

# Investigadora computacional — código fuerte, teoría estándar  
user_maria = register_user("maria.comp@example.com", "CompBio_Maria")

# Teórico matemático — teoría muy original, sin código
user_kenji = register_user("kenji.math@example.com", "MathBio_Kenji")

# Generalista — un poco de todo, nada destacado
user_alex = register_user("alex.gen@example.com", "BioGeneral_Alex")

# =============================================================================
print_separator("FASE 2: SUBMIT DE RESEARCH COMMITS")
# =============================================================================

print("  📝 Submitting commit para ProteinTheorist_AR (TÚ)...")
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
        "AlphaFold2 attention mechanism concept — adapted as inspiration for local interaction focus, not directly used",
        "Forman-Kay 2022 IDP classification — used taxonomy of disorder types as starting framework",
        "Debye-Hückel theory — standard electrostatic screening model, applied without modification"
    ]
}
cid_you, scores_you = submit_commit(user_you, commit_you_data)
print_scores("ProteinTheorist_AR (TÚ)", scores_you)

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
        "SchNet architecture — used as base for GNN, modified attention mechanism",
        "OpenMM framework — used for MD engine, extended with custom integrators",
        "CASP15 evaluation metrics — standard benchmark protocol, no modifications"
    ]
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
    "adhoc_summary": "Completely novel topological invariant ('folding barcode') that captures the essential geometric features of the folding landscape. Proof that this invariant is complete for single-domain proteins. New theorem connecting Reeb graph structure to folding kinetics. Potential to classify all known protein folds by topological type rather than structural similarity.",
    "adhoc_connections": [
        "Applied persistent homology from computational topology to energy landscapes in biochemistry",
        "Connected Morse theory from differential topology to protein folding kinetics",
        "Drew parallels between Conley index in dynamical systems and folding pathway branching",
        "Applied concepts from knot theory to disulfide bond topology in folding",
        "Connected algebraic topology with statistical mechanics partition functions"
    ],
    "cherry_picking": [
        "Edelsbrunner persistent homology algorithm — used standard implementation",
        "Frauenfelder energy landscape theory — used as physical motivation, not mathematical framework"
    ]
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
        "AlphaFold2 — used standard model and predictions without modification",
        "UniProt database — standard protein data source",
        "BioPython — standard library for analysis"
    ]
}
cid_alex, scores_alex = submit_commit(user_alex, commit_alex_data)
print_scores("BioGeneral_Alex", scores_alex)

# =============================================================================
print_separator("FASE 3: BÚSQUEDA DE MATCHES PARA TI (ProteinTheorist_AR)")
# =============================================================================

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
        print()

# =============================================================================
print_separator("FASE 4: ANÁLISIS DE COMPLEMENTARIEDAD")
# =============================================================================

print("  📊 TUS SCORES:")
print(f"     OT:  {scores_you['ot_score']:.1f}%  (Teoría fuerte, conexiones interdisciplinarias)")
print(f"     OFC: {scores_you['ofc_score']:.1f}%  (Código básico, Python simple)")
print()

print("  🔬 ANÁLISIS POR CANDIDATO:\n")

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
        print(f"       Baja complementariedad — poco aporte mutuo.")
    
    print()

# =============================================================================
print_separator("FASE 5: SIMULACIÓN DE SOLICITUD DE COLABORACIÓN")
# =============================================================================

import uuid

if matches:
    # Find the best green match
    best = None
    for m in matches:
        if m['semaphore'] == 'green':
            best = m
            break
    if not best:
        best = matches[0]
    
    print(f"  📤 Enviando solicitud a {best['candidate_pseudonym']}...")
    
    # Create match record
    match_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO matches (id, user_a_id, user_b_id, base_similarity,
            complementarity_score, semaphore, a_gains_from_b, b_gains_from_a)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (match_id, user_you, best['candidate_user_id'],
          best['base_similarity'], best['complementarity_score'],
          best['semaphore'], best['a_gains_from_b'], best['b_gains_from_a']))
    
    # Create collaboration request
    req_id = str(uuid.uuid4())
    db.execute("""
        INSERT INTO collaboration_requests (id, match_id, requester_id, recipient_id, message, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
    """, (req_id, match_id, user_you, best['candidate_user_id'],
          "Estoy trabajando en predicción de IDPs por electrostática local. Tu pipeline computacional podría validar mi framework a escala. ¿Te interesa explorar una colaboración?"))
    db.commit()
    
    print(f"  ✅ Solicitud enviada (ID: {req_id[:8]}...)")
    print(f"     Semáforo: {semaphore_emoji(best['semaphore'])} {best['semaphore'].upper()}")
    print(f"     Mensaje: 'Estoy trabajando en predicción de IDPs por electrostática local...'")
    print()
    
    # Simulate acceptance
    print(f"  📥 {best['candidate_pseudonym']} acepta la solicitud...")
    
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
    print(f"     Estado: Revelación gradual iniciada")
    print()
    print(f"  📋 Próximos pasos:")
    print(f"     1. IA genera resúmenes anónimos del trabajo de cada parte")
    print(f"     2. Ambos confirman interés → se revelan identidades")
    print(f"     3. Se abre repositorio compartido con trazabilidad")
    print(f"     4. Licencia conjunta protege contribuciones de ambos")

print_separator("FIN DE LA SIMULACIÓN")
print("  🎉 Flujo completo: Registro → Commit → Evaluación → Match → Solicitud → Equipo")
print("  📁 Base de datos de test: test_research_match.db")
print()
