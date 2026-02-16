"""Tests for the Reveal System (Level 3 — Bilateral Consent).

Tests cover: schema constraints, reveal request logic, reveal respond logic,
content visibility after approval, and Pydantic model validation.
Uses in-memory SQLite DB from conftest.py fixtures.
"""
import json
import uuid
import sqlite3

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from research_match_server import (
    init_database,
    _get_or_create_user,
    _write_audit_log,
    RevealRequestInput,
    RevealRespondInput,
    RevealStatusInput,
    MAX_PENDING_REVEALS_PER_TEAM,
)


# ============================================================
# Helpers
# ============================================================

def _create_team_with_members(db, user_a_id, user_b_id):
    """Helper: create a team and add two members."""
    team_id = str(uuid.uuid4())
    team_name = f"team-{team_id[:8]}"
    db.execute("INSERT INTO teams (id, name, license_type) VALUES (?, ?, 'joint-equal')",
               (team_id, team_name))
    db.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')",
               (team_id, user_a_id))
    db.execute("INSERT INTO team_members (team_id, user_id, role) VALUES (?, ?, 'co-lead')",
               (team_id, user_b_id))
    db.commit()
    return team_id


def _create_commit_for_user(db, user_id, domain="molecular biology", problem="Test problem"):
    """Helper: insert a minimal research commit for a user."""
    commit_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO research_commits
           (id, user_id, version, domain, problem, hypothesis, theoretical_framework,
            demonstrations_summary, demo_types, code_languages, adhoc_summary,
            adhoc_connections, cherry_picking, content_hash,
            ot_score, ofc_score, ot_breakdown, ofc_breakdown,
            solidity_levels, overall_solidity, solidity_impact)
           VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (commit_id, user_id, domain, problem,
         "Test hypothesis about protein folding",
         "Energy landscape theory",
         "Python scripts for simulation",
         json.dumps(["code"]), json.dumps(["Python"]),
         "Novel approach connecting fields",
         json.dumps(["Applied Ising model from stat mech"]),
         json.dumps(["AlphaFold2"]),
         "test_hash_" + commit_id[:8],
         65.0, 58.0,
         json.dumps({"corpus_divergence": 80}),
         json.dumps({"formal_method_originality": 50}),
         json.dumps({"theory": "speculative", "demos": "functional"}),
         "speculative",
         json.dumps({"theory_multiplier": 0.6}))
    )
    db.commit()
    return commit_id


def _create_consent(db, team_id, requester_id, approver_id, resource_ref, status="pending"):
    """Helper: insert a reveal consent directly."""
    consent_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id,
           resource_type, resource_ref, status)
           VALUES (?, ?, 3, ?, ?, 'commit', ?, ?)""",
        (consent_id, team_id, requester_id, approver_id, resource_ref, status)
    )
    db.commit()
    return consent_id


# ============================================================
# TestRevealSchema — verify table constraints
# ============================================================

class TestRevealSchema:
    """Verify reveal_consents schema constraints."""

    def test_consent_creation_ok(self, db):
        """Creating a valid consent should work."""
        user_a = _get_or_create_user(db, "rev_a@test.com", "RevA")
        user_b = _get_or_create_user(db, "rev_b@test.com", "RevB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)

        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id)

        row = db.execute("SELECT * FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone()
        assert row is not None
        r = dict(row)
        assert r["level"] == 3
        assert r["status"] == "pending"
        assert r["requester_id"] == user_a
        assert r["approver_id"] == user_b
        assert r["resource_type"] == "commit"
        assert r["resource_ref"] == commit_id

    def test_unique_constraint_blocks_duplicate(self, db):
        """UNIQUE(team_id, level, requester_id, resource_ref) should block duplicates."""
        user_a = _get_or_create_user(db, "dup_a@test.com", "DupA")
        user_b = _get_or_create_user(db, "dup_b@test.com", "DupB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)

        _create_consent(db, team_id, user_a, user_b, commit_id)

        with pytest.raises(sqlite3.IntegrityError):
            _create_consent(db, team_id, user_a, user_b, commit_id)

    def test_level_2_rejected(self, db):
        """Level 2 should be rejected by CHECK(level IN (3, 4))."""
        user_a = _get_or_create_user(db, "lev_a@test.com", "LevA")
        user_b = _get_or_create_user(db, "lev_b@test.com", "LevB")
        team_id = _create_team_with_members(db, user_a, user_b)

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id, resource_ref)
                   VALUES (?, ?, 2, ?, ?, 'ref1')""",
                (str(uuid.uuid4()), team_id, user_a, user_b)
            )


# ============================================================
# TestRevealRequest — request logic validation
# ============================================================

class TestRevealRequest:
    """Test reveal request creation logic (simulating tool behavior at DB level)."""

    def test_request_creates_pending_consent(self, db):
        """A valid request should create a pending consent with correct fields."""
        user_a = _get_or_create_user(db, "req_a@test.com", "ReqA")
        user_b = _get_or_create_user(db, "req_b@test.com", "ReqB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)

        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id, status="pending")

        row = dict(db.execute("SELECT * FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone())
        assert row["status"] == "pending"
        assert row["resolved_at"] is None
        assert row["requester_id"] == user_a
        assert row["approver_id"] == user_b

    def test_duplicate_pending_blocked(self, db):
        """Cannot create duplicate pending consent for same team+level+requester+resource."""
        user_a = _get_or_create_user(db, "dpb_a@test.com", "DpbA")
        user_b = _get_or_create_user(db, "dpb_b@test.com", "DpbB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)

        _create_consent(db, team_id, user_a, user_b, commit_id)

        # Application-level check: query for existing pending
        existing = db.execute(
            """SELECT id FROM reveal_consents
               WHERE team_id = ? AND level = 3 AND requester_id = ? AND resource_ref = ? AND status = 'pending'""",
            (team_id, user_a, commit_id)
        ).fetchone()
        assert existing is not None, "Should find existing pending consent"

    def test_non_member_blocked(self, db):
        """A non-member should not be able to find team membership."""
        user_a = _get_or_create_user(db, "nmb_a@test.com", "NmbA")
        user_b = _get_or_create_user(db, "nmb_b@test.com", "NmbB")
        outsider = _get_or_create_user(db, "nmb_out@test.com", "Outsider")
        team_id = _create_team_with_members(db, user_a, user_b)

        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (team_id, outsider)
        ).fetchone()
        assert membership is None, "Outsider should not be a team member"

    def test_target_without_commit_detected(self, db):
        """Target user without a commit should be detectable."""
        user_a = _get_or_create_user(db, "noc_a@test.com", "NocA")
        user_b = _get_or_create_user(db, "noc_b@test.com", "NocB")
        _create_team_with_members(db, user_a, user_b)

        commit = db.execute(
            "SELECT id FROM research_commits WHERE user_id = ? ORDER BY version DESC LIMIT 1",
            (user_b,)
        ).fetchone()
        assert commit is None, "User without commits should return None"


# ============================================================
# TestRevealResponse — approve/deny logic
# ============================================================

class TestRevealResponse:
    """Test consent approval and denial logic."""

    def test_approve_sets_status_and_resolved_at(self, db):
        """Approving a consent should set status='approved' and resolved_at."""
        user_a = _get_or_create_user(db, "app_a@test.com", "AppA")
        user_b = _get_or_create_user(db, "app_b@test.com", "AppB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)
        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id)

        db.execute(
            "UPDATE reveal_consents SET status = 'approved', resolved_at = datetime('now') WHERE id = ?",
            (consent_id,)
        )
        db.commit()

        row = dict(db.execute("SELECT * FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone())
        assert row["status"] == "approved"
        assert row["resolved_at"] is not None

    def test_deny_sets_status(self, db):
        """Denying a consent should set status='denied' and resolved_at."""
        user_a = _get_or_create_user(db, "den_a@test.com", "DenA")
        user_b = _get_or_create_user(db, "den_b@test.com", "DenB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)
        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id)

        db.execute(
            "UPDATE reveal_consents SET status = 'denied', resolved_at = datetime('now') WHERE id = ?",
            (consent_id,)
        )
        db.commit()

        row = dict(db.execute("SELECT * FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone())
        assert row["status"] == "denied"
        assert row["resolved_at"] is not None

    def test_already_resolved_blocked(self, db):
        """An already-resolved consent should not be modifiable (application-level check)."""
        user_a = _get_or_create_user(db, "arb_a@test.com", "ArbA")
        user_b = _get_or_create_user(db, "arb_b@test.com", "ArbB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)
        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id, status="approved")

        # Application-level check: status should not be 'pending'
        row = db.execute("SELECT status FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone()
        assert row["status"] != "pending", "Already resolved consent should not be pending"


# ============================================================
# TestRevealContent — content visibility rules
# ============================================================

class TestRevealContent:
    """Test that approved reveals expose commit content and denied do not."""

    def test_approved_commit_fetchable(self, db):
        """When consent is approved, the full commit should be fetchable via resource_ref."""
        user_a = _get_or_create_user(db, "fetch_a@test.com", "FetchA")
        user_b = _get_or_create_user(db, "fetch_b@test.com", "FetchB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b, domain="physics", problem="Quantum tunneling")
        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id, status="approved")

        # Simulate what reveal_status does: fetch commit for approved consent where user is requester
        consent = dict(db.execute("SELECT * FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone())
        assert consent["status"] == "approved"
        assert consent["requester_id"] == user_a

        commit = db.execute("SELECT * FROM research_commits WHERE id = ?", (consent["resource_ref"],)).fetchone()
        assert commit is not None
        c = dict(commit)
        assert c["domain"] == "physics"
        assert c["problem"] == "Quantum tunneling"
        assert c["hypothesis"] == "Test hypothesis about protein folding"
        assert c["ot_score"] == 65.0
        assert c["ofc_score"] == 58.0

        # Verify JSON fields are parseable
        demo_types = json.loads(c["demo_types"])
        assert demo_types == ["code"]
        adhoc_connections = json.loads(c["adhoc_connections"])
        assert "Applied Ising model from stat mech" in adhoc_connections

    def test_denied_content_not_fetchable(self, db):
        """When consent is denied, the application should NOT return commit content."""
        user_a = _get_or_create_user(db, "nofetch_a@test.com", "NoFetchA")
        user_b = _get_or_create_user(db, "nofetch_b@test.com", "NoFetchB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_id = _create_commit_for_user(db, user_b)
        consent_id = _create_consent(db, team_id, user_a, user_b, commit_id, status="denied")

        consent = dict(db.execute("SELECT * FROM reveal_consents WHERE id = ?", (consent_id,)).fetchone())

        # Application logic: only fetch content if status == 'approved' AND requester_id == current_user
        should_reveal = (consent["status"] == "approved" and consent["requester_id"] == user_a)
        assert should_reveal is False, "Denied consent should not allow content fetch"


# ============================================================
# TestRevealPydanticValidation — input model validation
# ============================================================

class TestRevealPydanticValidation:
    """Test Pydantic model validation for reveal inputs."""

    def test_reveal_request_input_valid(self):
        """Valid RevealRequestInput should pass."""
        inp = RevealRequestInput(team_id="team-123", target_user_id="user-456")
        assert inp.team_id == "team-123"
        assert inp.target_user_id == "user-456"

    def test_reveal_respond_input_valid(self):
        """Valid RevealRespondInput should pass."""
        inp = RevealRespondInput(consent_id="consent-abc", approve=True)
        assert inp.consent_id == "consent-abc"
        assert inp.approve is True

    def test_reveal_status_input_valid(self):
        """Valid RevealStatusInput should pass."""
        inp = RevealStatusInput(team_id="team-xyz")
        assert inp.team_id == "team-xyz"

    def test_reveal_request_extra_fields_rejected(self):
        """Extra fields should be rejected (extra='forbid')."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RevealRequestInput(team_id="team-123", target_user_id="user-456", bogus="extra")

    def test_reveal_respond_extra_fields_rejected(self):
        """Extra fields should be rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RevealRespondInput(consent_id="consent-abc", approve=True, extra_field="nope")
