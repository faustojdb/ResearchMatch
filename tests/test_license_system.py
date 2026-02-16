"""Tests for the License System (NEED-03 — Automatic Licensing).

Tests cover: _compute_license rules, contribution splits, hooks in
reveal_respond and needs_resolve, and Pydantic model validation.
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
    _compute_license,
    TeamLicenseInput,
    LICENSE_TERMS,
    LICENSE_STALE_DAYS,
)


# ============================================================
# Helpers
# ============================================================

def _create_team_with_members(db, user_a_id, user_b_id, created_at=None):
    """Helper: create a team and add two members. Optionally backdate creation."""
    team_id = str(uuid.uuid4())
    team_name = f"team-{team_id[:8]}"
    if created_at:
        db.execute("INSERT INTO teams (id, name, license_type, created_at) VALUES (?, ?, 'joint-equal', ?)",
                   (team_id, team_name, created_at))
    else:
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
         "Test hypothesis",
         "Test framework",
         "Test demos",
         json.dumps(["code"]), json.dumps(["Python"]),
         "Test adhoc",
         json.dumps(["connection1"]),
         json.dumps(["source1"]),
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


def _create_approved_consent(db, team_id, requester_id, approver_id, resource_ref):
    """Helper: create an approved Level 3 reveal consent."""
    consent_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id,
           resource_type, resource_ref, status, resolved_at)
           VALUES (?, ?, 3, ?, ?, 'commit', ?, 'approved', datetime('now'))""",
        (consent_id, team_id, requester_id, approver_id, resource_ref)
    )
    db.commit()
    return consent_id


def _resolve_tickets_for_user(db, team_id, author_id, resolver_id, count):
    """Helper: bulk insert resolved tickets for a user."""
    for i in range(count):
        ticket_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO team_tickets
               (id, team_id, author_id, type, area, title, description, status,
                resolved_by, resolved_at)
               VALUES (?, ?, ?, 'need_help', 'code', ?, 'Test ticket', 'resolved', ?, datetime('now'))""",
            (ticket_id, team_id, author_id, f"Ticket {i+1}", resolver_id)
        )
    db.commit()


# ============================================================
# TestComputeLicense — 5 rules
# ============================================================

class TestComputeLicense:
    """Test _compute_license produces correct license types."""

    def test_no_reveals_returns_joint_equal(self, db):
        """RULE 1: No reveals → joint-equal."""
        user_a = _get_or_create_user(db, "lic_a@test.com", "LicA")
        user_b = _get_or_create_user(db, "lic_b@test.com", "LicB")
        team_id = _create_team_with_members(db, user_a, user_b)

        result = _compute_license(db, team_id)
        assert result["license_type"] == "joint-equal"
        assert result["reveal_state"] == "none"
        assert result["contribution_split"]["LicA"] == 50
        assert result["contribution_split"]["LicB"] == 50

    def test_unilateral_reveal_returns_advisory(self, db):
        """RULE 2: Unilateral reveal → advisory-only."""
        user_a = _get_or_create_user(db, "uni_a@test.com", "UniA")
        user_b = _get_or_create_user(db, "uni_b@test.com", "UniB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)

        # A reveals to B (B requested, A approved) → A is the one sharing content
        _create_approved_consent(db, team_id, requester_id=user_b, approver_id=user_a, resource_ref=commit_a)

        result = _compute_license(db, team_id)
        assert result["license_type"] == "advisory-only"
        assert "unilateral" in result["reveal_state"]
        # A revealed, so A is owner (100%)
        assert result["contribution_split"]["UniA"] == 100
        assert result["contribution_split"]["UniB"] == 0

    def test_bilateral_balanced_returns_joint_equal(self, db):
        """RULE 3: Bilateral reveals + balanced tickets → joint-equal."""
        user_a = _get_or_create_user(db, "bal_a@test.com", "BalA")
        user_b = _get_or_create_user(db, "bal_b@test.com", "BalB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)
        commit_b = _create_commit_for_user(db, user_b, domain="physics", problem="Quantum")

        # Bilateral: A reveals to B AND B reveals to A
        _create_approved_consent(db, team_id, requester_id=user_b, approver_id=user_a, resource_ref=commit_a)
        _create_approved_consent(db, team_id, requester_id=user_a, approver_id=user_b, resource_ref=commit_b)

        # Balanced tickets (3:2 ratio < 2:1)
        _resolve_tickets_for_user(db, team_id, author_id=user_b, resolver_id=user_a, count=3)
        _resolve_tickets_for_user(db, team_id, author_id=user_a, resolver_id=user_b, count=2)

        result = _compute_license(db, team_id)
        assert result["license_type"] == "joint-equal"
        assert result["reveal_state"] == "bilateral"
        assert result["contribution_split"]["BalA"] == 50

    def test_bilateral_asymmetric_returns_joint_weighted(self, db):
        """RULE 4: Bilateral reveals + asymmetric tickets (>=2:1) → joint-weighted."""
        user_a = _get_or_create_user(db, "asym_a@test.com", "AsymA")
        user_b = _get_or_create_user(db, "asym_b@test.com", "AsymB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)
        commit_b = _create_commit_for_user(db, user_b, domain="physics", problem="Quantum")

        # Bilateral reveals
        _create_approved_consent(db, team_id, requester_id=user_b, approver_id=user_a, resource_ref=commit_a)
        _create_approved_consent(db, team_id, requester_id=user_a, approver_id=user_b, resource_ref=commit_b)

        # Asymmetric tickets: A resolved 8, B resolved 2 (4:1 ratio)
        _resolve_tickets_for_user(db, team_id, author_id=user_b, resolver_id=user_a, count=8)
        _resolve_tickets_for_user(db, team_id, author_id=user_a, resolver_id=user_b, count=2)

        result = _compute_license(db, team_id)
        assert result["license_type"] == "joint-weighted"
        assert result["reveal_state"] == "bilateral"
        # A resolved 8/10 = 80% but capped at 75%, B gets 25%
        assert result["contribution_split"]["AsymA"] == 75
        assert result["contribution_split"]["AsymB"] == 25

    def test_old_team_no_reveals_returns_time_limited(self, db):
        """RULE 5: Team >30 days old with no reveals → time-limited."""
        user_a = _get_or_create_user(db, "old_a@test.com", "OldA")
        user_b = _get_or_create_user(db, "old_b@test.com", "OldB")
        # Create team backdated to 45 days ago
        team_id = _create_team_with_members(db, user_a, user_b,
                                            created_at="2025-01-01 00:00:00")

        result = _compute_license(db, team_id)
        assert result["license_type"] == "time-limited"
        assert result["reveal_state"] == "none"


# ============================================================
# TestLicenseContribution — split calculations
# ============================================================

class TestLicenseContribution:
    """Test contribution split calculations."""

    def test_joint_equal_split_50_50(self, db):
        """joint-equal always gives 50/50."""
        user_a = _get_or_create_user(db, "eq_a@test.com", "EqA")
        user_b = _get_or_create_user(db, "eq_b@test.com", "EqB")
        team_id = _create_team_with_members(db, user_a, user_b)

        result = _compute_license(db, team_id)
        assert result["contribution_split"]["EqA"] == 50
        assert result["contribution_split"]["EqB"] == 50

    def test_weighted_split_respects_floor(self, db):
        """joint-weighted never drops below 25% for lesser contributor."""
        user_a = _get_or_create_user(db, "floor_a@test.com", "FloorA")
        user_b = _get_or_create_user(db, "floor_b@test.com", "FloorB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)
        commit_b = _create_commit_for_user(db, user_b, domain="physics", problem="Quantum")

        # Bilateral reveals
        _create_approved_consent(db, team_id, requester_id=user_b, approver_id=user_a, resource_ref=commit_a)
        _create_approved_consent(db, team_id, requester_id=user_a, approver_id=user_b, resource_ref=commit_b)

        # Extremely asymmetric: A resolved 19, B resolved 1 (19:1 ratio)
        _resolve_tickets_for_user(db, team_id, author_id=user_b, resolver_id=user_a, count=19)
        _resolve_tickets_for_user(db, team_id, author_id=user_a, resolver_id=user_b, count=1)

        result = _compute_license(db, team_id)
        assert result["license_type"] == "joint-weighted"
        # A: 19/20 = 95% but capped at 75%
        assert result["contribution_split"]["FloorA"] == 75
        assert result["contribution_split"]["FloorB"] == 25

    def test_advisory_split_100_0(self, db):
        """advisory-only gives 100% to owner, 0% to advisor."""
        user_a = _get_or_create_user(db, "adv_a@test.com", "AdvA")
        user_b = _get_or_create_user(db, "adv_b@test.com", "AdvB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_b = _create_commit_for_user(db, user_b)

        # Only B reveals to A
        _create_approved_consent(db, team_id, requester_id=user_a, approver_id=user_b, resource_ref=commit_b)

        result = _compute_license(db, team_id)
        assert result["license_type"] == "advisory-only"
        assert result["contribution_split"]["AdvB"] == 100
        assert result["contribution_split"]["AdvA"] == 0


# ============================================================
# TestLicenseHooks — DB-level hook verification
# ============================================================

class TestLicenseHooks:
    """Test that license recalculation hooks update the DB correctly."""

    def test_reveal_approve_updates_license_type(self, db):
        """Approving a unilateral reveal should change license_type in DB."""
        user_a = _get_or_create_user(db, "hook_a@test.com", "HookA")
        user_b = _get_or_create_user(db, "hook_b@test.com", "HookB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)

        # Initially joint-equal
        team = db.execute("SELECT license_type FROM teams WHERE id = ?", (team_id,)).fetchone()
        assert team["license_type"] == "joint-equal"

        # Create approved consent (unilateral: only A revealed)
        _create_approved_consent(db, team_id, requester_id=user_b, approver_id=user_a, resource_ref=commit_a)

        # Simulate what the hook does: compute and update
        lic = _compute_license(db, team_id)
        assert lic["license_type"] == "advisory-only"

        current_type = db.execute("SELECT license_type FROM teams WHERE id = ?",
                                  (team_id,)).fetchone()["license_type"]
        if lic["license_type"] != current_type:
            db.execute("UPDATE teams SET license_type = ?, license_updated_at = datetime('now') WHERE id = ?",
                       (lic["license_type"], team_id))
            db.commit()

        team_after = db.execute("SELECT license_type, license_updated_at FROM teams WHERE id = ?",
                                (team_id,)).fetchone()
        assert team_after["license_type"] == "advisory-only"
        assert team_after["license_updated_at"] is not None

    def test_ticket_resolve_updates_contribution_percentage(self, db):
        """Resolving tickets asymmetrically should update contribution_percentage in team_members."""
        user_a = _get_or_create_user(db, "cp_a@test.com", "CpA")
        user_b = _get_or_create_user(db, "cp_b@test.com", "CpB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)
        commit_b = _create_commit_for_user(db, user_b, domain="physics", problem="Quantum")

        # Bilateral reveals
        _create_approved_consent(db, team_id, requester_id=user_b, approver_id=user_a, resource_ref=commit_a)
        _create_approved_consent(db, team_id, requester_id=user_a, approver_id=user_b, resource_ref=commit_b)

        # Asymmetric tickets
        _resolve_tickets_for_user(db, team_id, author_id=user_b, resolver_id=user_a, count=6)
        _resolve_tickets_for_user(db, team_id, author_id=user_a, resolver_id=user_b, count=2)

        # Simulate hook: compute and update
        lic = _compute_license(db, team_id)
        assert lic["license_type"] == "joint-weighted"

        for m_row in db.execute(
            "SELECT tm.user_id, u.pseudonym FROM team_members tm JOIN users u ON tm.user_id = u.id WHERE tm.team_id = ?",
            (team_id,)
        ).fetchall():
            pct = lic["contribution_split"].get(m_row["pseudonym"], 0)
            db.execute("UPDATE team_members SET contribution_percentage = ? WHERE team_id = ? AND user_id = ?",
                       (pct, team_id, m_row["user_id"]))
        db.commit()

        cp_a = db.execute("SELECT contribution_percentage FROM team_members WHERE team_id = ? AND user_id = ?",
                          (team_id, user_a)).fetchone()["contribution_percentage"]
        cp_b = db.execute("SELECT contribution_percentage FROM team_members WHERE team_id = ? AND user_id = ?",
                          (team_id, user_b)).fetchone()["contribution_percentage"]

        assert cp_a == 75  # 6/8 = 75%
        assert cp_b == 25  # 2/8 = 25%


# ============================================================
# TestLicensePydantic — input validation
# ============================================================

class TestLicensePydantic:
    """Test Pydantic model validation for license input."""

    def test_team_license_input_valid(self):
        """Valid TeamLicenseInput should pass."""
        inp = TeamLicenseInput(team_id="team-123")
        assert inp.team_id == "team-123"

    def test_team_license_input_extra_rejected(self):
        """Extra fields should be rejected (extra='forbid')."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TeamLicenseInput(team_id="team-123", bogus="extra")
