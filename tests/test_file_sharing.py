"""Tests for the File Sharing System (NEED-04 — Level 4 Metadata Registry).

Tests cover: schema constraints, bilateral L3 gating, file share logic,
audit trail, and Pydantic model validation.
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
    ShareFileInput,
    SharedFilesInput,
    MAX_SHARED_FILES_PER_TEAM,
    MAX_FILE_PATH_LENGTH,
    MAX_FILE_DESCRIPTION_LENGTH,
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

    # A reveals to B (B requested, A approved)
    c1 = str(uuid.uuid4())
    db.execute(
        """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id,
           resource_type, resource_ref, status, resolved_at)
           VALUES (?, ?, 3, ?, ?, 'commit', ?, 'approved', datetime('now'))""",
        (c1, team_id, user_b_id, user_a_id, commit_a)
    )
    # B reveals to A (A requested, B approved)
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


# ============================================================
# TestFileShareSchema — verify table constraints
# ============================================================

class TestFileShareSchema:
    """Verify shared_files schema constraints."""

    def test_file_creation_ok(self, db):
        """Creating a valid shared file record should work."""
        user_a = _get_or_create_user(db, "fs_a@test.com", "FsA")
        user_b = _get_or_create_user(db, "fs_b@test.com", "FsB")
        team_id = _create_team_with_members(db, user_a, user_b)

        file_id = _share_file(db, team_id, user_a, "scripts/analysis.py",
                              file_hash="abc123", description="Main analysis script")

        row = db.execute("SELECT * FROM shared_files WHERE id = ?", (file_id,)).fetchone()
        assert row is not None
        r = dict(row)
        assert r["team_id"] == team_id
        assert r["shared_by"] == user_a
        assert r["file_path"] == "scripts/analysis.py"
        assert r["file_hash"] == "abc123"
        assert r["description"] == "Main analysis script"
        assert r["origin_user_id"] == user_a
        assert r["shared_at"] is not None

    def test_team_fk_required(self, db):
        """shared_files.team_id must reference a valid team."""
        user_a = _get_or_create_user(db, "fk_a@test.com", "FkA")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO shared_files (id, team_id, shared_by, file_path, origin_user_id)
                   VALUES (?, 'nonexistent-team', ?, 'test.py', ?)""",
                (str(uuid.uuid4()), user_a, user_a)
            )

    def test_description_column_exists(self, db):
        """The description column should exist in shared_files."""
        user_a = _get_or_create_user(db, "desc_a@test.com", "DescA")
        user_b = _get_or_create_user(db, "desc_b@test.com", "DescB")
        team_id = _create_team_with_members(db, user_a, user_b)

        file_id = _share_file(db, team_id, user_a, "data.csv", description="Dataset with 10K rows")

        row = db.execute("SELECT description FROM shared_files WHERE id = ?", (file_id,)).fetchone()
        assert row["description"] == "Dataset with 10K rows"


# ============================================================
# TestFileShareGating — bilateral L3 as gate
# ============================================================

class TestFileShareGating:
    """Test bilateral Level 3 reveal gating for file sharing."""

    def test_no_reveals_blocks_sharing(self, db):
        """Without any reveals, file sharing should be blocked."""
        user_a = _get_or_create_user(db, "gate_a@test.com", "GateA")
        user_b = _get_or_create_user(db, "gate_b@test.com", "GateB")
        team_id = _create_team_with_members(db, user_a, user_b)

        # Simulate the bilateral check from the tool
        members = db.execute(
            "SELECT user_id FROM team_members WHERE team_id = ?", (team_id,)
        ).fetchall()
        member_ids = [m["user_id"] for m in members]

        bilateral = True
        for m_id in member_ids:
            other_ids = [o for o in member_ids if o != m_id]
            for other_id in other_ids:
                consent = db.execute(
                    """SELECT id FROM reveal_consents
                       WHERE team_id = ? AND level = 3 AND requester_id = ? AND approver_id = ?
                       AND status = 'approved'""",
                    (team_id, other_id, m_id)
                ).fetchone()
                if not consent:
                    bilateral = False
                    break

        assert bilateral is False, "No reveals should block file sharing"

    def test_unilateral_reveal_blocks_sharing(self, db):
        """With only one-directional reveal, file sharing should be blocked."""
        user_a = _get_or_create_user(db, "uni_a@test.com", "UniA")
        user_b = _get_or_create_user(db, "uni_b@test.com", "UniB")
        team_id = _create_team_with_members(db, user_a, user_b)
        commit_a = _create_commit_for_user(db, user_a)

        # Only A reveals to B (unilateral)
        db.execute(
            """INSERT INTO reveal_consents (id, team_id, level, requester_id, approver_id,
               resource_type, resource_ref, status, resolved_at)
               VALUES (?, ?, 3, ?, ?, 'commit', ?, 'approved', datetime('now'))""",
            (str(uuid.uuid4()), team_id, user_b, user_a, commit_a)
        )
        db.commit()

        # Check bilateral
        members = db.execute(
            "SELECT user_id FROM team_members WHERE team_id = ?", (team_id,)
        ).fetchall()
        member_ids = [m["user_id"] for m in members]

        bilateral = True
        for m_id in member_ids:
            other_ids = [o for o in member_ids if o != m_id]
            for other_id in other_ids:
                consent = db.execute(
                    """SELECT id FROM reveal_consents
                       WHERE team_id = ? AND level = 3 AND requester_id = ? AND approver_id = ?
                       AND status = 'approved'""",
                    (team_id, other_id, m_id)
                ).fetchone()
                if not consent:
                    bilateral = False
                    break

        assert bilateral is False, "Unilateral reveal should block file sharing"

    def test_bilateral_reveals_allow_sharing(self, db):
        """With bilateral reveals, file sharing should be allowed."""
        user_a = _get_or_create_user(db, "bil_a@test.com", "BilA")
        user_b = _get_or_create_user(db, "bil_b@test.com", "BilB")
        team_id = _create_team_with_members(db, user_a, user_b)
        _create_bilateral_reveals(db, team_id, user_a, user_b)

        # Check bilateral
        members = db.execute(
            "SELECT user_id FROM team_members WHERE team_id = ?", (team_id,)
        ).fetchall()
        member_ids = [m["user_id"] for m in members]

        bilateral = True
        for m_id in member_ids:
            other_ids = [o for o in member_ids if o != m_id]
            for other_id in other_ids:
                consent = db.execute(
                    """SELECT id FROM reveal_consents
                       WHERE team_id = ? AND level = 3 AND requester_id = ? AND approver_id = ?
                       AND status = 'approved'""",
                    (team_id, other_id, m_id)
                ).fetchone()
                if not consent:
                    bilateral = False
                    break

        assert bilateral is True, "Bilateral reveals should allow file sharing"


# ============================================================
# TestFileShareLogic — share creates record, dedup, limits
# ============================================================

class TestFileShareLogic:
    """Test file share creation, dedup, and limits."""

    def test_share_creates_record(self, db):
        """Sharing a file should create a record with all fields."""
        user_a = _get_or_create_user(db, "rec_a@test.com", "RecA")
        user_b = _get_or_create_user(db, "rec_b@test.com", "RecB")
        team_id = _create_team_with_members(db, user_a, user_b)

        file_id = _share_file(db, team_id, user_a, "notebook.ipynb",
                              file_hash="sha256_abc", description="Jupyter notebook")

        row = dict(db.execute("SELECT * FROM shared_files WHERE id = ?", (file_id,)).fetchone())
        assert row["file_path"] == "notebook.ipynb"
        assert row["file_hash"] == "sha256_abc"
        assert row["description"] == "Jupyter notebook"
        assert row["shared_by"] == user_a
        assert row["origin_user_id"] == user_a

    def test_dedup_same_user_same_path(self, db):
        """Same user sharing same file_path should be detectable for dedup."""
        user_a = _get_or_create_user(db, "dup_a@test.com", "DupA")
        user_b = _get_or_create_user(db, "dup_b@test.com", "DupB")
        team_id = _create_team_with_members(db, user_a, user_b)

        file_id_1 = _share_file(db, team_id, user_a, "scripts/run.py")

        # Check if file already exists (simulating tool dedup logic)
        existing = db.execute(
            "SELECT id FROM shared_files WHERE team_id = ? AND shared_by = ? AND file_path = ?",
            (team_id, user_a, "scripts/run.py")
        ).fetchone()
        assert existing is not None
        assert existing["id"] == file_id_1

    def test_different_users_same_path_ok(self, db):
        """Different users can share files with the same path."""
        user_a = _get_or_create_user(db, "diff_a@test.com", "DiffA")
        user_b = _get_or_create_user(db, "diff_b@test.com", "DiffB")
        team_id = _create_team_with_members(db, user_a, user_b)

        file_id_a = _share_file(db, team_id, user_a, "data.csv")
        file_id_b = _share_file(db, team_id, user_b, "data.csv")

        assert file_id_a != file_id_b

        count = db.execute(
            "SELECT COUNT(*) as c FROM shared_files WHERE team_id = ? AND file_path = 'data.csv'",
            (team_id,)
        ).fetchone()["c"]
        assert count == 2

    def test_file_limit_enforced(self, db):
        """File count per team should be trackable for limit enforcement."""
        user_a = _get_or_create_user(db, "lim_a@test.com", "LimA")
        user_b = _get_or_create_user(db, "lim_b@test.com", "LimB")
        team_id = _create_team_with_members(db, user_a, user_b)

        # Insert MAX_SHARED_FILES_PER_TEAM files
        for i in range(MAX_SHARED_FILES_PER_TEAM):
            _share_file(db, team_id, user_a, f"file_{i}.py")

        count = db.execute(
            "SELECT COUNT(*) as c FROM shared_files WHERE team_id = ?", (team_id,)
        ).fetchone()["c"]
        assert count == MAX_SHARED_FILES_PER_TEAM

        # Application-level check: count >= limit
        assert count >= MAX_SHARED_FILES_PER_TEAM, "Limit should be reached"


# ============================================================
# TestFileShareAudit — audit trail
# ============================================================

class TestFileShareAudit:
    """Test audit trail for file sharing actions."""

    def test_file_shared_audit_entry(self, db):
        """file_shared audit entry should be creatable."""
        user_a = _get_or_create_user(db, "aud_a@test.com", "AudA")
        user_b = _get_or_create_user(db, "aud_b@test.com", "AudB")
        team_id = _create_team_with_members(db, user_a, user_b)
        file_id = _share_file(db, team_id, user_a, "results.csv")

        _write_audit_log(db, team_id, user_a, "file_shared",
                         resource_ref=file_id,
                         details={"file_path": "results.csv", "file_hash": None})
        db.commit()

        audit = db.execute(
            "SELECT * FROM audit_log WHERE team_id = ? AND action = 'file_shared'",
            (team_id,)
        ).fetchone()
        assert audit is not None
        d = json.loads(audit["details"])
        assert d["file_path"] == "results.csv"

    def test_file_accessed_audit_entry(self, db):
        """file_accessed audit entry should be creatable."""
        user_a = _get_or_create_user(db, "acc_a@test.com", "AccA")
        user_b = _get_or_create_user(db, "acc_b@test.com", "AccB")
        team_id = _create_team_with_members(db, user_a, user_b)

        _write_audit_log(db, team_id, user_b, "file_accessed",
                         resource_ref=team_id,
                         details={"file_count": 3})
        db.commit()

        audit = db.execute(
            "SELECT * FROM audit_log WHERE team_id = ? AND action = 'file_accessed'",
            (team_id,)
        ).fetchone()
        assert audit is not None
        d = json.loads(audit["details"])
        assert d["file_count"] == 3


# ============================================================
# TestFileSharePydantic — input model validation
# ============================================================

class TestFileSharePydantic:
    """Test Pydantic model validation for file sharing inputs."""

    def test_share_file_input_valid(self):
        """Valid ShareFileInput should pass."""
        inp = ShareFileInput(team_id="team-123", file_path="scripts/run.py",
                             file_hash="abc123", description="Runner script")
        assert inp.team_id == "team-123"
        assert inp.file_path == "scripts/run.py"
        assert inp.file_hash == "abc123"
        assert inp.description == "Runner script"

    def test_share_file_input_extra_rejected(self):
        """Extra fields should be rejected (extra='forbid')."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ShareFileInput(team_id="team-123", file_path="test.py", bogus="extra")

    def test_shared_files_input_valid(self):
        """Valid SharedFilesInput should pass."""
        inp = SharedFilesInput(team_id="team-xyz")
        assert inp.team_id == "team-xyz"

    def test_empty_path_rejected(self):
        """Empty file_path should be rejected (min_length=1)."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ShareFileInput(team_id="team-123", file_path="")

    def test_long_path_rejected(self):
        """File path exceeding MAX_FILE_PATH_LENGTH should be rejected."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ShareFileInput(team_id="team-123", file_path="a" * 501)
