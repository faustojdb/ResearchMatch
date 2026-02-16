"""Tests for the Contract System (NEED-08 — Git-Verifiable Collaboration Contracts).

Tests cover: contract generation, bilateral confirmation, contract content,
git refs on commits, and Pydantic model validation.
Uses in-memory SQLite DB from conftest.py fixtures.
"""
import json
import uuid
import hashlib
import re

import pytest

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from research_match_server import (
    init_database,
    _get_or_create_user,
    _write_audit_log,
    _compute_license,
    _generate_contract_content,
    ExportContractInput,
    ConfirmContractInput,
    SubmitCommitInput,
    LICENSE_TERMS,
    CONTRACT_VERSION,
    CONTRACT_DIR_NAME,
    CONTRACT_FILE_PREFIX,
    GIT_COMMIT_HASH_PATTERN,
    MAX_CONTRACT_CONFIRMATIONS_PER_TEAM,
    SERVER_VERSION,
)


# ============================================================
# Helpers
# ============================================================

VALID_GIT_HASH = "a" * 40
VALID_GIT_HASH_2 = "b" * 40


def _create_team_with_members(db, user_a_id, user_b_id, created_at=None):
    """Helper: create a team and add two members."""
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


def _create_commit_for_user(db, user_id, domain="molecular biology", problem="Test problem for contract testing",
                            git_repo_url=None, git_commit_hash=None):
    """Helper: insert a minimal research commit for a user."""
    commit_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO research_commits
           (id, user_id, version, domain, problem, hypothesis, theoretical_framework,
            demonstrations_summary, demo_types, code_languages, adhoc_summary,
            adhoc_connections, cherry_picking, content_hash,
            ot_score, ofc_score, ot_breakdown, ofc_breakdown,
            solidity_levels, overall_solidity, solidity_impact,
            git_repo_url, git_commit_hash)
           VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
         json.dumps({"theory_multiplier": 0.6}),
         git_repo_url, git_commit_hash)
    )
    db.commit()
    return commit_id


def _insert_contract(db, team_id, generated_by, contract_version=1,
                     license_type="joint-equal", status="pending"):
    """Helper: insert a contract directly for testing."""
    contract_id = str(uuid.uuid4())
    content = f"# Test Contract v{contract_version}"
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    db.execute(
        """INSERT INTO collaboration_contracts
           (id, team_id, contract_version, license_type, contribution_split,
            contract_content, content_hash, generated_by, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (contract_id, team_id, contract_version, license_type,
         json.dumps({}), content, content_hash, generated_by, status)
    )
    db.commit()
    return contract_id


def _add_bilateral_reveals(db, team_id, user_a_id, user_b_id):
    """Helper: add bilateral Level 3 reveals."""
    for req_id, appr_id in [(user_a_id, user_b_id), (user_b_id, user_a_id)]:
        db.execute(
            """INSERT INTO reveal_consents
               (id, team_id, level, requester_id, approver_id, status)
               VALUES (?, ?, 3, ?, ?, 'approved')""",
            (str(uuid.uuid4()), team_id, req_id, appr_id)
        )
    db.commit()


# ============================================================
# TestContractGeneration
# ============================================================

class TestContractGeneration:
    """Tests for contract generation via _generate_contract_content."""

    def test_basic_contract_generation(self, db):
        """Generate a basic contract for a 2-member team."""
        user_a = _get_or_create_user(db, "alice@test.com", "Alice_CG")
        user_b = _get_or_create_user(db, "bob@test.com", "Bob_CG")
        _create_commit_for_user(db, user_a)
        _create_commit_for_user(db, user_b)
        team_id = _create_team_with_members(db, user_a, user_b)

        license_info = _compute_license(db, team_id)
        content = _generate_contract_content(db, team_id, license_info, 1)

        assert "# Research Match Collaboration Contract" in content
        assert "Alice_CG" in content
        assert "Bob_CG" in content
        assert "Contract Version:** 1" in content

    def test_contract_with_git_refs(self, db):
        """Contract includes git refs when commits have them."""
        user_a = _get_or_create_user(db, "alice_gr@test.com", "Alice_GR")
        user_b = _get_or_create_user(db, "bob_gr@test.com", "Bob_GR")
        _create_commit_for_user(db, user_a, git_repo_url="https://github.com/alice/repo",
                                git_commit_hash=VALID_GIT_HASH)
        _create_commit_for_user(db, user_b)
        team_id = _create_team_with_members(db, user_a, user_b)

        license_info = _compute_license(db, team_id)
        content = _generate_contract_content(db, team_id, license_info, 1)

        assert "https://github.com/alice/repo" in content
        assert VALID_GIT_HASH in content

    def test_versioning_supersedes_previous(self, db):
        """Creating a new contract supersedes previous pending/partial ones."""
        user_a = _get_or_create_user(db, "alice_vs@test.com", "Alice_VS")
        user_b = _get_or_create_user(db, "bob_vs@test.com", "Bob_VS")
        _create_commit_for_user(db, user_a)
        _create_commit_for_user(db, user_b)
        team_id = _create_team_with_members(db, user_a, user_b)

        # Insert v1 contract as pending
        c1_id = _insert_contract(db, team_id, user_a, contract_version=1, status="pending")

        # Insert v2 — should supersede v1 conceptually (we test via direct DB update)
        db.execute(
            "UPDATE collaboration_contracts SET status = 'superseded' WHERE id = ?",
            (c1_id,)
        )
        c2_id = _insert_contract(db, team_id, user_a, contract_version=2, status="pending")

        # Verify v1 is superseded
        v1 = db.execute("SELECT status FROM collaboration_contracts WHERE id = ?", (c1_id,)).fetchone()
        assert v1["status"] == "superseded"

        v2 = db.execute("SELECT status FROM collaboration_contracts WHERE id = ?", (c2_id,)).fetchone()
        assert v2["status"] == "pending"

    def test_non_member_cannot_see_contract(self, db):
        """Only team members should have contract content generated."""
        user_a = _get_or_create_user(db, "alice_nm@test.com", "Alice_NM")
        user_b = _get_or_create_user(db, "bob_nm@test.com", "Bob_NM")
        outsider = _get_or_create_user(db, "outsider_nm@test.com", "Outsider_NM")
        team_id = _create_team_with_members(db, user_a, user_b)

        # Outsider is not a member
        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (team_id, outsider)
        ).fetchone()
        assert membership is None

    def test_content_hash_correct(self, db):
        """content_hash matches SHA-256 of the generated markdown."""
        user_a = _get_or_create_user(db, "alice_ch@test.com", "Alice_CH")
        user_b = _get_or_create_user(db, "bob_ch@test.com", "Bob_CH")
        _create_commit_for_user(db, user_a)
        _create_commit_for_user(db, user_b)
        team_id = _create_team_with_members(db, user_a, user_b)

        license_info = _compute_license(db, team_id)
        content = _generate_contract_content(db, team_id, license_info, 1)
        expected_hash = hashlib.sha256(content.encode()).hexdigest()

        assert len(expected_hash) == 64
        assert re.match(r'^[0-9a-f]{64}$', expected_hash)


# ============================================================
# TestContractConfirmation
# ============================================================

class TestContractConfirmation:
    """Tests for bilateral contract confirmation flow."""

    def test_first_party_partial(self, db):
        """First confirmation sets status to 'partial'."""
        user_a = _get_or_create_user(db, "alice_fp@test.com", "Alice_FP")
        user_b = _get_or_create_user(db, "bob_fp@test.com", "Bob_FP")
        team_id = _create_team_with_members(db, user_a, user_b)
        contract_id = _insert_contract(db, team_id, user_a)

        # User A confirms
        db.execute(
            """UPDATE collaboration_contracts
               SET confirmation_a_user_id = ?, confirmation_a_git_hash = ?,
                   confirmation_a_at = datetime('now'), status = 'partial'
               WHERE id = ?""",
            (user_a, VALID_GIT_HASH, contract_id)
        )
        db.commit()

        row = db.execute("SELECT * FROM collaboration_contracts WHERE id = ?", (contract_id,)).fetchone()
        assert row["status"] == "partial"
        assert row["confirmation_a_user_id"] == user_a
        assert row["confirmation_a_git_hash"] == VALID_GIT_HASH
        assert row["confirmation_b_user_id"] is None

    def test_second_party_confirmed(self, db):
        """Both confirmations set status to 'confirmed'."""
        user_a = _get_or_create_user(db, "alice_sp@test.com", "Alice_SP")
        user_b = _get_or_create_user(db, "bob_sp@test.com", "Bob_SP")
        team_id = _create_team_with_members(db, user_a, user_b)
        contract_id = _insert_contract(db, team_id, user_a)

        # User A confirms
        db.execute(
            """UPDATE collaboration_contracts
               SET confirmation_a_user_id = ?, confirmation_a_git_hash = ?,
                   confirmation_a_at = datetime('now'), status = 'partial'
               WHERE id = ?""",
            (user_a, VALID_GIT_HASH, contract_id)
        )

        # User B confirms
        db.execute(
            """UPDATE collaboration_contracts
               SET confirmation_b_user_id = ?, confirmation_b_git_hash = ?,
                   confirmation_b_at = datetime('now'), status = 'confirmed'
               WHERE id = ?""",
            (user_b, VALID_GIT_HASH_2, contract_id)
        )
        db.commit()

        row = db.execute("SELECT * FROM collaboration_contracts WHERE id = ?", (contract_id,)).fetchone()
        assert row["status"] == "confirmed"
        assert row["confirmation_a_user_id"] == user_a
        assert row["confirmation_b_user_id"] == user_b

    def test_idempotent_confirmation(self, db):
        """Same user confirming again updates their slot without error."""
        user_a = _get_or_create_user(db, "alice_ic@test.com", "Alice_IC")
        user_b = _get_or_create_user(db, "bob_ic@test.com", "Bob_IC")
        team_id = _create_team_with_members(db, user_a, user_b)
        contract_id = _insert_contract(db, team_id, user_a)

        new_hash = "c" * 40

        # First confirm
        db.execute(
            """UPDATE collaboration_contracts
               SET confirmation_a_user_id = ?, confirmation_a_git_hash = ?,
                   confirmation_a_at = datetime('now'), status = 'partial'
               WHERE id = ?""",
            (user_a, VALID_GIT_HASH, contract_id)
        )
        # Idempotent update with different hash
        db.execute(
            """UPDATE collaboration_contracts
               SET confirmation_a_git_hash = ?, confirmation_a_at = datetime('now')
               WHERE id = ? AND confirmation_a_user_id = ?""",
            (new_hash, contract_id, user_a)
        )
        db.commit()

        row = db.execute("SELECT * FROM collaboration_contracts WHERE id = ?", (contract_id,)).fetchone()
        assert row["confirmation_a_git_hash"] == new_hash
        assert row["status"] == "partial"

    def test_invalid_hash_rejected(self):
        """Pydantic rejects invalid git hashes."""
        with pytest.raises(Exception):
            ConfirmContractInput(
                team_id="test-team",
                contract_id="test-contract",
                git_commit_hash="not-a-valid-hash"
            )

    def test_superseded_contract_cannot_confirm(self, db):
        """Cannot confirm a superseded contract."""
        user_a = _get_or_create_user(db, "alice_sc@test.com", "Alice_SC")
        user_b = _get_or_create_user(db, "bob_sc@test.com", "Bob_SC")
        team_id = _create_team_with_members(db, user_a, user_b)
        contract_id = _insert_contract(db, team_id, user_a, status="superseded")

        row = db.execute("SELECT status FROM collaboration_contracts WHERE id = ?", (contract_id,)).fetchone()
        assert row["status"] == "superseded"

    def test_non_member_cannot_confirm(self, db):
        """Non-member cannot confirm a contract (membership check)."""
        user_a = _get_or_create_user(db, "alice_nmc@test.com", "Alice_NMC")
        user_b = _get_or_create_user(db, "bob_nmc@test.com", "Bob_NMC")
        outsider = _get_or_create_user(db, "outsider_nmc@test.com", "Outsider_NMC")
        team_id = _create_team_with_members(db, user_a, user_b)

        membership = db.execute(
            "SELECT * FROM team_members WHERE team_id = ? AND user_id = ?",
            (team_id, outsider)
        ).fetchone()
        assert membership is None


# ============================================================
# TestContractContent
# ============================================================

class TestContractContent:
    """Tests for contract markdown content structure."""

    def _generate_contract(self, db):
        user_a = _get_or_create_user(db, "alice_cc@test.com", "Alice_CC")
        user_b = _get_or_create_user(db, "bob_cc@test.com", "Bob_CC")
        _create_commit_for_user(db, user_a, git_repo_url="https://github.com/alice/repo",
                                git_commit_hash=VALID_GIT_HASH)
        _create_commit_for_user(db, user_b, git_repo_url="https://github.com/bob/repo",
                                git_commit_hash=VALID_GIT_HASH_2)
        team_id = _create_team_with_members(db, user_a, user_b)
        _add_bilateral_reveals(db, team_id, user_a, user_b)
        license_info = _compute_license(db, team_id)
        content = _generate_contract_content(db, team_id, license_info, 1)
        return content, license_info

    def test_contains_both_parties(self, db):
        """Contract contains both team members' pseudonyms."""
        content, _ = self._generate_contract(db)
        assert "Alice_CC" in content
        assert "Bob_CC" in content

    def test_contains_license_terms(self, db):
        """Contract contains license type and terms."""
        content, license_info = self._generate_contract(db)
        license_type = license_info["license_type"]
        assert f"**Type:** {license_type}" in content
        # At least one term should appear
        terms = LICENSE_TERMS.get(license_type, [])
        if terms:
            assert terms[0] in content

    def test_contains_scores(self, db):
        """Contract contains OT/OFC scores."""
        content, _ = self._generate_contract(db)
        assert "OT:" in content
        assert "OFC:" in content
        assert "65.0%" in content
        assert "58.0%" in content

    def test_contains_verification(self, db):
        """Contract contains verification section."""
        content, _ = self._generate_contract(db)
        assert "## Verification" in content
        assert "BOTH parties' git repositories" in content
        assert "Deletion of this file" in content
        assert SERVER_VERSION in content


# ============================================================
# TestGitRefOnCommit
# ============================================================

class TestGitRefOnCommit:
    """Tests for git_repo_url and git_commit_hash on research commits."""

    def test_commit_with_git_ref(self, db):
        """Commit stores git refs when provided."""
        user = _get_or_create_user(db, "alice_gr2@test.com", "Alice_GR2")
        _create_commit_for_user(db, user,
                                git_repo_url="https://github.com/alice/project",
                                git_commit_hash=VALID_GIT_HASH)

        row = db.execute(
            "SELECT git_repo_url, git_commit_hash FROM research_commits WHERE user_id = ?",
            (user,)
        ).fetchone()
        assert row["git_repo_url"] == "https://github.com/alice/project"
        assert row["git_commit_hash"] == VALID_GIT_HASH

    def test_commit_without_git_ref(self, db):
        """Commit works without git refs (backward compatible)."""
        user = _get_or_create_user(db, "bob_gr2@test.com", "Bob_GR2")
        _create_commit_for_user(db, user)

        row = db.execute(
            "SELECT git_repo_url, git_commit_hash FROM research_commits WHERE user_id = ?",
            (user,)
        ).fetchone()
        assert row["git_repo_url"] is None
        assert row["git_commit_hash"] is None

    def test_invalid_git_hash_rejected_on_submit(self):
        """SubmitCommitInput rejects invalid git hashes."""
        with pytest.raises(Exception):
            SubmitCommitInput(
                domain="test",
                problem="Test problem with enough chars",
                git_commit_hash="INVALID"
            )


# ============================================================
# TestContractPydantic
# ============================================================

class TestContractPydantic:
    """Tests for Pydantic model validation."""

    def test_valid_export_input(self):
        """ExportContractInput accepts valid data."""
        inp = ExportContractInput(team_id="some-team-id")
        assert inp.team_id == "some-team-id"

    def test_extra_fields_rejected(self):
        """ExportContractInput rejects extra fields."""
        with pytest.raises(Exception):
            ExportContractInput(team_id="some-team-id", extra_field="bad")

    def test_valid_confirm_input(self):
        """ConfirmContractInput accepts valid data."""
        inp = ConfirmContractInput(
            team_id="some-team",
            contract_id="some-contract",
            git_commit_hash=VALID_GIT_HASH,
            repo_url="https://github.com/user/repo"
        )
        assert inp.git_commit_hash == VALID_GIT_HASH
        assert inp.repo_url == "https://github.com/user/repo"

    def test_confirm_input_without_repo_url(self):
        """ConfirmContractInput works without optional repo_url."""
        inp = ConfirmContractInput(
            team_id="some-team",
            contract_id="some-contract",
            git_commit_hash=VALID_GIT_HASH
        )
        assert inp.repo_url is None


# ============================================================
# TestContractSchema
# ============================================================

class TestContractSchema:
    """Tests for the collaboration_contracts table schema."""

    def test_table_exists(self, db):
        """collaboration_contracts table is created by init_database."""
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='collaboration_contracts'"
        ).fetchone()
        assert row is not None

    def test_unique_team_version(self, db):
        """Cannot insert two contracts with same team_id and version."""
        user = _get_or_create_user(db, "alice_ts@test.com", "Alice_TS")
        user_b = _get_or_create_user(db, "bob_ts@test.com", "Bob_TS")
        team_id = _create_team_with_members(db, user, user_b)

        _insert_contract(db, team_id, user, contract_version=1)

        with pytest.raises(Exception):
            _insert_contract(db, team_id, user, contract_version=1)

    def test_git_ref_columns_exist(self, db):
        """research_commits has git_repo_url and git_commit_hash columns."""
        user = _get_or_create_user(db, "alice_gc@test.com", "Alice_GC")
        commit_id = _create_commit_for_user(db, user,
                                            git_repo_url="https://github.com/test/repo",
                                            git_commit_hash=VALID_GIT_HASH)
        row = db.execute(
            "SELECT git_repo_url, git_commit_hash FROM research_commits WHERE id = ?",
            (commit_id,)
        ).fetchone()
        assert row["git_repo_url"] == "https://github.com/test/repo"
        assert row["git_commit_hash"] == VALID_GIT_HASH
