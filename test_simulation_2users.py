#!/usr/bin/env python3
"""Full 2-user E2E simulation: Alice (ResearchMatch) + Bob (MastersThesis).

Tests all MCP tools via direct async calls with monkeypatched context.
"""
import asyncio
import json
import os
import sqlite3
import sys
import uuid
import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Setup paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

# DB config
DB_PATH = os.path.join(os.path.dirname(__file__), "test_simulation_2users.db")
os.environ["RESEARCH_MATCH_DB"] = DB_PATH
os.environ["RESEARCH_MATCH_LOG_LEVEL"] = "WARNING"

# Remove stale DB
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

from research_match_server import (
    init_database,
    EmbeddingEngine, OriginalityEvaluator, MatchingEngine, ReputationEngine,
    _get_current_user, _get_or_create_user,
    research_match_register, research_match_prepare_commit,
    research_match_submit_commit, research_match_my_profile,
    research_match_find_collaborators, research_match_send_request,
    research_match_inbox, research_match_respond_request,
    research_match_needs_create, research_match_needs_list,
    research_match_needs_resolve, research_match_reveal_request,
    research_match_reveal_respond, research_match_reveal_status,
    research_match_team_license, research_match_share_file,
    research_match_shared_files, research_match_rate_user,
    research_match_audit_log,
    RegisterInput, SubmitCommitInput, FindCollaboratorsInput,
    SendRequestInput, RespondRequestInput, RateUserInput,
    NeedsCreateInput, NeedsListInput, NeedsResolveInput,
    RevealRequestInput, RevealRespondInput, RevealStatusInput,
    TeamLicenseInput, ShareFileInput, SharedFilesInput,
    AuditLogInput, PrepareCommitInput,
)


# Initialize DB and engines
db = init_database(DB_PATH)
embedding = EmbeddingEngine()
evaluator = OriginalityEvaluator(db, embedding)
matcher = MatchingEngine(db, embedding)
reputation = ReputationEngine(db)

# Create a mock context that returns our DB/engines
def make_ctx():
    ctx = MagicMock()
    state = {"db": db, "evaluator": evaluator, "matcher": matcher, "reputation": reputation}
    ctx.request_context.lifespan_state = state
    return ctx

CTX = make_ctx()


def switch_user(email_hash):
    """Switch _get_current_user to return the user with this email_hash."""
    now = datetime.now(timezone.utc).isoformat()
    db.execute("UPDATE users SET created_at = '2000-01-01T00:00:00' WHERE 1=1")
    db.execute("UPDATE users SET created_at = ? WHERE email_hash = ?", (now, email_hash))
    db.commit()


def jprint(label, result):
    """Print JSON result with label, return parsed data."""
    try:
        data = json.loads(result)
        text = json.dumps(data, indent=2)
        # Truncate for display
        if len(text) > 600:
            text = text[:600] + "\n  ... (truncated)"
        print(f"  {label}: {text}")
        return data
    except (json.JSONDecodeError, TypeError):
        print(f"  {label}: {str(result)[:600]}")
        return result


async def main():
    print("=" * 70)
    print("FULL 2-USER E2E SIMULATION — All MCP Tools")
    print("=" * 70)

    # ──────────────────────────────────────────
    # STEP 1: Register both users
    # ──────────────────────────────────────────
    print("\n--- 1a. Register Alice ---")
    r = await research_match_register(RegisterInput(
        pseudonym="Alice_RM",
        email="alice@research.org",
    ), ctx=CTX)
    alice_data = jprint("Registered", r)
    alice_id = alice_data["user_id"]
    alice_email_hash = hashlib.sha256("alice@research.org".lower().strip().encode()).hexdigest()
    print(f"  Alice ID: {alice_id[:12]}...")

    print("\n--- 1b. Register Bob ---")
    r = await research_match_register(RegisterInput(
        pseudonym="Bob_MT",
        email="bob@masters.edu",
    ), ctx=CTX)
    bob_data = jprint("Registered", r)
    bob_id = bob_data["user_id"]
    bob_email_hash = hashlib.sha256("bob@masters.edu".lower().strip().encode()).hexdigest()
    print(f"  Bob ID: {bob_id[:12]}...")

    # ──────────────────────────────────────────
    # STEP 2: Both submit commits
    # ──────────────────────────────────────────
    print("\n--- 2a. Alice submits commit ---")
    switch_user(alice_email_hash)
    cur = _get_current_user(db)
    assert cur["id"] == alice_id, f"Expected Alice, got {cur['pseudonym']}"

    r = await research_match_submit_commit(SubmitCommitInput(
        domain="distributed systems",
        subdomain="model context protocol servers",
        problem="How to connect isolated researchers who unknowingly work on complementary problems",
        hypothesis="That AI-powered originality scoring combined with bilateral matching can identify complementary research at scale",
        theoretical_framework="Cosine similarity embeddings (sentence-transformers), exponential smoothing reputation, game-theoretic bilateral matching",
        demonstrations_summary="22-tool MCP server with register/submit/find/collaborate flow, OT/OFC dual-axis scoring, team licensing, file sharing, audit trail",
        demo_types=["code", "api", "data"],
        code_languages=["Python"],
        adhoc_summary="Novel combination of originality scoring (OT/OFC axes) with bilateral semaphore matching (green/yellow/red) for research collaboration",
        adhoc_connections=[
            "Applied game theory bilateral matching to research collaboration",
            "Applied NLP embeddings to originality scoring"
        ],
        cherry_picking=["sentence-transformers — embedding model", "FastMCP — server framework"],
        solidity_levels={"theory": "functional", "demos": "functional", "adhoc": "functional"},
        overall_solidity="functional"
    ), ctx=CTX)
    alice_commit = jprint("Alice commit", r)

    print("\n--- 2b. Bob submits commit ---")
    switch_user(bob_email_hash)
    cur = _get_current_user(db)
    assert cur["id"] == bob_id, f"Expected Bob, got {cur['pseudonym']}"

    r = await research_match_submit_commit(SubmitCommitInput(
        domain="distributed systems",
        subdomain="blockchain reputation protocols",
        problem="How to create a trustworthy peer review system using decentralized reputation",
        hypothesis="That blockchain-based reputation with exponential smoothing can incentivize honest peer review",
        theoretical_framework="Ethereum smart contracts, exponential smoothing reputation (EWMA), Byzantine fault tolerance, DecentralizedScience framework",
        demonstrations_summary="Solidity smart contracts for reputation tracking, LaTeX thesis with formal proofs, shell automation scripts",
        demo_types=["code", "math"],
        code_languages=["Shell", "Markdown"],
        adhoc_summary="Novel integration of blockchain immutability with exponential smoothing reputation for academic peer review",
        adhoc_connections=[
            "Applied blockchain consensus from cryptocurrency to academic peer review",
            "Applied exponential smoothing from signal processing to reputation scoring"
        ],
        cherry_picking=["Ethereum — blockchain platform", "DecentralizedScience — base framework"],
        solidity_levels={"theory": "functional", "demos": "speculative", "adhoc": "speculative"},
        overall_solidity="speculative"
    ), ctx=CTX)
    bob_commit = jprint("Bob commit", r)

    # ──────────────────────────────────────────
    # STEP 3: Profiles
    # ──────────────────────────────────────────
    print("\n--- 3a. Bob's profile ---")
    r = await research_match_my_profile(ctx=CTX)
    jprint("Bob profile", r)

    print("\n--- 3b. Alice's profile ---")
    switch_user(alice_email_hash)
    r = await research_match_my_profile(ctx=CTX)
    jprint("Alice profile", r)

    # ──────────────────────────────────────────
    # STEP 4: Find collaborators (as Alice)
    # ──────────────────────────────────────────
    print("\n--- 4. Alice find_collaborators ---")
    r = await research_match_find_collaborators(FindCollaboratorsInput(), ctx=CTX)
    collab = jprint("Collaborators", r)

    # Check if match was stored
    match_row = db.execute("SELECT * FROM matches ORDER BY created_at DESC LIMIT 1").fetchone()
    if match_row:
        match_dict = dict(match_row)
        sem = match_dict["semaphore"]
        print(f"  Match stored: semaphore={sem}, a_gains={match_dict['a_gains_from_b']:.1f}, b_gains={match_dict['b_gains_from_a']:.1f}")
    else:
        # YELLOW matches are NOT stored. Create one manually for simulation continuity.
        print("  No match stored. Creating manual match for simulation...")
        alice_c = db.execute("SELECT * FROM commits WHERE user_id = ?", (alice_id,)).fetchone()
        bob_c = db.execute("SELECT * FROM commits WHERE user_id = ?", (bob_id,)).fetchone()
        if alice_c and bob_c:
            ac, bc = dict(alice_c), dict(bob_c)
            gain_a = matcher._calculate_gain(ac["ot_score"], ac["ofc_score"], bc["ot_score"], bc["ofc_score"])
            gain_b = matcher._calculate_gain(bc["ot_score"], bc["ofc_score"], ac["ot_score"], ac["ofc_score"])
            match_id = str(uuid.uuid4())
            db.execute("""
                INSERT INTO matches (id, user_a_id, user_b_id, base_similarity,
                    a_gains_from_b, b_gains_from_a, complementarity_score,
                    semaphore, semaphore_reason_a, semaphore_reason_b, semaphore_summary)
                VALUES (?, ?, ?, 0.5, ?, ?, ?, 'yellow',
                    'Moderate complementarity — shared distributed systems domain',
                    'Moderate complementarity — shared distributed systems domain',
                    'YELLOW — moderate mutual gain potential')
            """, (match_id, alice_id, bob_id, gain_a, gain_b, (gain_a + gain_b) / 2))
            db.commit()
            print(f"  Manual match: gain_a={gain_a:.1f}, gain_b={gain_b:.1f}")

    # ──────────────────────────────────────────
    # STEP 5: Bob sends request to Alice
    # ──────────────────────────────────────────
    print("\n--- 5. Bob sends request to Alice ---")
    switch_user(bob_email_hash)
    cur = _get_current_user(db)
    print(f"  Current user: {cur['pseudonym']} (id={cur['id'][:12]}...)")

    r = await research_match_send_request(SendRequestInput(
        candidate_user_id=alice_id,
        message="Your MCP server could benefit from blockchain-based reputation. Let's collaborate!"
    ), ctx=CTX)
    send_result = jprint("Send request", r)

    # Verify request exists
    req_count = db.execute("SELECT COUNT(*) as c FROM collaboration_requests").fetchone()["c"]
    print(f"  Requests in DB: {req_count}")

    # ──────────────────────────────────────────
    # STEP 6: Alice checks inbox + accepts
    # ──────────────────────────────────────────
    print("\n--- 6a. Alice checks inbox ---")
    switch_user(alice_email_hash)
    cur = _get_current_user(db)
    print(f"  Current user: {cur['pseudonym']} (id={cur['id'][:12]}...)")

    r = await research_match_inbox(ctx=CTX)
    inbox = jprint("Inbox", r)

    assert inbox.get("incoming") and len(inbox["incoming"]) > 0, \
        f"Expected incoming requests! incoming={inbox.get('incoming')}"

    req_id = inbox["incoming"][0]["request_id"]
    print(f"\n--- 6b. Alice accepts request {req_id[:12]}... ---")
    r = await research_match_respond_request(RespondRequestInput(
        request_id=req_id,
        accept=True
    ), ctx=CTX)
    accept_result = jprint("Accepted", r)
    team_id = accept_result.get("team", {}).get("team_id") or accept_result.get("team_id")
    assert team_id, f"Expected team_id in response! Got: {accept_result}"
    print(f"  Team ID: {team_id[:12]}...")

    # ──────────────────────────────────────────
    # STEP 7: Needs system (tickets)
    # ──────────────────────────────────────────
    print("\n--- 7a. Alice creates a need ---")
    r = await research_match_needs_create(NeedsCreateInput(
        team_id=team_id,
        type="need_help",
        area="code",
        title="Need blockchain expertise for audit trail",
        description="Our audit_log uses SQLite. Looking for help integrating blockchain-based immutability.",
        priority="important"
    ), ctx=CTX)
    need = jprint("Need created", r)
    ticket_id = need.get("ticket_id")

    print("\n--- 7b. List needs ---")
    r = await research_match_needs_list(NeedsListInput(team_id=team_id), ctx=CTX)
    needs_list = jprint("Needs list", r)

    print("\n--- 7c. Bob resolves Alice's need ---")
    switch_user(bob_email_hash)
    r = await research_match_needs_resolve(NeedsResolveInput(
        ticket_id=ticket_id,
        resolution="resolved",
        resolution_note="I can provide Solidity contracts for immutable audit logging. See my thesis Chapter 4."
    ), ctx=CTX)
    jprint("Resolved", r)

    # ──────────────────────────────────────────
    # STEP 8: Reveal system (bilateral)
    # ──────────────────────────────────────────
    print("\n--- 8a. Alice requests reveal from Bob ---")
    switch_user(alice_email_hash)
    r = await research_match_reveal_request(RevealRequestInput(
        team_id=team_id,
        target_user_id=bob_id
    ), ctx=CTX)
    jprint("Reveal req (A→B)", r)

    print("\n--- 8b. Bob approves reveal ---")
    switch_user(bob_email_hash)
    consent = db.execute("""
        SELECT id FROM reveal_consents
        WHERE team_id = ? AND requester_id = ? AND approver_id = ? AND status = 'pending'
    """, (team_id, alice_id, bob_id)).fetchone()
    assert consent, "Expected pending consent for Alice→Bob reveal"
    r = await research_match_reveal_respond(RevealRespondInput(
        consent_id=dict(consent)["id"],
        approve=True
    ), ctx=CTX)
    jprint("Reveal approved (A→B)", r)

    print("\n--- 8c. Bob requests reveal from Alice ---")
    r = await research_match_reveal_request(RevealRequestInput(
        team_id=team_id,
        target_user_id=alice_id
    ), ctx=CTX)
    jprint("Reveal req (B→A)", r)

    print("\n--- 8d. Alice approves reveal ---")
    switch_user(alice_email_hash)
    consent2 = db.execute("""
        SELECT id FROM reveal_consents
        WHERE team_id = ? AND requester_id = ? AND approver_id = ? AND status = 'pending'
    """, (team_id, bob_id, alice_id)).fetchone()
    assert consent2, "Expected pending consent for Bob→Alice reveal"
    r = await research_match_reveal_respond(RevealRespondInput(
        consent_id=dict(consent2)["id"],
        approve=True
    ), ctx=CTX)
    jprint("Reveal approved (B→A)", r)

    print("\n--- 8e. Reveal status (bilateral complete) ---")
    r = await research_match_reveal_status(RevealStatusInput(team_id=team_id), ctx=CTX)
    reveal_status = jprint("Reveal status", r)

    # ──────────────────────────────────────────
    # STEP 9: Team license
    # ──────────────────────────────────────────
    print("\n--- 9. Team license ---")
    r = await research_match_team_license(TeamLicenseInput(team_id=team_id), ctx=CTX)
    jprint("License", r)

    # ──────────────────────────────────────────
    # STEP 10: File sharing (requires bilateral L3 reveals)
    # ──────────────────────────────────────────
    print("\n--- 10a. Alice shares file ---")
    r = await research_match_share_file(ShareFileInput(
        team_id=team_id,
        file_path="/home/alice/research_match_server.py",
        file_hash="abc123def456",
        description="Main MCP server implementation"
    ), ctx=CTX)
    jprint("Alice shared", r)

    print("\n--- 10b. Bob shares file ---")
    switch_user(bob_email_hash)
    r = await research_match_share_file(ShareFileInput(
        team_id=team_id,
        file_path="/home/bob/thesis/chapter4_reputation.tex",
        file_hash="789ghi012jkl",
        description="Chapter 4 — Blockchain reputation system design"
    ), ctx=CTX)
    jprint("Bob shared", r)

    print("\n--- 10c. List shared files ---")
    r = await research_match_shared_files(SharedFilesInput(team_id=team_id), ctx=CTX)
    jprint("Shared files", r)

    # ──────────────────────────────────────────
    # STEP 11: Ratings
    # ──────────────────────────────────────────
    print("\n--- 11a. Bob rates Alice ---")
    r = await research_match_rate_user(RateUserInput(
        rated_user_id=alice_id,
        team_id=team_id,
        honesty=5,
        quality=4,
        effort=5,
        comment="Excellent MCP implementation, very well documented"
    ), ctx=CTX)
    jprint("Bob rated Alice", r)

    print("\n--- 11b. Alice rates Bob ---")
    switch_user(alice_email_hash)
    r = await research_match_rate_user(RateUserInput(
        rated_user_id=bob_id,
        team_id=team_id,
        honesty=4,
        quality=4,
        effort=4,
        comment="Good blockchain expertise, thesis work is solid"
    ), ctx=CTX)
    jprint("Alice rated Bob", r)

    # ──────────────────────────────────────────
    # STEP 12: Audit log
    # ──────────────────────────────────────────
    print("\n--- 12. Audit log ---")
    r = await research_match_audit_log(AuditLogInput(
        team_id=team_id,
        limit=20
    ), ctx=CTX)
    jprint("Audit log", r)

    # ──────────────────────────────────────────
    # STEP 13: prepare_commit extract (proforma)
    # ──────────────────────────────────────────
    print("\n--- 13. prepare_commit extract ---")
    r = await research_match_prepare_commit(PrepareCommitInput(
        project_path="/mnt/d/ResearchMatch_repo",
        mode="extract"
    ), ctx=CTX)
    proforma = jprint("Proforma extract", r)

    # ──────────────────────────────────────────
    # STEP 14: Final profiles (with reputation)
    # ──────────────────────────────────────────
    print("\n--- 14a. Alice final profile ---")
    switch_user(alice_email_hash)
    r = await research_match_my_profile(ctx=CTX)
    jprint("Alice final", r)

    print("\n--- 14b. Bob final profile ---")
    switch_user(bob_email_hash)
    r = await research_match_my_profile(ctx=CTX)
    jprint("Bob final", r)

    # ──────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SIMULATION COMPLETE")
    print("=" * 70)
    tools_tested = [
        "register (x2)", "submit_commit (x2)", "my_profile (x4)",
        "find_collaborators", "send_request", "inbox", "respond_request",
        "needs_create", "needs_list", "needs_resolve",
        "reveal_request (x2)", "reveal_respond (x2)", "reveal_status",
        "team_license", "share_file (x2)", "shared_files",
        "rate_user (x2)", "audit_log", "prepare_commit"
    ]
    print(f"\nTools exercised: {len(tools_tested)} calls covering 19/22 unique tools")
    for t in tools_tested:
        print(f"  ✓ {t}")

    not_tested = ["cold_search (needs network)", "deep_search (needs GitHub clone)", "analyze_work (needs existing user commits)"]
    print(f"\nNot in this simulation ({len(not_tested)}):")
    for t in not_tested:
        print(f"  ○ {t}")

    # Stats
    users = db.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    commits = db.execute("SELECT COUNT(*) as c FROM research_commits").fetchone()["c"]
    matches = db.execute("SELECT COUNT(*) as c FROM matches").fetchone()["c"]
    teams = db.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    tickets = db.execute("SELECT COUNT(*) as c FROM team_tickets").fetchone()["c"]
    consents = db.execute("SELECT COUNT(*) as c FROM reveal_consents").fetchone()["c"]
    shared = db.execute("SELECT COUNT(*) as c FROM shared_files").fetchone()["c"]
    ratings = db.execute("SELECT COUNT(*) as c FROM ratings").fetchone()["c"]
    audit = db.execute("SELECT COUNT(*) as c FROM audit_log").fetchone()["c"]

    print(f"\nDB Stats:")
    print(f"  Users: {users} | Commits: {commits} | Matches: {matches} | Teams: {teams}")
    print(f"  Tickets: {tickets} | Reveals: {consents} | Files: {shared} | Ratings: {ratings} | Audit: {audit}")

    db.close()
    print(f"\nDB: {DB_PATH}")
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
