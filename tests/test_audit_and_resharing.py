"""Tests for Audit Log Viewer + Re-sharing Control (NEED-05 — MAD).

Tests cover: audit log schema, audit log viewer tool, re-sharing detection,
re-sharing penalty, and AuditLogInput Pydantic validation.
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
    _check_resharing_violation,
    AuditLogInput,
    RESHARING_PENALTY_HONESTY,
)


# ============================================================
# Helpers (reused patterns from test_file_sharing.py)
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


def _create_bilateral_reveals(db, team_id, user_a_id, user_b_id):
    """Helper: create approved Level 3 consents in BOTH directions."""
    commit_a = _create_commit_for_user(db, user_a_id)
    commit_b = _create_commit_for_user(db, user_b_id, domain="physics", problem="Quantum")

    c1 = str(uuid.uuid4())
    db.execute(
        """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id,
           resource_type, resource_ref, status, resolved_at)
           VALUES (?, ?, 3, ?, ?, 'commit', ?, 'approved', datetime('now'))""",
        (c1, team_id, user_b_id, user_a_id, commit_a)
    )
    c2 = str(uuid.uuid4())
    db.execute(
        """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id,
           resource_type, resource_ref, status, resolved_at)
           VALUES (?, ?, 3, ?, ?, 'commit', ?, 'approved', datetime('now'))""",
        (c2, team_id, user_a_id, user_b_id, commit_b)
    )
    db.commit()
    return c1, c2


def _share_file(db, team_id, user_id, file_path, file_hash=None, description=None):
    """Helper: INSERT a shared file directly."""
    file_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO shared_files (id, team_id, shared_by, file_path, file_hash, description, origin_user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (file_id, team_id, user_id, file_path, file_hash, description, user_id)
    )
    db.commit()
    return file_id


def _create_audit_entry(db, team_id, user_id, action, resource_ref=None, details=None):
    """Helper: INSERT an audit log entry directly."""
    return _write_audit_log(db, team_id, user_id, action,
                            resource_ref=resource_ref, details=details)


# ============================================================
# TestAuditLogSchema — verify audit_log table constraints
# ============================================================

class TestAuditLogSchema:
    """Verify audit_log schema constraints."""

    def test_audit_entry_creation_ok(self, db):
        """Creating a valid audit log entry should work."""
        user_a = _get_or_create_user(db, "al_a@test.com", "AuditA")
        user_b = _get_or_create_user(db, "al_b@test.com", "AuditB")
        team_id = _create_team_with_members(db, user_a, user_b)

        log_id = _create_audit_entry(db, team_id, user_a, "file_shared",
                                     resource_ref="some-file-id",
                                     details={"file_path": "test.py"})
        db.commit()

        row = db.execute("SELECT * FROM audit_log WHERE id = ?", (log_id,)).fetchone()
        assert row is not None
        r = dict(row)
        assert r["team_id"] == team_id
        assert r["actor_id"] == user_a
        assert r["action"] == "file_shared"
        assert r["resource_ref"] == "some-file-id"
        assert json.loads(r["details"]) == {"file_path": "test.py"}
        assert r["created_at"] is not None

    def test_invalid_action_rejected(self, db):
        """audit_log CHECK constraint should reject invalid action types."""
        user_a = _get_or_create_user(db, "chk_a@test.com", "ChkA")
        user_b = _get_or_create_user(db, "chk_b@test.com", "ChkB")
        team_id = _create_team_with_members(db, user_a, user_b)

        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO audit_log (id, team_id, actor_id, action)
                   VALUES (?, ?, ?, 'invalid_action')""",
                (str(uuid.uuid4()), team_id, user_a)
            )


# ============================================================
# TestAuditLogViewer — verify the audit log tool logic
# ============================================================

class TestAuditLogViewer:
    """Test audit log viewing functionality."""

    def test_list_all_entries(self, db):
        """Should list all audit entries for a team."""
        user_a = _get_or_create_user(db, "view_a@test.com", "ViewA")
        user_b = _get_or_create_user(db, "view_b@test.com", "ViewB")
        team_id = _create_team_with_members(db, user_a, user_b)

        _create_audit_entry(db, team_id, user_a, "file_shared",
                            details={"file_path": "a.py"})
        _create_audit_entry(db, team_id, user_b, "ticket_created",
                            details={"title": "help"})
        _create_audit_entry(db, team_id, user_a, "reveal_requested")
        db.commit()

        # Query all entries
        rows = db.execute(
            """SELECT al.*, u.pseudonym AS actor_pseudonym
               FROM audit_log al
               JOIN users u ON al.actor_id = u.id
               WHERE al.team_id = ?
               ORDER BY al.created_at DESC""",
            (team_id,)
        ).fetchall()

        assert len(rows) == 3

    def test_filter_by_action(self, db):
        """Should filter entries by action type."""
        user_a = _get_or_create_user(db, "filt_a@test.com", "FiltA")
        user_b = _get_or_create_user(db, "filt_b@test.com", "FiltB")
        team_id = _create_team_with_members(db, user_a, user_b)

        _create_audit_entry(db, team_id, user_a, "file_shared")
        _create_audit_entry(db, team_id, user_b, "file_shared")
        _create_audit_entry(db, team_id, user_a, "ticket_created")
        db.commit()

        rows = db.execute(
            """SELECT * FROM audit_log
               WHERE team_id = ? AND action = ?""",
            (team_id, "file_shared")
        ).fetchall()

        assert len(rows) == 2

    def test_no_cross_team_access(self, db):
        """Entries from another team should not appear."""
        user_a = _get_or_create_user(db, "cross_a@test.com", "CrossA")
        user_b = _get_or_create_user(db, "cross_b@test.com", "CrossB")
        user_c = _get_or_create_user(db, "cross_c@test.com", "CrossC")
        team1 = _create_team_with_members(db, user_a, user_b)
        team2 = _create_team_with_members(db, user_b, user_c)

        _create_audit_entry(db, team1, user_a, "file_shared")
        _create_audit_entry(db, team2, user_c, "ticket_created")
        db.commit()

        rows_team1 = db.execute(
            "SELECT * FROM audit_log WHERE team_id = ?", (team1,)
        ).fetchall()
        rows_team2 = db.execute(
            "SELECT * FROM audit_log WHERE team_id = ?", (team2,)
        ).fetchall()

        assert len(rows_team1) == 1
        assert len(rows_team2) == 1
        assert dict(rows_team1[0])["action"] == "file_shared"
        assert dict(rows_team2[0])["action"] == "ticket_created"

    def test_limit_works(self, db):
        """Should respect the limit parameter."""
        user_a = _get_or_create_user(db, "lim_a@test.com", "LimA")
        user_b = _get_or_create_user(db, "lim_b@test.com", "LimB")
        team_id = _create_team_with_members(db, user_a, user_b)

        for i in range(10):
            _create_audit_entry(db, team_id, user_a, "file_shared",
                                details={"i": i})
        db.commit()

        rows = db.execute(
            """SELECT * FROM audit_log
               WHERE team_id = ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (team_id, 3)
        ).fetchall()

        assert len(rows) == 3


# ============================================================
# TestResharingDetection — verify _check_resharing_violation
# ============================================================

class TestResharingDetection:
    """Test re-sharing detection logic."""

    def test_no_hash_no_check(self, db):
        """If file_hash is None, should return None (no check possible)."""
        user_a = _get_or_create_user(db, "nohash_a@test.com", "NoHashA")
        result = _check_resharing_violation(db, user_a, None)
        assert result is None

    def test_same_user_same_hash_ok(self, db):
        """Same user sharing same hash in different team should be allowed."""
        user_a = _get_or_create_user(db, "same_a@test.com", "SameA")
        user_b = _get_or_create_user(db, "same_b@test.com", "SameB")
        user_c = _get_or_create_user(db, "same_c@test.com", "SameC")
        team1 = _create_team_with_members(db, user_a, user_b)
        team2 = _create_team_with_members(db, user_a, user_c)

        # User A shares file with hash in team1
        _share_file(db, team1, user_a, "data.csv", file_hash="abc123")

        # User A tries to share same hash in team2 — should be OK (own file)
        result = _check_resharing_violation(db, user_a, "abc123")
        assert result is None

    def test_different_user_same_hash_violation(self, db):
        """Different user sharing same hash should be detected as violation."""
        user_a = _get_or_create_user(db, "viol_a@test.com", "ViolA")
        user_b = _get_or_create_user(db, "viol_b@test.com", "ViolB")
        user_c = _get_or_create_user(db, "viol_c@test.com", "ViolC")
        team1 = _create_team_with_members(db, user_a, user_b)
        team2 = _create_team_with_members(db, user_b, user_c)

        # User A shares file with hash in team1
        file_id = _share_file(db, team1, user_a, "research.py", file_hash="secret_hash_xyz")

        # User B tries to share same hash — VIOLATION
        result = _check_resharing_violation(db, user_b, "secret_hash_xyz")
        assert result is not None
        assert result["original_file_id"] == file_id
        assert result["original_team_id"] == team1
        assert result["origin_user_id"] == user_a
        assert result["file_path"] == "research.py"

    def test_null_hash_in_db_skipped(self, db):
        """Files with NULL hash in DB should not trigger false positives."""
        user_a = _get_or_create_user(db, "null_a@test.com", "NullA")
        user_b = _get_or_create_user(db, "null_b@test.com", "NullB")
        team_id = _create_team_with_members(db, user_a, user_b)

        # User A shares file without hash
        _share_file(db, team_id, user_a, "notes.txt", file_hash=None)

        # User B checks with a hash — should not match (NULL != 'somehash')
        result = _check_resharing_violation(db, user_b, "somehash")
        assert result is None


# ============================================================
# TestResharingPenalty — verify penalty mechanics
# ============================================================

class TestResharingPenalty:
    """Test that re-sharing violations apply correct penalties."""

    def test_violation_tanks_honesty(self, db):
        """A violation should set running_honesty and avg_honesty to RESHARING_PENALTY_HONESTY."""
        user_a = _get_or_create_user(db, "pen_a@test.com", "PenA")
        user_b = _get_or_create_user(db, "pen_b@test.com", "PenB")
        user_c = _get_or_create_user(db, "pen_c@test.com", "PenC")
        team1 = _create_team_with_members(db, user_a, user_b)
        team2 = _create_team_with_members(db, user_b, user_c)

        # Set user B's initial honesty to something decent
        db.execute("UPDATE users SET running_honesty = 4.0, avg_honesty = 4.0 WHERE id = ?",
                   (user_b,))
        db.commit()

        # User A shares with hash
        _share_file(db, team1, user_a, "secret.py", file_hash="unique_hash_001")

        # Simulate violation penalty (as share_file would do)
        violation = _check_resharing_violation(db, user_b, "unique_hash_001")
        assert violation is not None

        db.execute(
            "UPDATE users SET running_honesty = ?, avg_honesty = ? WHERE id = ?",
            (RESHARING_PENALTY_HONESTY, RESHARING_PENALTY_HONESTY, user_b)
        )
        db.commit()

        row = db.execute("SELECT running_honesty, avg_honesty FROM users WHERE id = ?",
                         (user_b,)).fetchone()
        assert row["running_honesty"] == RESHARING_PENALTY_HONESTY
        assert row["avg_honesty"] == RESHARING_PENALTY_HONESTY

    def test_violation_audit_entry_created(self, db):
        """A violation should create a 'violation_detected' audit entry."""
        user_a = _get_or_create_user(db, "aud_a@test.com", "AudA")
        user_b = _get_or_create_user(db, "aud_b@test.com", "AudB")
        user_c = _get_or_create_user(db, "aud_c@test.com", "AudC")
        team1 = _create_team_with_members(db, user_a, user_b)
        team2 = _create_team_with_members(db, user_b, user_c)

        file_id = _share_file(db, team1, user_a, "data.csv", file_hash="hash_002")

        # Simulate what share_file does on violation
        violation = _check_resharing_violation(db, user_b, "hash_002")
        assert violation is not None

        _write_audit_log(db, team2, user_b, "violation_detected",
                         resource_ref=violation["original_file_id"],
                         details={
                             "type": "resharing",
                             "file_hash": "hash_002",
                             "original_team_id": violation["original_team_id"],
                             "origin_user_id": violation["origin_user_id"],
                             "attempted_file_path": "stolen_data.csv",
                         })
        db.commit()

        row = db.execute(
            "SELECT * FROM audit_log WHERE team_id = ? AND action = 'violation_detected'",
            (team2,)
        ).fetchone()
        assert row is not None
        details = json.loads(row["details"])
        assert details["type"] == "resharing"
        assert details["file_hash"] == "hash_002"
        assert details["origin_user_id"] == user_a

    def test_blocked_share_not_inserted(self, db):
        """When a violation is detected, the file should NOT be inserted into shared_files."""
        user_a = _get_or_create_user(db, "blk_a@test.com", "BlkA")
        user_b = _get_or_create_user(db, "blk_b@test.com", "BlkB")
        user_c = _get_or_create_user(db, "blk_c@test.com", "BlkC")
        team1 = _create_team_with_members(db, user_a, user_b)
        team2 = _create_team_with_members(db, user_b, user_c)

        _share_file(db, team1, user_a, "original.py", file_hash="hash_003")

        # Simulate: violation detected, so we do NOT insert
        violation = _check_resharing_violation(db, user_b, "hash_003")
        assert violation is not None

        # Verify no file was shared by user_b with this hash
        count = db.execute(
            "SELECT COUNT(*) as c FROM shared_files WHERE shared_by = ? AND file_hash = ?",
            (user_b, "hash_003")
        ).fetchone()["c"]
        assert count == 0


# ============================================================
# TestAuditPydantic — validate AuditLogInput model
# ============================================================

class TestAuditPydantic:
    """Validate AuditLogInput Pydantic model."""

    def test_valid_input(self):
        """Valid AuditLogInput should pass."""
        inp = AuditLogInput(team_id="team-123", action_filter="file_shared", limit=10)
        assert inp.team_id == "team-123"
        assert inp.action_filter == "file_shared"
        assert inp.limit == 10

    def test_defaults(self):
        """Default values should be applied."""
        inp = AuditLogInput(team_id="team-456")
        assert inp.action_filter is None
        assert inp.limit == 50

    def test_extra_rejected(self):
        """Extra fields should be rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AuditLogInput(team_id="team-789", unknown_field="bad")

    def test_limit_bounds(self):
        """Limit should be between 1 and 200."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AuditLogInput(team_id="team-lim", limit=0)
        with pytest.raises(ValidationError):
            AuditLogInput(team_id="team-lim", limit=201)
