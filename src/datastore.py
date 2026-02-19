"""
DataStore Protocol — Abstract interface for Research Match persistence.

Defines ~65 semantic methods that replace all 146 raw db.execute() calls.
Implementations: FirestoreDataStore (production), SQLiteDataStore (legacy/test).

All methods use plain dicts for data transfer (matching sqlite3.Row behavior).
Timestamps are ISO-8601 strings. IDs are UUID4 strings.
"""

from __future__ import annotations

import abc
from typing import Any, Optional


# Type alias: all records are returned as plain dicts
Record = dict[str, Any]


class DataStore(abc.ABC):
    """Abstract persistence layer for Research Match.

    Every public method corresponds to one or more db.execute() calls
    in the original SQLite implementation. Grouped by domain entity.
    """

    # =================================================================
    # SCHEMA / LIFECYCLE
    # =================================================================

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Create schema, run migrations, configure backend."""
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Release connections / cleanup."""
        ...

    # =================================================================
    # USERS (13 methods)
    # =================================================================

    @abc.abstractmethod
    async def find_user_by_email_hash(self, email_hash: str) -> Optional[Record]:
        """SELECT id FROM users WHERE email_hash = ?"""
        ...

    @abc.abstractmethod
    async def insert_user(self, user_id: str, pseudonym: str, email_hash: str) -> None:
        """INSERT INTO users (id, pseudonym, email_hash) VALUES (?,?,?)"""
        ...

    @abc.abstractmethod
    async def get_most_recent_user(self) -> Optional[Record]:
        """SELECT * FROM users ORDER BY created_at DESC LIMIT 1
        Used in single-user mode. Will be replaced by email-hash lookup in multi-user.
        """
        ...

    @abc.abstractmethod
    async def get_user_by_id(self, user_id: str) -> Optional[Record]:
        """SELECT * FROM users WHERE id = ?"""
        ...

    @abc.abstractmethod
    async def get_user_pseudonym(self, user_id: str) -> Optional[str]:
        """SELECT pseudonym FROM users WHERE id = ?"""
        ...

    @abc.abstractmethod
    async def get_user_running_averages(self, user_id: str) -> Optional[Record]:
        """SELECT running_honesty, running_quality, running_effort,
                  total_ratings_received FROM users WHERE id = ?"""
        ...

    @abc.abstractmethod
    async def get_user_running_effort(self, user_id: str) -> Optional[float]:
        """SELECT running_effort FROM users WHERE id = ?"""
        ...

    @abc.abstractmethod
    async def update_user_running_averages(
        self, user_id: str, running_honesty: float,
        running_quality: float, running_effort: float
    ) -> None:
        """UPDATE users SET running_honesty=?, running_quality=?, running_effort=? WHERE id=?"""
        ...

    @abc.abstractmethod
    async def update_user_running_effort(self, user_id: str, running_effort: float) -> None:
        """UPDATE users SET running_effort=? WHERE id=?"""
        ...

    @abc.abstractmethod
    async def update_user_reputation_stats(
        self, user_id: str, reputation_score: float,
        total_ratings_received: int, avg_honesty: float,
        avg_quality: float, avg_effort: float
    ) -> None:
        """UPDATE users SET reputation_score=?, total_ratings_received=?,
                  avg_honesty=?, avg_quality=?, avg_effort=? WHERE id=?"""
        ...

    @abc.abstractmethod
    async def penalize_user_honesty(
        self, user_id: str, running_honesty: float, avg_honesty: float
    ) -> None:
        """UPDATE users SET running_honesty=?, avg_honesty=? WHERE id=?"""
        ...

    @abc.abstractmethod
    async def count_users(self) -> int:
        """SELECT COUNT(*) FROM users"""
        ...

    # =================================================================
    # RESEARCH COMMITS (11 methods)
    # =================================================================

    @abc.abstractmethod
    async def get_corpus_commits(
        self, domain: str, exclude_user_id: str, subdomain: Optional[str] = None
    ) -> list[Record]:
        """SELECT * FROM research_commits WHERE domain=? AND user_id!=?
           [AND subdomain=?]"""
        ...

    @abc.abstractmethod
    async def get_latest_commit_by_user(self, user_id: str) -> Optional[Record]:
        """SELECT * FROM research_commits WHERE user_id=?
           ORDER BY version DESC LIMIT 1"""
        ...

    @abc.abstractmethod
    async def get_latest_commit_id_by_user(self, user_id: str) -> Optional[str]:
        """SELECT id FROM research_commits WHERE user_id=?
           ORDER BY version DESC LIMIT 1"""
        ...

    @abc.abstractmethod
    async def get_latest_scores_by_user(self, user_id: str) -> Optional[Record]:
        """SELECT ot_score, ofc_score FROM research_commits WHERE user_id=?
           ORDER BY version DESC LIMIT 1"""
        ...

    @abc.abstractmethod
    async def get_all_commits_by_user(self, user_id: str) -> list[Record]:
        """SELECT * FROM research_commits WHERE user_id=?
           ORDER BY version DESC"""
        ...

    @abc.abstractmethod
    async def get_commit_by_id(self, commit_id: str) -> Optional[Record]:
        """SELECT * FROM research_commits WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_max_commit_version(self, user_id: str) -> int:
        """SELECT MAX(version) FROM research_commits WHERE user_id=?
        Returns 0 if no commits exist."""
        ...

    @abc.abstractmethod
    async def insert_commit(self, commit: Record) -> None:
        """INSERT INTO research_commits (id, user_id, version, domain, ...) VALUES (...)
        The commit dict must contain all required fields."""
        ...

    @abc.abstractmethod
    async def find_candidate_commits_in_domain(
        self, exclude_user_id: str, domain: str
    ) -> list[Record]:
        """SELECT rc.*, u.pseudonym, u.reputation_score, ...
           FROM research_commits rc JOIN users u ...
           WHERE rc.user_id != ? AND rc.domain = ?
           GROUP BY rc.user_id HAVING rc.version = MAX(rc.version)

        Returns latest commit per user in the same domain, with user profile data.
        """
        ...

    @abc.abstractmethod
    async def search_commits_by_keywords(
        self, keywords: list[str], limit: int = 10
    ) -> list[Record]:
        """Full-text search across domain, subdomain, problem, hypothesis.
        In SQLite: LIKE queries. In Firestore: Algolia search.
        Returns commits with pseudonym joined from users."""
        ...

    @abc.abstractmethod
    async def count_commits(self) -> int:
        """SELECT COUNT(*) FROM research_commits"""
        ...

    # =================================================================
    # MATCHES (3 methods)
    # =================================================================

    @abc.abstractmethod
    async def upsert_match(self, match: Record) -> None:
        """INSERT OR REPLACE INTO matches (id, user_a_id, ...) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def find_match_between_users(self, user_a_id: str, user_b_id: str) -> Optional[Record]:
        """SELECT * FROM matches WHERE (user_a_id=? AND user_b_id=?)
           OR (user_a_id=? AND user_b_id=?) ORDER BY created_at DESC LIMIT 1"""
        ...

    @abc.abstractmethod
    async def count_matches(self) -> int:
        """SELECT COUNT(*) FROM matches"""
        ...

    # =================================================================
    # COLLABORATION REQUESTS (7 methods)
    # =================================================================

    @abc.abstractmethod
    async def find_pending_request(
        self, requester_id: str, recipient_id: str
    ) -> Optional[Record]:
        """SELECT * FROM collaboration_requests
           WHERE requester_id=? AND recipient_id=? AND status='pending'"""
        ...

    @abc.abstractmethod
    async def insert_collaboration_request(
        self, request_id: str, match_id: str,
        requester_id: str, recipient_id: str, message: str
    ) -> None:
        """INSERT INTO collaboration_requests (...) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def get_incoming_requests(self, recipient_id: str) -> list[Record]:
        """SELECT cr.*, m.semaphore, ..., u.pseudonym AS requester_pseudonym
           FROM collaboration_requests cr JOIN matches m ... JOIN users u ...
           WHERE cr.recipient_id=? ORDER BY cr.created_at DESC"""
        ...

    @abc.abstractmethod
    async def get_outgoing_requests(self, requester_id: str) -> list[Record]:
        """SELECT cr.*, m.semaphore, ..., u.pseudonym AS recipient_pseudonym
           FROM collaboration_requests cr JOIN matches m ... JOIN users u ...
           WHERE cr.requester_id=? ORDER BY cr.created_at DESC"""
        ...

    @abc.abstractmethod
    async def get_request_for_recipient(
        self, request_id: str, recipient_id: str
    ) -> Optional[Record]:
        """SELECT * FROM collaboration_requests WHERE id=? AND recipient_id=?"""
        ...

    @abc.abstractmethod
    async def update_request_status(
        self, request_id: str, status: str, responded_at: Optional[str] = None
    ) -> None:
        """UPDATE collaboration_requests SET status=?, responded_at=now() WHERE id=?
        If responded_at is provided, use it instead of now()."""
        ...

    @abc.abstractmethod
    async def count_pending_requests(self) -> int:
        """SELECT COUNT(*) FROM collaboration_requests WHERE status='pending'"""
        ...

    # =================================================================
    # TEAMS (9 methods)
    # =================================================================

    @abc.abstractmethod
    async def get_team_by_id(self, team_id: str) -> Optional[Record]:
        """SELECT * FROM teams WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_team_name(self, team_id: str) -> Optional[str]:
        """SELECT name FROM teams WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_team_created_at(self, team_id: str) -> Optional[str]:
        """SELECT created_at FROM teams WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_team_license_type(self, team_id: str) -> Optional[str]:
        """SELECT license_type FROM teams WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_team_license_info(self, team_id: str) -> Optional[Record]:
        """SELECT license_type, license_updated_at FROM teams WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_teams_by_user(self, user_id: str) -> list[Record]:
        """SELECT t.* FROM teams t JOIN team_members tm ...
           WHERE tm.user_id=?"""
        ...

    @abc.abstractmethod
    async def insert_team(self, team_id: str, name: str, license_type: str = "joint-equal") -> None:
        """INSERT INTO teams (id, name, license_type) VALUES (?,?,?)"""
        ...

    @abc.abstractmethod
    async def update_team_license(
        self, team_id: str, license_type: str, updated_at: Optional[str] = None
    ) -> None:
        """UPDATE teams SET license_type=?, license_updated_at=now() WHERE id=?
        If updated_at is provided, use it instead of now()."""
        ...

    @abc.abstractmethod
    async def count_teams(self) -> int:
        """SELECT COUNT(*) FROM teams"""
        ...

    # =================================================================
    # TEAM MEMBERS (7 methods)
    # =================================================================

    @abc.abstractmethod
    async def get_team_membership(self, team_id: str, user_id: str) -> Optional[Record]:
        """SELECT * FROM team_members WHERE team_id=? AND user_id=?"""
        ...

    @abc.abstractmethod
    async def get_team_member_ids(self, team_id: str) -> list[str]:
        """SELECT user_id FROM team_members WHERE team_id=?"""
        ...

    @abc.abstractmethod
    async def get_team_member_pseudonyms(self, team_id: str) -> list[Record]:
        """SELECT tm.user_id, u.pseudonym FROM team_members tm
           JOIN users u ... WHERE tm.team_id=?"""
        ...

    @abc.abstractmethod
    async def get_team_members_with_profiles(self, team_id: str) -> list[Record]:
        """SELECT tm.user_id, tm.role, tm.contribution_percentage, tm.joined_at,
                  u.pseudonym, u.reputation_score
           FROM team_members tm JOIN users u ... WHERE tm.team_id=?"""
        ...

    @abc.abstractmethod
    async def insert_team_member(
        self, team_id: str, user_id: str, role: str = "co-lead"
    ) -> None:
        """INSERT INTO team_members (team_id, user_id, role) VALUES (?,?,?)"""
        ...

    @abc.abstractmethod
    async def update_member_contribution(
        self, team_id: str, user_id: str, contribution_percentage: float
    ) -> None:
        """UPDATE team_members SET contribution_percentage=?
           WHERE team_id=? AND user_id=?"""
        ...

    @abc.abstractmethod
    async def count_team_members(self, team_id: str) -> int:
        """SELECT COUNT(*) FROM team_members WHERE team_id=?"""
        ...

    # =================================================================
    # RATINGS (8 methods)
    # =================================================================

    @abc.abstractmethod
    async def find_rating(
        self, team_id: str, rater_id: str, rated_id: str
    ) -> Optional[Record]:
        """SELECT id FROM ratings WHERE team_id=? AND rater_id=? AND rated_id=?"""
        ...

    @abc.abstractmethod
    async def get_rating(
        self, team_id: str, rater_id: str, rated_id: str
    ) -> Optional[Record]:
        """SELECT * FROM ratings WHERE team_id=? AND rater_id=? AND rated_id=?"""
        ...

    @abc.abstractmethod
    async def get_ratings_received_desc(self, rated_id: str) -> list[Record]:
        """SELECT * FROM ratings WHERE rated_id=? ORDER BY created_at DESC"""
        ...

    @abc.abstractmethod
    async def get_ratings_given_desc(self, rater_id: str) -> list[Record]:
        """SELECT * FROM ratings WHERE rater_id=? ORDER BY created_at DESC"""
        ...

    @abc.abstractmethod
    async def count_ratings_received(self, rated_id: str) -> int:
        """SELECT COUNT(*) FROM ratings WHERE rated_id=?"""
        ...

    @abc.abstractmethod
    async def insert_rating(self, rating: Record) -> None:
        """INSERT INTO ratings (id, team_id, rater_id, rated_id,
                  honesty, quality, effort, comment) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def reveal_team_ratings(self, team_id: str) -> None:
        """UPDATE ratings SET is_revealed=1 WHERE team_id=?"""
        ...

    @abc.abstractmethod
    async def count_ratings(self) -> int:
        """SELECT COUNT(*) FROM ratings"""
        ...

    # =================================================================
    # TEAM TICKETS (7 methods)
    # =================================================================

    @abc.abstractmethod
    async def get_ticket_by_id(self, ticket_id: str) -> Optional[Record]:
        """SELECT * FROM team_tickets WHERE id=?"""
        ...

    @abc.abstractmethod
    async def count_open_tickets_by_author(self, team_id: str, author_id: str) -> int:
        """SELECT COUNT(*) FROM team_tickets
           WHERE team_id=? AND author_id=? AND status IN ('open','in_progress')"""
        ...

    @abc.abstractmethod
    async def count_resolved_tickets_by_member(self, team_id: str, resolved_by: str) -> int:
        """SELECT COUNT(*) FROM team_tickets
           WHERE team_id=? AND resolved_by=? AND status='resolved'"""
        ...

    @abc.abstractmethod
    async def get_ticket_status_summary(self, team_id: str) -> list[Record]:
        """SELECT status, COUNT(*) AS c FROM team_tickets
           WHERE team_id=? GROUP BY status"""
        ...

    @abc.abstractmethod
    async def list_tickets_with_filters(
        self, team_id: str,
        status: Optional[str] = None,
        area: Optional[str] = None,
        ticket_type: Optional[str] = None
    ) -> list[Record]:
        """SELECT t.*, u.pseudonym AS author_pseudonym
           FROM team_tickets t JOIN users u ...
           WHERE t.team_id=? [AND filters] ORDER BY priority, created_at DESC"""
        ...

    @abc.abstractmethod
    async def insert_ticket(self, ticket: Record) -> None:
        """INSERT INTO team_tickets (id, team_id, author_id, type, area,
                  title, description, priority) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def resolve_ticket(
        self, ticket_id: str, resolved_by: str, status: str = "resolved"
    ) -> None:
        """UPDATE team_tickets SET status=?, resolved_by=?,
                  resolved_at=now(), updated_at=now() WHERE id=?"""
        ...

    @abc.abstractmethod
    async def count_tickets(self) -> int:
        """SELECT COUNT(*) FROM team_tickets"""
        ...

    # =================================================================
    # REVEAL CONSENTS (11 methods)
    # =================================================================

    @abc.abstractmethod
    async def find_pending_reveal(
        self, team_id: str, requester_id: str, resource_ref: str
    ) -> Optional[Record]:
        """SELECT id FROM reveal_consents
           WHERE team_id=? AND level=3 AND requester_id=?
           AND resource_ref=? AND status='pending'"""
        ...

    @abc.abstractmethod
    async def find_approved_reveal(
        self, team_id: str, requester_id: str, resource_ref: str
    ) -> Optional[Record]:
        """SELECT id FROM reveal_consents
           WHERE team_id=? AND level=3 AND requester_id=?
           AND resource_ref=? AND status='approved'"""
        ...

    @abc.abstractmethod
    async def find_approved_reveal_for_pair(
        self, team_id: str, requester_id: str, approver_id: str
    ) -> Optional[Record]:
        """SELECT id FROM reveal_consents
           WHERE team_id=? AND level=3 AND requester_id=?
           AND approver_id=? AND status='approved'"""
        ...

    @abc.abstractmethod
    async def count_pending_reveals(self, team_id: str) -> int:
        """SELECT COUNT(*) FROM reveal_consents
           WHERE team_id=? AND status='pending'"""
        ...

    @abc.abstractmethod
    async def count_approved_reveals_direction(
        self, team_id: str, approver_id: str, requester_id: str
    ) -> int:
        """SELECT COUNT(*) FROM reveal_consents
           WHERE team_id=? AND level=3 AND status='approved'
           AND approver_id=? AND requester_id=?"""
        ...

    @abc.abstractmethod
    async def get_reveal_consent_by_id(self, consent_id: str) -> Optional[Record]:
        """SELECT * FROM reveal_consents WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_team_consents_with_pseudonyms(self, team_id: str) -> list[Record]:
        """SELECT rc.*, u_req.pseudonym AS requester_pseudonym,
                  u_app.pseudonym AS approver_pseudonym
           FROM reveal_consents rc JOIN users u_req ... JOIN users u_app ...
           WHERE rc.team_id=? ORDER BY rc.created_at DESC"""
        ...

    @abc.abstractmethod
    async def get_reveal_visible_to(self, team_id: str, approver_id: str) -> list[str]:
        """Returns pseudonyms of users who can see approver_id's commits.
        SELECT u.pseudonym FROM reveal_consents rc JOIN users u ...
           WHERE rc.team_id=? AND rc.approver_id=?
           AND rc.status='approved' AND rc.level=3"""
        ...

    @abc.abstractmethod
    async def get_reveal_can_see(self, team_id: str, requester_id: str) -> list[str]:
        """Returns pseudonyms of users whose commits requester_id can see.
        SELECT u.pseudonym FROM reveal_consents rc JOIN users u ...
           WHERE rc.team_id=? AND rc.requester_id=?
           AND rc.status='approved' AND rc.level=3"""
        ...

    @abc.abstractmethod
    async def insert_reveal_consent(self, consent: Record) -> None:
        """INSERT INTO reveal_consents (id, team_id, level, requester_id,
                  approver_id, resource_type, resource_ref) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def update_reveal_consent_status(
        self, consent_id: str, status: str,
        team_id: Optional[str] = None, resolved_at: Optional[str] = None
    ) -> None:
        """UPDATE reveal_consents SET status=?, resolved_at=now() WHERE id=?
        team_id and resolved_at are optional hints (used by server for consistency)."""
        ...

    # =================================================================
    # SHARED FILES (6 methods)
    # =================================================================

    @abc.abstractmethod
    async def find_file_by_hash_other_user(
        self, file_hash: str, user_id: str
    ) -> Optional[Record]:
        """SELECT id, team_id, origin_user_id, file_path FROM shared_files
           WHERE file_hash=? AND origin_user_id!=? LIMIT 1"""
        ...

    @abc.abstractmethod
    async def find_shared_file_by_path(
        self, team_id: str, shared_by: str, file_path: str
    ) -> Optional[Record]:
        """SELECT id FROM shared_files
           WHERE team_id=? AND shared_by=? AND file_path=?"""
        ...

    @abc.abstractmethod
    async def count_shared_files_in_team(self, team_id: str) -> int:
        """SELECT COUNT(*) FROM shared_files WHERE team_id=?"""
        ...

    @abc.abstractmethod
    async def list_shared_files_with_pseudonyms(self, team_id: str) -> list[Record]:
        """SELECT sf.*, u.pseudonym AS shared_by_pseudonym
           FROM shared_files sf JOIN users u ...
           WHERE sf.team_id=? ORDER BY sf.shared_at DESC"""
        ...

    @abc.abstractmethod
    async def insert_shared_file(self, file_record: Record) -> None:
        """INSERT INTO shared_files (id, team_id, shared_by, file_path,
                  file_hash, description, origin_user_id) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def count_shared_files(self, team_id: Optional[str] = None) -> int:
        """SELECT COUNT(*) FROM shared_files.
        If team_id is provided, counts only files in that team
        (delegates to count_shared_files_in_team)."""
        ...

    # =================================================================
    # AUDIT LOG (4 methods)
    # =================================================================

    @abc.abstractmethod
    async def insert_audit_entry(
        self, entry_id: str, team_id: str, actor_id: str,
        action: str, resource_ref: Optional[str], details: Optional[str]
    ) -> None:
        """INSERT INTO audit_log (id, team_id, actor_id, action,
                  resource_ref, details) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def get_license_change_history(
        self, team_id: str, limit: int = 10
    ) -> list[Record]:
        """SELECT details, created_at FROM audit_log
           WHERE team_id=? AND action='license_generated'
           ORDER BY created_at DESC LIMIT ?"""
        ...

    @abc.abstractmethod
    async def list_audit_entries(
        self, team_id: str, limit: int = 100
    ) -> list[Record]:
        """SELECT al.*, u.pseudonym AS actor_pseudonym
           FROM audit_log al JOIN users u ...
           WHERE al.team_id=? ORDER BY al.created_at DESC LIMIT ?"""
        ...

    @abc.abstractmethod
    async def list_audit_entries_filtered(
        self, team_id: str, action: str, limit: int = 100
    ) -> list[Record]:
        """SELECT al.*, u.pseudonym AS actor_pseudonym
           FROM audit_log al JOIN users u ...
           WHERE al.team_id=? AND al.action=?
           ORDER BY al.created_at DESC LIMIT ?"""
        ...

    @abc.abstractmethod
    async def count_audit_entries(self) -> int:
        """SELECT COUNT(*) FROM audit_log"""
        ...

    # =================================================================
    # COLLABORATION CONTRACTS (9 methods)
    # =================================================================

    @abc.abstractmethod
    async def get_max_contract_version(self, team_id: str) -> int:
        """SELECT MAX(contract_version) FROM collaboration_contracts
           WHERE team_id=?   Returns 0 if no contracts exist."""
        ...

    @abc.abstractmethod
    async def get_contract_by_id(self, contract_id: str) -> Optional[Record]:
        """SELECT * FROM collaboration_contracts WHERE id=?"""
        ...

    @abc.abstractmethod
    async def get_contract_by_id_and_team(
        self, contract_id: str, team_id: str
    ) -> Optional[Record]:
        """SELECT * FROM collaboration_contracts WHERE id=? AND team_id=?"""
        ...

    @abc.abstractmethod
    async def count_confirmed_contracts(self) -> int:
        """SELECT COUNT(*) FROM collaboration_contracts WHERE status='confirmed'"""
        ...

    @abc.abstractmethod
    async def count_confirmed_contracts_for_team(self, team_id: str) -> int:
        """SELECT COUNT(*) FROM collaboration_contracts
           WHERE team_id=? AND status='confirmed'"""
        ...

    @abc.abstractmethod
    async def supersede_pending_contracts(self, team_id: str) -> None:
        """UPDATE collaboration_contracts SET status='superseded'
           WHERE team_id=? AND status IN ('pending','partial')"""
        ...

    @abc.abstractmethod
    async def insert_contract(self, contract: Record) -> None:
        """INSERT INTO collaboration_contracts (id, team_id, contract_version,
                  ..., status) VALUES (...)"""
        ...

    @abc.abstractmethod
    async def update_contract_confirmation_a(
        self, contract_id: str, user_id: str,
        git_hash: str, repo_url: str, confirmed_at: str
    ) -> None:
        """UPDATE collaboration_contracts
           SET confirmation_a_user_id=?, confirmation_a_git_hash=?,
               confirmation_a_repo_url=?, confirmation_a_at=?
           WHERE id=?"""
        ...

    @abc.abstractmethod
    async def update_contract_confirmation_b(
        self, contract_id: str, user_id: str,
        git_hash: str, repo_url: str, confirmed_at: str
    ) -> None:
        """UPDATE collaboration_contracts
           SET confirmation_b_user_id=?, confirmation_b_git_hash=?,
               confirmation_b_repo_url=?, confirmation_b_at=?
           WHERE id=?"""
        ...

    @abc.abstractmethod
    async def update_contract_status(self, contract_id: str, status: str) -> None:
        """UPDATE collaboration_contracts SET status=? WHERE id=?"""
        ...

    # =================================================================
    # GITHUB CONNECTIONS (5 methods)
    # =================================================================

    @abc.abstractmethod
    async def get_github_connection(self, user_id: str) -> Optional[Record]:
        """Get GitHub connection info for a user.
        Returns dict with github_username, installation_id, authorized_repos, connected_at
        or None if not connected."""
        ...

    @abc.abstractmethod
    async def upsert_github_connection(
        self, user_id: str, github_username: str,
        installation_id: int, authorized_repos: list[str]
    ) -> None:
        """Create or update a user's GitHub connection.
        In Firestore: embedded in users/{user_id}.github_connection
        In SQLite: INSERT OR REPLACE into github_connections table."""
        ...

    @abc.abstractmethod
    async def delete_github_connection(self, user_id: str) -> None:
        """Remove a user's GitHub connection.
        In Firestore: set github_connection field to None.
        In SQLite: DELETE from github_connections."""
        ...

    @abc.abstractmethod
    async def get_github_connections_for_team(self, team_id: str) -> list[Record]:
        """Get GitHub connections for all members of a team.
        Returns list of dicts with user_id, github_username, installation_id, authorized_repos.
        Only includes members who have a GitHub connection."""
        ...

    @abc.abstractmethod
    async def update_github_authorized_repos(
        self, user_id: str, authorized_repos: list[str]
    ) -> None:
        """Update only the authorized_repos list for a user's GitHub connection."""
        ...

    # =================================================================
    # UTILITY (1 method)
    # =================================================================

    @abc.abstractmethod
    async def compute_age_in_days(self, iso_timestamp: str) -> float:
        """Returns (now - timestamp) in fractional days.
        In SQLite: SELECT julianday('now') - julianday(?)
        In Firestore: Python datetime arithmetic."""
        ...

    # =================================================================
    # HEALTH / STATS (aggregated)
    # =================================================================

    @abc.abstractmethod
    async def health_stats(self) -> Record:
        """Returns dict with counts: users, commits, matches, teams,
        pending_requests, ratings, tickets, audit_entries,
        shared_files, confirmed_contracts."""
        ...

    # =================================================================
    # BATCH OPERATIONS (for Firestore atomicity)
    # =================================================================

    @abc.abstractmethod
    async def create_team_with_members(
        self,
        team_id: str = "",
        team_name: str = "",
        license_type: str = "joint-equal",
        member_user_ids: Optional[list[str]] = None,
        role: str = "co-lead",
        *,
        team: Optional[Record] = None,
        members: Optional[list[Record]] = None,
    ) -> None:
        """Atomically create a team + insert all members.
        Accepts either positional args (team_id, team_name, etc.) OR
        dict-based kwargs (team={...}, members=[{...}]).
        In SQLite: sequential inserts in same transaction.
        In Firestore: batch write."""
        ...

    @abc.abstractmethod
    async def submit_commit_and_mark_latest(
        self, commit: Record, previous_commit_id: Optional[str] = None
    ) -> None:
        """Atomically insert a new commit and mark the previous one as not-latest.
        In SQLite: sequential inserts (single connection = implicit transaction).
        In Firestore: batch write setting is_latest=false on old, true on new.
        Also syncs to Algolia if available."""
        ...

    # =================================================================
    # CONVENIENCE ALIASES
    # =================================================================
    # Concrete (non-abstract) methods that delegate to canonical abstract
    # methods above. These bridge naming differences between the server
    # code and the protocol without duplicating implementation.

    # -- Team Members --
    async def get_team_member(self, team_id: str, user_id: str) -> Optional[Record]:
        """Alias for get_team_membership."""
        return await self.get_team_membership(team_id, user_id)

    # -- Teams --
    async def get_teams_for_user(self, user_id: str) -> list[Record]:
        """Alias for get_teams_by_user."""
        return await self.get_teams_by_user(user_id)

    # -- Commits --
    async def get_commits_by_user(self, user_id: str) -> list[Record]:
        """Alias for get_all_commits_by_user."""
        return await self.get_all_commits_by_user(user_id)

    async def get_next_commit_version(self, user_id: str) -> int:
        """Returns max_commit_version + 1."""
        return (await self.get_max_commit_version(user_id)) + 1

    # -- Contracts --
    async def get_next_contract_version(self, team_id: str) -> int:
        """Returns max_contract_version + 1."""
        return (await self.get_max_contract_version(team_id)) + 1

    async def get_contract(self, contract_id: str, team_id: str) -> Optional[Record]:
        """Alias for get_contract_by_id_and_team."""
        return await self.get_contract_by_id_and_team(contract_id, team_id)

    async def update_contract_confirmation(
        self, contract_id: str, slot: str, user_id: str,
        git_hash: str, repo_url: str, confirmed_at: str
    ) -> None:
        """Unified contract confirmation — dispatches to slot a or b."""
        if slot == "a":
            await self.update_contract_confirmation_a(
                contract_id, user_id, git_hash, repo_url, confirmed_at)
        else:
            await self.update_contract_confirmation_b(
                contract_id, user_id, git_hash, repo_url, confirmed_at)

    # -- Collaboration Requests --
    async def create_collaboration_request(self, data: Record) -> None:
        """Dict-based wrapper for insert_collaboration_request."""
        await self.insert_collaboration_request(
            request_id=data["id"],
            match_id=data["match_id"],
            requester_id=data["requester_id"],
            recipient_id=data["recipient_id"],
            message=data.get("message", ""),
        )

    async def get_incoming_requests_with_details(self, recipient_id: str) -> list[Record]:
        """Alias for get_incoming_requests (Firestore version already joins details)."""
        return await self.get_incoming_requests(recipient_id)

    async def get_outgoing_requests_with_details(self, requester_id: str) -> list[Record]:
        """Alias for get_outgoing_requests (Firestore version already joins details)."""
        return await self.get_outgoing_requests(requester_id)

    # -- Tickets --
    async def list_tickets(
        self, team_id: str, status: Optional[str] = None,
        area: Optional[str] = None, ticket_type: Optional[str] = None
    ) -> list[Record]:
        """Alias for list_tickets_with_filters."""
        return await self.list_tickets_with_filters(
            team_id, status=status, area=area, ticket_type=ticket_type)

    async def count_open_tickets_by_user(self, team_id: str, user_id: str) -> int:
        """Alias for count_open_tickets_by_author."""
        return await self.count_open_tickets_by_author(team_id, user_id)

    async def count_tickets_by_status(self, team_id: str) -> list[Record]:
        """Alias for get_ticket_status_summary."""
        return await self.get_ticket_status_summary(team_id)

    async def update_ticket_status(
        self, team_id: str, ticket_id: str,
        status: str = "resolved", resolved_by: str = "",
        resolved_at: str = ""
    ) -> None:
        """Enhanced resolve_ticket with team_id and timestamp."""
        await self.resolve_ticket(ticket_id, resolved_by, status)

    # -- Reveal Consents --
    async def find_reveal_consent(
        self, team_id: str, requester_id: str, resource_ref: str,
        status: str = "pending", approver_id: Optional[str] = None
    ) -> Optional[Record]:
        """Unified finder: dispatches to pending/approved/pair variants."""
        if status == "pending":
            return await self.find_pending_reveal(team_id, requester_id, resource_ref)
        elif status == "approved" and approver_id:
            return await self.find_approved_reveal_for_pair(team_id, requester_id, approver_id)
        elif status == "approved":
            return await self.find_approved_reveal(team_id, requester_id, resource_ref)
        return None

    async def get_reveal_consents_with_pseudonyms(self, team_id: str) -> list[Record]:
        """Alias for get_team_consents_with_pseudonyms."""
        return await self.get_team_consents_with_pseudonyms(team_id)

    async def get_approved_reveal_targets(
        self, team_id: str, user_id: str, direction: str = "approver"
    ) -> list[str]:
        """Unified reveal direction query. direction='approver' means who can see
        user's commits; direction='requester' means whose commits user can see."""
        if direction == "approver":
            return await self.get_reveal_visible_to(team_id, user_id)
        else:
            return await self.get_reveal_can_see(team_id, user_id)

    # -- Shared Files --
    async def find_shared_file(
        self, team_id: str, shared_by: str, file_path: str
    ) -> Optional[Record]:
        """Alias for find_shared_file_by_path."""
        return await self.find_shared_file_by_path(team_id, shared_by, file_path)

    async def get_shared_files_with_pseudonyms(self, team_id: str) -> list[Record]:
        """Alias for list_shared_files_with_pseudonyms."""
        return await self.list_shared_files_with_pseudonyms(team_id)

    # -- Audit --
    async def get_audit_entries(
        self, team_id: str, action: Optional[str] = None, limit: int = 100
    ) -> list[Record]:
        """Unified audit query: if action is provided, filters; otherwise returns all."""
        if action:
            return await self.list_audit_entries_filtered(team_id, action, limit)
        return await self.list_audit_entries(team_id, limit)

    # -- Users --
    async def update_user_honesty_penalty(
        self, user_id: str, penalty_value: float
    ) -> None:
        """Simplified penalty: sets both running_honesty and avg_honesty to penalty_value."""
        await self.penalize_user_honesty(user_id, penalty_value, penalty_value)
