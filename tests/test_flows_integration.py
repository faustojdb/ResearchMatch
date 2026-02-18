"""
Integration tests — end-to-end flows that exercise multiple DataStore methods
in realistic sequences, simulating actual MCP tool workflows.

Requires: firebase emulators:start --only firestore
7 flows covering the full collaboration lifecycle.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from src.firestore_datastore import FirestoreDataStore


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# =====================================================================
# Flow 1: Register → Submit → My Profile
# =====================================================================


class TestFlowRegisterSubmit:
    """register → submit_commit → my_profile (verify scores + versions)"""

    async def test_register_submit_profile(self, ds: FirestoreDataStore):
        # 1. Register user
        uid = _uid()
        await ds.insert_user(uid, "researcher_alice", "hash_alice_flow")
        user = await ds.get_user_by_id(uid)
        assert user is not None
        assert user["pseudonym"] == "researcher_alice"
        assert user["reputation_score"] == 100.0

        # 2. Submit commit v1
        cid1 = _uid()
        commit1 = {
            "id": cid1, "user_id": uid, "version": 1,
            "domain": "machine learning", "subdomain": "privacy",
            "problem": "Data sharing without privacy loss",
            "hypothesis": "Federated learning preserves privacy",
            "overall_solidity": "functional",
            "ot_score": 63.3, "ofc_score": 55.7,
        }
        await ds.submit_commit_and_mark_latest(commit1)

        # 3. Verify profile shows commit
        latest = await ds.get_latest_commit_by_user(uid)
        assert latest is not None
        assert latest["version"] == 1
        assert latest["is_latest"] is True

        scores = await ds.get_latest_scores_by_user(uid)
        assert scores["ot_score"] == 63.3

        # 4. Submit commit v2 → verify v1 marked not-latest
        cid2 = _uid()
        commit2 = {
            "id": cid2, "user_id": uid, "version": 2,
            "domain": "machine learning", "subdomain": "privacy",
            "problem": "Enhanced problem",
            "hypothesis": "Improved hypothesis",
            "overall_solidity": "strong",
            "ot_score": 72.0, "ofc_score": 68.0,
        }
        await ds.submit_commit_and_mark_latest(commit2, previous_commit_id=cid1)

        c1 = await ds.get_commit_by_id(cid1)
        c2 = await ds.get_commit_by_id(cid2)
        assert c1["is_latest"] is False
        assert c2["is_latest"] is True

        # 5. Version history
        all_commits = await ds.get_all_commits_by_user(uid)
        assert len(all_commits) == 2
        assert all_commits[0]["version"] == 2  # DESC order


# =====================================================================
# Flow 2: Register x2 → Submit x2 → Find Collaborators → Request → Respond
# =====================================================================


class TestFlowMatchingCollaboration:
    """Full matching + collaboration lifecycle"""

    async def test_matching_and_team_creation(self, ds: FirestoreDataStore):
        # 1. Register users A and B
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "alice_ml", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "bob_ml", f"h_{uid_b[:8]}")

        # 2. Both submit commits in same domain
        cid_a = _uid()
        await ds.submit_commit_and_mark_latest({
            "id": cid_a, "user_id": uid_a, "version": 1,
            "domain": "machine learning", "subdomain": "nlp",
            "problem": "Text classification", "hypothesis": "Transformers",
            "overall_solidity": "functional", "ot_score": 60, "ofc_score": 55,
        })
        cid_b = _uid()
        await ds.submit_commit_and_mark_latest({
            "id": cid_b, "user_id": uid_b, "version": 1,
            "domain": "machine learning", "subdomain": "cv",
            "problem": "Image segmentation", "hypothesis": "U-Net",
            "overall_solidity": "strong", "ot_score": 70, "ofc_score": 65,
        })

        # 3. Find collaborators for user A
        candidates = await ds.find_candidate_commits_in_domain(uid_a, "machine learning")
        assert len(candidates) == 1
        assert candidates[0]["pseudonym"] == "bob_ml"

        # 4. Create match record (simulating MatchingEngine output)
        mid = _uid()
        await ds.upsert_match({
            "id": mid, "user_a_id": uid_a, "user_b_id": uid_b,
            "semaphore": "GREEN", "complementarity_score": 82.5,
            "a_gains_from_b": 12, "b_gains_from_a": 9,
            "semaphore_reason_a": "Strong CV complement",
            "semaphore_reason_b": "NLP expertise helps",
        })

        # 5. User A sends collaboration request
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "Want to collaborate on ML?")

        # 6. User B checks inbox
        inbox = await ds.get_incoming_requests(uid_b)
        assert len(inbox) == 1
        assert inbox[0]["requester_pseudonym"] == "alice_ml"
        assert inbox[0]["semaphore"] == "GREEN"

        # User A checks outgoing
        outgoing = await ds.get_outgoing_requests(uid_a)
        assert len(outgoing) == 1
        assert outgoing[0]["recipient_pseudonym"] == "bob_ml"

        # 7. User B accepts → create team
        await ds.update_request_status(rid, "accepted")
        tid = _uid()
        await ds.create_team_with_members(tid, "alice_ml × bob_ml", "joint-equal", [uid_a, uid_b])

        # 8. Verify team
        team = await ds.get_team_by_id(tid)
        assert team["name"] == "alice_ml × bob_ml"
        members = await ds.get_team_member_ids(tid)
        assert set(members) == {uid_a, uid_b}

        # 9. Both can see team
        teams_a = await ds.get_teams_for_user(uid_a)
        teams_b = await ds.get_teams_for_user(uid_b)
        assert len(teams_a) == 1
        assert len(teams_b) == 1

        # 10. No more pending requests
        pending = await ds.find_pending_request(uid_a, uid_b)
        assert pending is None


# =====================================================================
# Flow 3: Bilateral Ratings → Reputation Update
# =====================================================================


class TestFlowRatings:
    """rate_user bilateral → reputation update → reveal"""

    async def test_bilateral_ratings_and_reputation(self, ds: FirestoreDataStore):
        # Setup team
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "rater_alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "rater_bob", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Rating Team", "joint-equal", [uid_a, uid_b])

        # 1. User A rates user B
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 5, "quality": 4, "effort": 4, "comment": "Great work",
        })

        # Rating not yet revealed (unilateral)
        r_ab = await ds.find_rating(tid, uid_a, uid_b)
        assert r_ab["is_revealed"] == 0

        # 2. User B rates user A
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_b, "rated_id": uid_a,
            "honesty": 4, "quality": 5, "effort": 3, "comment": "Nice",
        })

        # Both rated → check counts
        assert await ds.count_ratings_received(uid_a) == 1
        assert await ds.count_ratings_received(uid_b) == 1

        # 3. Reveal ratings (bilateral complete)
        await ds.reveal_team_ratings(tid)
        r_ab = await ds.find_rating(tid, uid_a, uid_b)
        r_ba = await ds.find_rating(tid, uid_b, uid_a)
        assert r_ab["is_revealed"] == 1
        assert r_ba["is_revealed"] == 1

        # 4. Simulate reputation update (ReputationEngine would do this)
        await ds.update_user_running_averages(uid_b, 5.0, 4.0, 4.0)
        await ds.update_user_reputation_stats(uid_b, 95.0, 1, 5.0, 4.0, 4.0)

        user_b = await ds.get_user_by_id(uid_b)
        assert user_b["reputation_score"] == 95.0
        assert user_b["total_ratings_received"] == 1

        # 5. Check rating history
        received = await ds.get_ratings_received_desc(uid_b)
        assert len(received) == 1
        given = await ds.get_ratings_given_desc(uid_a)
        assert len(given) == 1


# =====================================================================
# Flow 4: Reveal Request → Respond → Status (bilateral)
# =====================================================================


class TestFlowReveals:
    """reveal_request → reveal_respond → reveal_status (bilateral)"""

    async def test_bilateral_reveal_flow(self, ds: FirestoreDataStore):
        # Setup team with commits
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "reveal_alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "reveal_bob", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Reveal Team", "joint-equal", [uid_a, uid_b])

        # Both have commits
        cid_a, cid_b = _uid(), _uid()
        await ds.submit_commit_and_mark_latest({
            "id": cid_a, "user_id": uid_a, "version": 1, "domain": "ml",
            "problem": "secret A", "hypothesis": "h_a",
            "overall_solidity": "functional", "ot_score": 60, "ofc_score": 55,
        })
        await ds.submit_commit_and_mark_latest({
            "id": cid_b, "user_id": uid_b, "version": 1, "domain": "ml",
            "problem": "secret B", "hypothesis": "h_b",
            "overall_solidity": "strong", "ot_score": 70, "ofc_score": 65,
        })

        # 1. A requests to see B's commit
        consent_ab = _uid()
        await ds.insert_reveal_consent({
            "id": consent_ab, "team_id": tid, "level": 3,
            "requester_id": uid_a, "approver_id": uid_b,
            "resource_type": "commit", "resource_ref": cid_b,
        })
        assert await ds.count_pending_reveals(tid) == 1

        # 2. B approves
        await ds.update_reveal_consent_status(consent_ab, "approved", team_id=tid)
        assert await ds.count_pending_reveals(tid) == 0

        # A can now see B's stuff
        can_see = await ds.get_reveal_can_see(tid, uid_a)
        assert "reveal_bob" in can_see

        # 3. B requests to see A's commit (reverse direction)
        consent_ba = _uid()
        await ds.insert_reveal_consent({
            "id": consent_ba, "team_id": tid, "level": 3,
            "requester_id": uid_b, "approver_id": uid_a,
            "resource_type": "commit", "resource_ref": cid_a,
        })

        # 4. A approves
        await ds.update_reveal_consent_status(consent_ba, "approved", team_id=tid)

        # 5. Verify bilateral reveals complete
        count_ab = await ds.count_approved_reveals_direction(tid, uid_b, uid_a)
        count_ba = await ds.count_approved_reveals_direction(tid, uid_a, uid_b)
        assert count_ab == 1  # B approved A's request
        assert count_ba == 1  # A approved B's request

        # Both can see each other
        a_sees = await ds.get_reveal_can_see(tid, uid_a)
        b_sees = await ds.get_reveal_can_see(tid, uid_b)
        assert "reveal_bob" in a_sees
        assert "reveal_alice" in b_sees

        # 6. Check consents with pseudonyms
        consents = await ds.get_team_consents_with_pseudonyms(tid)
        assert len(consents) == 2
        pseudonyms = {c["requester_pseudonym"] for c in consents}
        assert pseudonyms == {"reveal_alice", "reveal_bob"}


# =====================================================================
# Flow 5: Ticket Lifecycle
# =====================================================================


class TestFlowTickets:
    """needs_create → needs_list → needs_resolve → effort boost"""

    async def test_ticket_lifecycle(self, ds: FirestoreDataStore):
        # Setup
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "ticket_alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "ticket_bob", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Ticket Team", "joint-equal", [uid_a, uid_b])

        # 1. Alice creates a ticket
        t1_id = _uid()
        await ds.insert_ticket({
            "id": t1_id, "team_id": tid, "author_id": uid_a,
            "type": "need_help", "area": "code",
            "title": "Help with data pipeline",
            "description": "Need help building ETL pipeline",
            "priority": "critical",
        })

        # 2. Alice creates another ticket
        t2_id = _uid()
        await ds.insert_ticket({
            "id": t2_id, "team_id": tid, "author_id": uid_a,
            "type": "question", "area": "theory",
            "title": "Question about convergence",
            "description": "Is gradient descent guaranteed to converge?",
            "priority": "nice_to_have",
        })

        # 3. List all tickets
        all_tickets = await ds.list_tickets(tid)
        assert len(all_tickets) == 2
        # Critical should come first (sorted by priority)
        assert all_tickets[0]["priority"] == "critical"

        # 4. Filter by area
        code_tickets = await ds.list_tickets_with_filters(tid, area="code")
        assert len(code_tickets) == 1

        # 5. Open ticket count
        assert await ds.count_open_tickets_by_author(tid, uid_a) == 2

        # 6. Bob resolves the critical ticket
        await ds.resolve_ticket(t1_id, uid_b)
        ticket = await ds.get_ticket_by_id(t1_id)
        assert ticket["status"] == "resolved"
        assert ticket["resolved_by"] == uid_b

        # 7. Check resolved count
        assert await ds.count_resolved_tickets_by_member(tid, uid_b) == 1
        assert await ds.count_open_tickets_by_author(tid, uid_a) == 1

        # 8. Status summary
        summary = await ds.get_ticket_status_summary(tid)
        status_map = {s["status"]: s["c"] for s in summary}
        assert status_map["open"] == 1
        assert status_map["resolved"] == 1

        # 9. Simulate effort boost for resolver
        await ds.update_user_running_effort(uid_b, 4.5)
        effort = await ds.get_user_running_effort(uid_b)
        assert effort == 4.5


# =====================================================================
# Flow 6: Contract Lifecycle (bilateral confirmation)
# =====================================================================


class TestFlowContracts:
    """export_contract → confirm bilateral → verified"""

    async def test_bilateral_contract_confirmation(self, ds: FirestoreDataStore):
        # Setup team with bilateral reveals
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "contract_alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "contract_bob", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Contract Team", "joint-equal", [uid_a, uid_b])

        # 1. Export contract v1
        contract_v = await ds.get_next_contract_version(tid)
        assert contract_v == 1

        cid = _uid()
        await ds.insert_contract({
            "id": cid, "team_id": tid, "contract_version": 1,
            "content_hash": "sha256_abc123", "content": "# Collaboration Contract\n...",
            "status": "pending",
            "confirmation_a_user_id": None, "confirmation_a_git_hash": None,
            "confirmation_a_repo_url": None, "confirmation_a_at": None,
            "confirmation_b_user_id": None, "confirmation_b_git_hash": None,
            "confirmation_b_repo_url": None, "confirmation_b_at": None,
        })

        # 2. User A confirms with git hash
        now = _now()
        await ds.update_contract_confirmation_a(
            cid, uid_a, "abc123def456", "https://github.com/alice/repo", now
        )
        await ds.update_contract_status(cid, "partial")

        c = await ds.get_contract_by_id(cid)
        assert c["status"] == "partial"
        assert c["confirmation_a_user_id"] == uid_a

        # 3. User B confirms
        await ds.update_contract_confirmation_b(
            cid, uid_b, "789xyz000111", "https://github.com/bob/repo", now
        )
        await ds.update_contract_status(cid, "confirmed")

        c = await ds.get_contract_by_id(cid)
        assert c["status"] == "confirmed"
        assert c["confirmation_b_git_hash"] == "789xyz000111"

        # 4. Count confirmed
        assert await ds.count_confirmed_contracts_for_team(tid) == 1
        assert await ds.count_confirmed_contracts() == 1

        # 5. Export v2 supersedes v1 pending/partial
        cid2 = _uid()
        await ds.insert_contract({
            "id": cid2, "team_id": tid, "contract_version": 2,
            "content_hash": "sha256_def456", "content": "# Updated Contract",
            "status": "pending",
            "confirmation_a_user_id": None, "confirmation_a_git_hash": None,
            "confirmation_a_repo_url": None, "confirmation_a_at": None,
            "confirmation_b_user_id": None, "confirmation_b_git_hash": None,
            "confirmation_b_repo_url": None, "confirmation_b_at": None,
        })
        # Supersede only pending/partial (confirmed v1 should stay)
        await ds.supersede_pending_contracts(tid)
        c2 = await ds.get_contract_by_id(cid2)
        assert c2["status"] == "superseded"
        # v1 (confirmed) untouched
        c1 = await ds.get_contract_by_id(cid)
        assert c1["status"] == "confirmed"

    async def test_contract_confirmation_via_unified_alias(self, ds: FirestoreDataStore):
        """Test the update_contract_confirmation alias that dispatches to slot a/b"""
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "alias_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "alias_b", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Alias Team", "joint-equal", [uid_a, uid_b])

        cid = _uid()
        await ds.insert_contract({
            "id": cid, "team_id": tid, "contract_version": 1,
            "content_hash": "hash", "content": "content", "status": "pending",
            "confirmation_a_user_id": None, "confirmation_a_git_hash": None,
            "confirmation_a_repo_url": None, "confirmation_a_at": None,
            "confirmation_b_user_id": None, "confirmation_b_git_hash": None,
            "confirmation_b_repo_url": None, "confirmation_b_at": None,
        })

        now = _now()
        await ds.update_contract_confirmation(cid, "a", uid_a, "hash_a", "url_a", now)
        await ds.update_contract_confirmation(cid, "b", uid_b, "hash_b", "url_b", now)

        c = await ds.get_contract_by_id(cid)
        assert c["confirmation_a_user_id"] == uid_a
        assert c["confirmation_b_user_id"] == uid_b


# =====================================================================
# Flow 7: File Sharing + Resharing Detection
# =====================================================================


class TestFlowSharedFiles:
    """share_file → shared_files → resharing detection via hash"""

    async def test_file_sharing_and_resharing_detection(self, ds: FirestoreDataStore):
        # Setup: two teams, 3 users
        uid_a, uid_b, uid_c = _uid(), _uid(), _uid()
        await ds.insert_user(uid_a, "file_alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "file_bob", f"h_{uid_b[:8]}")
        await ds.insert_user(uid_c, "file_carol", f"h_{uid_c[:8]}")

        tid1 = _uid()
        await ds.create_team_with_members(tid1, "Team AB", "joint-equal", [uid_a, uid_b])
        tid2 = _uid()
        await ds.create_team_with_members(tid2, "Team AC", "joint-equal", [uid_a, uid_c])

        # 1. Alice shares a file in Team AB
        fid1 = _uid()
        await ds.insert_shared_file({
            "id": fid1, "team_id": tid1, "shared_by": uid_a,
            "file_path": "/src/model.py", "file_hash": "sha256_model_abc",
            "description": "ML model implementation", "origin_user_id": uid_a,
        })

        # 2. Verify file is listed
        files = await ds.list_shared_files_with_pseudonyms(tid1)
        assert len(files) == 1
        assert files[0]["shared_by_pseudonym"] == "file_alice"
        assert files[0]["file_path"] == "/src/model.py"

        # 3. Idempotent check — same path
        existing = await ds.find_shared_file(tid1, uid_a, "/src/model.py")
        assert existing is not None

        # 4. File count
        assert await ds.count_shared_files_in_team(tid1) == 1
        assert await ds.count_shared_files() == 1  # global

        # 5. Resharing detection: Alice shares same hash in Team AC
        # (simulating _check_resharing_violation)
        violation = await ds.find_file_by_hash_other_user("sha256_model_abc", uid_c)
        # uid_c is NOT the origin → should find alice's file
        assert violation is not None
        assert violation["origin_user_id"] == uid_a

        # Alice searches her own hash → should NOT find (same user)
        no_violation = await ds.find_file_by_hash_other_user("sha256_model_abc", uid_a)
        assert no_violation is None

        # 6. Add more files and verify counts
        await ds.insert_shared_file({
            "id": _uid(), "team_id": tid1, "shared_by": uid_b,
            "file_path": "/data/train.csv", "file_hash": "sha256_data_xyz",
            "description": "Training data", "origin_user_id": uid_b,
        })
        assert await ds.count_shared_files_in_team(tid1) == 2

        # 7. Audit trail for file sharing
        await ds.insert_audit_entry(
            _uid(), tid1, uid_a, "file_shared", fid1, "Shared model.py"
        )
        entries = await ds.list_audit_entries(tid1)
        assert len(entries) == 1
        assert entries[0]["action"] == "file_shared"

    async def test_file_sharing_cross_team_isolation(self, ds: FirestoreDataStore):
        """Files in one team are not visible in another team's listing"""
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "iso_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "iso_b", f"h_{uid_b[:8]}")

        tid1 = _uid()
        tid2 = _uid()
        await ds.create_team_with_members(tid1, "Team1", "joint-equal", [uid_a, uid_b])
        await ds.create_team_with_members(tid2, "Team2", "joint-equal", [uid_a, uid_b])

        await ds.insert_shared_file({
            "id": _uid(), "team_id": tid1, "shared_by": uid_a,
            "file_path": "/secret.py", "file_hash": "hash_secret",
            "description": "secret", "origin_user_id": uid_a,
        })

        # Team 1 has file, Team 2 does not
        assert await ds.count_shared_files_in_team(tid1) == 1
        assert await ds.count_shared_files_in_team(tid2) == 0


# =====================================================================
# Flow 8: Full Lifecycle (register → contract confirmed)
# =====================================================================


class TestFlowFullLifecycle:
    """Complete lifecycle: register → submit → match → request → accept →
       reveal → rate → ticket → license → file share → contract"""

    async def test_complete_lifecycle(self, ds: FirestoreDataStore):
        # --- REGISTER ---
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "lifecycle_alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "lifecycle_bob", f"h_{uid_b[:8]}")

        # --- SUBMIT COMMITS ---
        cid_a, cid_b = _uid(), _uid()
        await ds.submit_commit_and_mark_latest({
            "id": cid_a, "user_id": uid_a, "version": 1, "domain": "biology",
            "problem": "Gene editing safety", "hypothesis": "CRISPR off-target",
            "overall_solidity": "functional", "ot_score": 65, "ofc_score": 60,
        })
        await ds.submit_commit_and_mark_latest({
            "id": cid_b, "user_id": uid_b, "version": 1, "domain": "biology",
            "problem": "Protein folding", "hypothesis": "AlphaFold limits",
            "overall_solidity": "strong", "ot_score": 75, "ofc_score": 70,
        })

        # --- MATCH ---
        mid = _uid()
        await ds.upsert_match({
            "id": mid, "user_a_id": uid_a, "user_b_id": uid_b,
            "semaphore": "GREEN", "complementarity_score": 88,
            "a_gains_from_b": 15, "b_gains_from_a": 10,
            "semaphore_reason_a": "Protein folding is complementary",
            "semaphore_reason_b": "Gene editing adds safety angle",
        })

        # --- REQUEST + ACCEPT ---
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "Let's work together")
        await ds.update_request_status(rid, "accepted")
        tid = _uid()
        await ds.create_team_with_members(tid, "lifecycle_alice × lifecycle_bob", "joint-equal", [uid_a, uid_b])

        # --- REVEALS (bilateral) ---
        c_ab = _uid()
        await ds.insert_reveal_consent({
            "id": c_ab, "team_id": tid, "level": 3,
            "requester_id": uid_a, "approver_id": uid_b,
            "resource_type": "commit", "resource_ref": cid_b,
        })
        await ds.update_reveal_consent_status(c_ab, "approved", team_id=tid)

        c_ba = _uid()
        await ds.insert_reveal_consent({
            "id": c_ba, "team_id": tid, "level": 3,
            "requester_id": uid_b, "approver_id": uid_a,
            "resource_type": "commit", "resource_ref": cid_a,
        })
        await ds.update_reveal_consent_status(c_ba, "approved", team_id=tid)

        # --- RATINGS ---
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 5, "quality": 5, "effort": 4, "comment": "Excellent",
        })
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_b, "rated_id": uid_a,
            "honesty": 4, "quality": 4, "effort": 5, "comment": "Hardworking",
        })
        await ds.reveal_team_ratings(tid)

        # --- TICKET ---
        tkt_id = _uid()
        await ds.insert_ticket({
            "id": tkt_id, "team_id": tid, "author_id": uid_a,
            "type": "need_help", "area": "code", "title": "Need pipeline",
            "description": "Build data pipeline", "priority": "important",
        })
        await ds.resolve_ticket(tkt_id, uid_b)

        # --- LICENSE UPDATE ---
        await ds.update_team_license(tid, "joint-weighted")
        await ds.update_member_contribution(tid, uid_a, 55.0)
        await ds.update_member_contribution(tid, uid_b, 45.0)
        await ds.insert_audit_entry(
            _uid(), tid, uid_a, "license_generated", None,
            '{"type":"joint-weighted","splits":{"alice":55,"bob":45}}'
        )

        # --- FILE SHARING ---
        await ds.insert_shared_file({
            "id": _uid(), "team_id": tid, "shared_by": uid_a,
            "file_path": "/src/crispr.py", "file_hash": "hash_crispr",
            "description": "CRISPR analysis code", "origin_user_id": uid_a,
        })

        # --- CONTRACT ---
        contract_id = _uid()
        await ds.insert_contract({
            "id": contract_id, "team_id": tid, "contract_version": 1,
            "content_hash": "sha256_full_contract",
            "content": "# Full Collaboration Contract",
            "status": "pending",
            "confirmation_a_user_id": None, "confirmation_a_git_hash": None,
            "confirmation_a_repo_url": None, "confirmation_a_at": None,
            "confirmation_b_user_id": None, "confirmation_b_git_hash": None,
            "confirmation_b_repo_url": None, "confirmation_b_at": None,
        })
        now = _now()
        await ds.update_contract_confirmation(contract_id, "a", uid_a, "aaa111", "url_a", now)
        await ds.update_contract_confirmation(contract_id, "b", uid_b, "bbb222", "url_b", now)
        await ds.update_contract_status(contract_id, "confirmed")

        # --- VERIFY FINAL STATE ---
        stats = await ds.health_stats()
        assert stats["users"] == 2
        assert stats["commits"] == 2
        assert stats["matches"] == 1
        assert stats["teams"] == 1
        assert stats["ratings"] == 2
        assert stats["tickets"] == 1
        assert stats["shared_files"] == 1
        assert stats["confirmed_contracts"] == 1

        # License
        license_type = await ds.get_team_license_type(tid)
        assert license_type == "joint-weighted"

        # Contributions
        profiles = await ds.get_team_members_with_profiles(tid)
        contribs = {p["pseudonym"]: p.get("contribution_percentage") for p in profiles}
        assert contribs["lifecycle_alice"] == 55.0
        assert contribs["lifecycle_bob"] == 45.0

        # Audit trail
        audit = await ds.list_audit_entries(tid)
        assert len(audit) >= 1
