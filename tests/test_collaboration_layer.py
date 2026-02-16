"""Tests for the Collaboration Layer (v2.4) — schema, tickets, audit log, Pydantic models.

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
    NeedsCreateInput,
    NeedsListInput,
    NeedsResolveInput,
    MAX_OPEN_TICKETS_PER_USER_PER_TEAM,
    TICKET_EFFORT_BONUS,
    REPUTATION_ALPHA,
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


def _create_ticket(db, team_id, author_id, type_="need_help", area="code",
                   title="Test ticket", description="Test description for the ticket",
                   priority="important"):
    """Helper: insert a ticket directly into team_tickets."""
    ticket_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO team_tickets (id, team_id, author_id, type, area, title, description, priority)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ticket_id, team_id, author_id, type_, area, title, description, priority)
    )
    db.commit()
    return ticket_id


# ============================================================
# TestTeamTicketsSchema — verify tables and constraints
# ============================================================

class TestTeamTicketsSchema:
    """Verify the 4 new collaboration tables exist and constraints work."""

    def test_four_tables_exist(self, db):
        """All 4 collaboration tables should exist after init_database."""
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [r["name"] for r in tables]
        for expected in ("team_tickets", "reveal_consents", "shared_files", "audit_log"):
            assert expected in table_names, f"Table '{expected}' not found in schema"

    def test_ticket_type_check_constraint(self, db):
        """Invalid ticket type should be rejected by CHECK constraint."""
        user_id = _get_or_create_user(db, "check@test.com", "CheckUser")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "b@test.com", "B"))

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO team_tickets (id, team_id, author_id, type, area, title, description)
                   VALUES (?, ?, ?, 'invalid_type', 'code', 'title', 'desc')""",
                (str(uuid.uuid4()), team_id, user_id)
            )

    def test_ticket_area_check_constraint(self, db):
        """Invalid area should be rejected by CHECK constraint."""
        user_id = _get_or_create_user(db, "area@test.com", "AreaUser")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "b2@test.com", "B2"))

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO team_tickets (id, team_id, author_id, type, area, title, description)
                   VALUES (?, ?, ?, 'need_help', 'invalid_area', 'title', 'desc')""",
                (str(uuid.uuid4()), team_id, user_id)
            )

    def test_ticket_status_check_constraint(self, db):
        """Invalid status should be rejected by CHECK constraint."""
        user_id = _get_or_create_user(db, "stat@test.com", "StatUser")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "b3@test.com", "B3"))

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO team_tickets (id, team_id, author_id, type, area, title, description, status)
                   VALUES (?, ?, ?, 'need_help', 'code', 'title', 'desc', 'bogus')""",
                (str(uuid.uuid4()), team_id, user_id)
            )

    def test_audit_log_action_check_constraint(self, db):
        """Invalid audit action should be rejected by CHECK constraint."""
        user_id = _get_or_create_user(db, "audit@test.com", "AuditUser")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "b4@test.com", "B4"))

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO audit_log (id, team_id, actor_id, action)
                   VALUES (?, ?, ?, 'invalid_action')""",
                (str(uuid.uuid4()), team_id, user_id)
            )

    def test_reveal_consents_level_check(self, db):
        """Only levels 3 and 4 are valid for reveal_consents."""
        user_a = _get_or_create_user(db, "reva@test.com", "RevA")
        user_b = _get_or_create_user(db, "revb@test.com", "RevB")
        team_id = _create_team_with_members(db, user_a, user_b)

        # Level 3 should work
        db.execute(
            """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id, resource_ref)
               VALUES (?, ?, 3, ?, ?, 'ref1')""",
            (str(uuid.uuid4()), team_id, user_a, user_b)
        )
        db.commit()

        # Level 2 should fail
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id, resource_ref)
                   VALUES (?, ?, 2, ?, ?, 'ref2')""",
                (str(uuid.uuid4()), team_id, user_a, user_b)
            )


# ============================================================
# TestTicketCreation
# ============================================================

class TestTicketCreation:
    """Test ticket creation logic and limits."""

    def test_create_ticket_ok(self, db):
        """Creating a valid ticket should work."""
        user_id = _get_or_create_user(db, "creator@test.com", "Creator")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "peer@test.com", "Peer"))

        ticket_id = _create_ticket(db, team_id, user_id,
                                   type_="need_help", area="theory",
                                   title="Need help with proof",
                                   description="I need help formalizing the convergence proof")

        row = db.execute("SELECT * FROM team_tickets WHERE id = ?", (ticket_id,)).fetchone()
        assert row is not None
        assert dict(row)["type"] == "need_help"
        assert dict(row)["area"] == "theory"
        assert dict(row)["status"] == "open"
        assert dict(row)["priority"] == "important"

    def test_max_open_tickets_enforced(self, db):
        """User should not exceed MAX_OPEN_TICKETS_PER_USER_PER_TEAM open tickets."""
        user_id = _get_or_create_user(db, "maxtickets@test.com", "MaxT")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "peer2@test.com", "Peer2"))

        # Create MAX tickets
        for i in range(MAX_OPEN_TICKETS_PER_USER_PER_TEAM):
            _create_ticket(db, team_id, user_id, title=f"Ticket {i}",
                          description=f"Description for ticket {i}")

        # Count open tickets
        count = db.execute(
            "SELECT COUNT(*) as c FROM team_tickets WHERE team_id = ? AND author_id = ? AND status IN ('open', 'in_progress')",
            (team_id, user_id)
        ).fetchone()["c"]
        assert count == MAX_OPEN_TICKETS_PER_USER_PER_TEAM

    def test_all_ticket_types_valid(self, db):
        """All 4 ticket types should be insertable."""
        user_id = _get_or_create_user(db, "types@test.com", "TypesUser")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "peer3@test.com", "Peer3"))

        for t in ("need_help", "can_offer", "warning", "question"):
            tid = _create_ticket(db, team_id, user_id, type_=t, title=f"Test {t}",
                                description=f"Description for {t} ticket type")
            row = db.execute("SELECT type FROM team_tickets WHERE id = ?", (tid,)).fetchone()
            assert dict(row)["type"] == t


# ============================================================
# TestTicketResolution
# ============================================================

class TestTicketResolution:
    """Test ticket resolution logic."""

    def test_resolve_ticket_ok(self, db):
        """Resolving an open ticket should update status, resolved_by, resolved_at."""
        user_a = _get_or_create_user(db, "resolver_a@test.com", "ResolverA")
        user_b = _get_or_create_user(db, "resolver_b@test.com", "ResolverB")
        team_id = _create_team_with_members(db, user_a, user_b)

        ticket_id = _create_ticket(db, team_id, user_a)

        db.execute(
            """UPDATE team_tickets SET status = 'resolved', resolved_by = ?, resolved_at = datetime('now')
               WHERE id = ?""",
            (user_b, ticket_id)
        )
        db.commit()

        row = dict(db.execute("SELECT * FROM team_tickets WHERE id = ?", (ticket_id,)).fetchone())
        assert row["status"] == "resolved"
        assert row["resolved_by"] == user_b
        assert row["resolved_at"] is not None

    def test_wont_fix_resolution(self, db):
        """Closing as wont_fix should be valid."""
        user_a = _get_or_create_user(db, "wf_a@test.com", "WfA")
        user_b = _get_or_create_user(db, "wf_b@test.com", "WfB")
        team_id = _create_team_with_members(db, user_a, user_b)

        ticket_id = _create_ticket(db, team_id, user_a)

        db.execute(
            "UPDATE team_tickets SET status = 'wont_fix', resolved_by = ? WHERE id = ?",
            (user_b, ticket_id)
        )
        db.commit()

        row = dict(db.execute("SELECT * FROM team_tickets WHERE id = ?", (ticket_id,)).fetchone())
        assert row["status"] == "wont_fix"

    def test_effort_boost_on_resolve(self, db):
        """Resolving someone else's need_help ticket should boost running_effort."""
        user_a = _get_or_create_user(db, "eboost_a@test.com", "EBoostA")
        user_b = _get_or_create_user(db, "eboost_b@test.com", "EBoostB")
        team_id = _create_team_with_members(db, user_a, user_b)

        # Initialize running_effort for user_b
        db.execute("UPDATE users SET running_effort = 3.0 WHERE id = ?", (user_b,))
        db.commit()

        ticket_id = _create_ticket(db, team_id, user_a, type_="need_help")

        # Simulate the effort boost logic from needs_resolve
        current = db.execute("SELECT running_effort FROM users WHERE id = ?", (user_b,)).fetchone()
        new_effort = min(5.0, current["running_effort"] + TICKET_EFFORT_BONUS * REPUTATION_ALPHA)
        db.execute("UPDATE users SET running_effort = ? WHERE id = ?", (new_effort, user_b))
        db.commit()

        updated = db.execute("SELECT running_effort FROM users WHERE id = ?", (user_b,)).fetchone()
        assert updated["running_effort"] > 3.0
        assert updated["running_effort"] == pytest.approx(3.0 + TICKET_EFFORT_BONUS * REPUTATION_ALPHA)


# ============================================================
# TestAuditLog
# ============================================================

class TestAuditLog:
    """Test audit_log immutable insert and constraints."""

    def test_insert_audit_entry(self, db):
        """_write_audit_log should insert a valid entry and return its ID."""
        user_id = _get_or_create_user(db, "auditw@test.com", "AuditW")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "peer4@test.com", "Peer4"))

        log_id = _write_audit_log(db, team_id, user_id, "ticket_created",
                                  resource_ref="ticket-123",
                                  details={"type": "need_help", "area": "code"})
        db.commit()

        row = db.execute("SELECT * FROM audit_log WHERE id = ?", (log_id,)).fetchone()
        assert row is not None
        rd = dict(row)
        assert rd["action"] == "ticket_created"
        assert rd["team_id"] == team_id
        assert rd["actor_id"] == user_id
        assert json.loads(rd["details"])["type"] == "need_help"

    def test_invalid_action_rejected(self, db):
        """An invalid action should be rejected by the CHECK constraint."""
        user_id = _get_or_create_user(db, "badact@test.com", "BadAct")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "peer5@test.com", "Peer5"))

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO audit_log (id, team_id, actor_id, action) VALUES (?, ?, ?, 'not_real')",
                (str(uuid.uuid4()), team_id, user_id)
            )

    def test_audit_chronological_order(self, db):
        """Multiple audit entries should be ordered chronologically."""
        user_id = _get_or_create_user(db, "chrono@test.com", "Chrono")
        team_id = _create_team_with_members(db, user_id, _get_or_create_user(db, "peer6@test.com", "Peer6"))

        ids = []
        for action in ("ticket_created", "ticket_updated", "ticket_resolved"):
            log_id = _write_audit_log(db, team_id, user_id, action, resource_ref="t1")
            ids.append(log_id)
        db.commit()

        rows = db.execute(
            "SELECT id FROM audit_log WHERE team_id = ? ORDER BY created_at ASC",
            (team_id,)
        ).fetchall()
        assert [r["id"] for r in rows] == ids


# ============================================================
# TestPydanticValidation
# ============================================================

class TestPydanticValidation:
    """Test Pydantic model validation for ticket inputs."""

    def test_needs_create_valid(self):
        """Valid NeedsCreateInput should pass validation."""
        inp = NeedsCreateInput(
            team_id="team-123",
            type="need_help",
            area="code",
            title="Need GPU optimization help",
            description="Looking for help optimizing CUDA kernels for MD simulation",
            priority="critical",
        )
        assert inp.type == "need_help"
        assert inp.priority == "critical"

    def test_needs_create_invalid_type(self):
        """Invalid type should raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            NeedsCreateInput(
                team_id="team-123",
                type="chat",  # invalid
                area="code",
                title="Some title here",
                description="Some description that is long enough",
            )

    def test_needs_create_invalid_area(self):
        """Invalid area should raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            NeedsCreateInput(
                team_id="team-123",
                type="need_help",
                area="marketing",  # invalid
                title="Some title here",
                description="Some description that is long enough",
            )

    def test_needs_create_title_too_short(self):
        """Title shorter than 5 chars should fail."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            NeedsCreateInput(
                team_id="team-123",
                type="need_help",
                area="code",
                title="Hi",  # too short (< 5)
                description="A description that passes minimum length",
            )

    def test_needs_resolve_valid(self):
        """Valid NeedsResolveInput should pass."""
        inp = NeedsResolveInput(
            ticket_id="ticket-abc",
            resolution="resolved",
            resolution_note="Fixed the convergence issue",
        )
        assert inp.resolution == "resolved"

    def test_needs_resolve_invalid_resolution(self):
        """Invalid resolution should raise ValidationError."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            NeedsResolveInput(
                ticket_id="ticket-abc",
                resolution="cancelled",  # invalid
            )

    def test_needs_list_optional_filters(self):
        """NeedsListInput with only team_id should be valid (all filters optional)."""
        inp = NeedsListInput(team_id="team-xyz")
        assert inp.status is None
        assert inp.area is None
        assert inp.type is None

    def test_needs_list_with_filters(self):
        """NeedsListInput with all filters should be valid."""
        inp = NeedsListInput(
            team_id="team-xyz",
            status="open",
            area="theory",
            type="question",
        )
        assert inp.status == "open"
        assert inp.area == "theory"
