"""
Unit tests for FirestoreDataStore — all methods against Firestore Emulator.

Requires: firebase emulators:start --only firestore
Env auto-configured by conftest.py (FIRESTORE_EMULATOR_HOST=127.0.0.1:8080)

~65 tests organized by domain entity.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.firestore_datastore import FirestoreDataStore


def _uid() -> str:
    return str(uuid.uuid4())


# =====================================================================
# USERS (9 tests)
# =====================================================================


class TestUsers:
    async def test_insert_and_find_by_email_hash(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "alice", "hash_alice")
        found = await ds.find_user_by_email_hash("hash_alice")
        assert found is not None
        assert found["id"] == uid

    async def test_find_by_email_hash_not_found(self, ds: FirestoreDataStore):
        result = await ds.find_user_by_email_hash("nonexistent")
        assert result is None

    async def test_get_user_by_id(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "bob", "hash_bob")
        user = await ds.get_user_by_id(uid)
        assert user is not None
        assert user["pseudonym"] == "bob"
        assert user["reputation_score"] == 100.0

    async def test_get_user_pseudonym(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "charlie", "hash_charlie")
        ps = await ds.get_user_pseudonym(uid)
        assert ps == "charlie"

    async def test_get_most_recent_user(self, ds: FirestoreDataStore):
        uid1 = _uid()
        uid2 = _uid()
        await ds.insert_user(uid1, "first", "hash_first")
        await ds.insert_user(uid2, "second", "hash_second")
        recent = await ds.get_most_recent_user()
        assert recent is not None
        # Should be one of them (timing might be identical)
        assert recent["pseudonym"] in ("first", "second")

    async def test_update_running_averages(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "dave", "hash_dave")
        await ds.update_user_running_averages(uid, 4.5, 3.8, 4.2)
        avgs = await ds.get_user_running_averages(uid)
        assert avgs is not None
        assert avgs["running_honesty"] == 4.5
        assert avgs["running_quality"] == 3.8
        assert avgs["running_effort"] == 4.2

    async def test_update_running_effort(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "eve", "hash_eve")
        await ds.update_user_running_effort(uid, 3.7)
        effort = await ds.get_user_running_effort(uid)
        assert effort == 3.7

    async def test_update_reputation_stats(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "frank", "hash_frank")
        await ds.update_user_reputation_stats(uid, 85.0, 5, 4.0, 4.5, 3.5)
        user = await ds.get_user_by_id(uid)
        assert user is not None
        assert user["reputation_score"] == 85.0
        assert user["total_ratings_received"] == 5
        assert user["avg_honesty"] == 4.0

    async def test_penalize_honesty(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "grace", "hash_grace")
        await ds.penalize_user_honesty(uid, 1.0, 1.5)
        user = await ds.get_user_by_id(uid)
        assert user is not None
        assert user["running_honesty"] == 1.0
        assert user["avg_honesty"] == 1.5

    async def test_count_users(self, ds: FirestoreDataStore):
        assert await ds.count_users() == 0
        await ds.insert_user(_uid(), "u1", "h1")
        await ds.insert_user(_uid(), "u2", "h2")
        assert await ds.count_users() == 2


# =====================================================================
# RESEARCH COMMITS (10 tests)
# =====================================================================


class TestCommits:
    async def _make_user(self, ds, name="tester"):
        uid = _uid()
        await ds.insert_user(uid, name, f"hash_{uid[:8]}")
        return uid

    async def _make_commit(self, ds, user_id, version=1, domain="ml", **kwargs):
        cid = _uid()
        commit = {
            "id": cid,
            "user_id": user_id,
            "version": version,
            "domain": domain,
            "subdomain": kwargs.get("subdomain", "deep learning"),
            "problem": kwargs.get("problem", "test problem"),
            "hypothesis": kwargs.get("hypothesis", "test hypothesis"),
            "overall_solidity": kwargs.get("overall_solidity", "functional"),
            "ot_score": kwargs.get("ot_score", 60.0),
            "ofc_score": kwargs.get("ofc_score", 55.0),
            "is_latest": kwargs.get("is_latest", True),
        }
        await ds.insert_commit(commit)
        return cid

    async def test_insert_and_get_by_id(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        cid = await self._make_commit(ds, uid)
        commit = await ds.get_commit_by_id(cid)
        assert commit is not None
        assert commit["user_id"] == uid
        assert commit["domain"] == "ml"

    async def test_get_latest_commit_by_user(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        await self._make_commit(ds, uid, version=1)
        cid2 = await self._make_commit(ds, uid, version=2)
        latest = await ds.get_latest_commit_by_user(uid)
        assert latest is not None
        assert latest["id"] == cid2
        assert latest["version"] == 2

    async def test_get_latest_scores_by_user(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        await self._make_commit(ds, uid, ot_score=70.0, ofc_score=65.0)
        scores = await ds.get_latest_scores_by_user(uid)
        assert scores is not None
        assert scores["ot_score"] == 70.0
        assert scores["ofc_score"] == 65.0

    async def test_get_max_commit_version(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        assert await ds.get_max_commit_version(uid) == 0
        await self._make_commit(ds, uid, version=1)
        await self._make_commit(ds, uid, version=2)
        assert await ds.get_max_commit_version(uid) == 2

    async def test_get_next_commit_version_alias(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        assert await ds.get_next_commit_version(uid) == 1
        await self._make_commit(ds, uid, version=1)
        assert await ds.get_next_commit_version(uid) == 2

    async def test_get_all_commits_by_user(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        await self._make_commit(ds, uid, version=1)
        await self._make_commit(ds, uid, version=2)
        commits = await ds.get_all_commits_by_user(uid)
        assert len(commits) == 2
        # Should be ordered DESC
        assert commits[0]["version"] == 2

    async def test_get_corpus_commits_excludes_user(self, ds: FirestoreDataStore):
        uid_a = await self._make_user(ds, "alice")
        uid_b = await self._make_user(ds, "bob")
        await self._make_commit(ds, uid_a, domain="ml")
        await self._make_commit(ds, uid_b, domain="ml")
        corpus = await ds.get_corpus_commits("ml", uid_a)
        assert len(corpus) == 1
        assert corpus[0]["user_id"] == uid_b

    async def test_find_candidate_commits_in_domain(self, ds: FirestoreDataStore):
        uid_a = await self._make_user(ds, "alice")
        uid_b = await self._make_user(ds, "bob")
        await self._make_commit(ds, uid_a, domain="ml", is_latest=True)
        await self._make_commit(ds, uid_b, domain="ml", is_latest=True)
        candidates = await ds.find_candidate_commits_in_domain(uid_a, "ml")
        assert len(candidates) == 1
        assert candidates[0]["pseudonym"] == "bob"

    async def test_search_commits_by_keywords_firestore_fallback(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds, "searcher")
        await self._make_commit(ds, uid, domain="machine learning")
        # Firestore fallback matches exact domain
        results = await ds.search_commits_by_keywords(["machine learning"], limit=5)
        assert len(results) >= 1
        assert results[0]["pseudonym"] == "searcher"

    async def test_submit_commit_and_mark_latest(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        cid1 = _uid()
        commit1 = {
            "id": cid1, "user_id": uid, "version": 1, "domain": "ml",
            "is_latest": True, "ot_score": 50.0, "ofc_score": 50.0,
        }
        await ds.submit_commit_and_mark_latest(commit1)
        # Submit v2, marking v1 as not-latest
        cid2 = _uid()
        commit2 = {
            "id": cid2, "user_id": uid, "version": 2, "domain": "ml",
            "ot_score": 60.0, "ofc_score": 60.0,
        }
        await ds.submit_commit_and_mark_latest(commit2, previous_commit_id=cid1)
        c1 = await ds.get_commit_by_id(cid1)
        c2 = await ds.get_commit_by_id(cid2)
        assert c1["is_latest"] is False
        assert c2["is_latest"] is True

    async def test_count_commits(self, ds: FirestoreDataStore):
        uid = await self._make_user(ds)
        assert await ds.count_commits() == 0
        await self._make_commit(ds, uid)
        assert await ds.count_commits() == 1


# =====================================================================
# MATCHES (3 tests)
# =====================================================================


class TestMatches:
    async def test_upsert_and_find(self, ds: FirestoreDataStore):
        mid = _uid()
        await ds.upsert_match({
            "id": mid, "user_a_id": "ua", "user_b_id": "ub",
            "semaphore": "GREEN", "complementarity_score": 75.0,
        })
        found = await ds.find_match_between_users("ua", "ub")
        assert found is not None
        assert found["semaphore"] == "GREEN"

    async def test_find_match_bidirectional(self, ds: FirestoreDataStore):
        mid = _uid()
        await ds.upsert_match({
            "id": mid, "user_a_id": "ua", "user_b_id": "ub",
            "semaphore": "YELLOW",
        })
        # Should find in reverse direction too
        found = await ds.find_match_between_users("ub", "ua")
        assert found is not None
        assert found["semaphore"] == "YELLOW"

    async def test_count_matches(self, ds: FirestoreDataStore):
        assert await ds.count_matches() == 0
        await ds.upsert_match({"id": _uid(), "user_a_id": "a", "user_b_id": "b"})
        assert await ds.count_matches() == 1


# =====================================================================
# COLLABORATION REQUESTS (7 tests)
# =====================================================================


class TestRequests:
    async def _setup_users_and_match(self, ds):
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "alice", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "bob", f"h_{uid_b[:8]}")
        mid = _uid()
        await ds.upsert_match({
            "id": mid, "user_a_id": uid_a, "user_b_id": uid_b,
            "semaphore": "GREEN", "complementarity_score": 80.0,
            "semaphore_reason_a": "good", "semaphore_reason_b": "good",
            "a_gains_from_b": 10, "b_gains_from_a": 8,
        })
        return uid_a, uid_b, mid

    async def test_insert_and_find_pending(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "Let's collaborate")
        found = await ds.find_pending_request(uid_a, uid_b)
        assert found is not None
        assert found["message"] == "Let's collaborate"
        assert found["status"] == "pending"

    async def test_create_collaboration_request_dict(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        rid = _uid()
        await ds.create_collaboration_request({
            "id": rid, "match_id": mid,
            "requester_id": uid_a, "recipient_id": uid_b, "message": "hi",
        })
        found = await ds.find_pending_request(uid_a, uid_b)
        assert found is not None

    async def test_get_incoming_requests(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "msg")
        incoming = await ds.get_incoming_requests(uid_b)
        assert len(incoming) == 1
        assert incoming[0]["requester_pseudonym"] == "alice"
        assert incoming[0]["semaphore"] == "GREEN"

    async def test_get_outgoing_requests(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "msg")
        outgoing = await ds.get_outgoing_requests(uid_a)
        assert len(outgoing) == 1
        assert outgoing[0]["recipient_pseudonym"] == "bob"

    async def test_update_request_status(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "msg")
        await ds.update_request_status(rid, "accepted")
        # Should no longer be pending
        found = await ds.find_pending_request(uid_a, uid_b)
        assert found is None

    async def test_get_request_for_recipient(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "msg")
        req = await ds.get_request_for_recipient(rid, uid_b)
        assert req is not None
        # Wrong recipient returns None
        req2 = await ds.get_request_for_recipient(rid, uid_a)
        assert req2 is None

    async def test_count_pending_requests(self, ds: FirestoreDataStore):
        uid_a, uid_b, mid = await self._setup_users_and_match(ds)
        assert await ds.count_pending_requests() == 0
        rid = _uid()
        await ds.insert_collaboration_request(rid, mid, uid_a, uid_b, "msg")
        assert await ds.count_pending_requests() == 1


# =====================================================================
# TEAMS + MEMBERS (11 tests)
# =====================================================================


class TestTeams:
    async def _make_users(self, ds, n=2):
        uids = []
        for i in range(n):
            uid = _uid()
            await ds.insert_user(uid, f"user_{i}", f"h_{uid[:8]}")
            uids.append(uid)
        return uids

    async def test_create_team_with_members_positional(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(tid, "Team Alpha", "joint-equal", uids)
        team = await ds.get_team_by_id(tid)
        assert team is not None
        assert team["name"] == "Team Alpha"
        members = await ds.get_team_member_ids(tid)
        assert set(members) == set(uids)

    async def test_create_team_with_members_dict(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(
            team={"id": tid, "name": "Team Beta", "license_type": "advisory-only"},
            members=[{"user_id": u, "role": "co-lead"} for u in uids],
        )
        team = await ds.get_team_by_id(tid)
        assert team["license_type"] == "advisory-only"

    async def test_get_team_name(self, ds: FirestoreDataStore):
        tid = _uid()
        await ds.insert_team(tid, "Gamma Team")
        assert await ds.get_team_name(tid) == "Gamma Team"

    async def test_get_team_license_info(self, ds: FirestoreDataStore):
        tid = _uid()
        await ds.insert_team(tid, "Delta", "joint-weighted")
        info = await ds.get_team_license_info(tid)
        assert info is not None
        assert info["license_type"] == "joint-weighted"

    async def test_get_team_member_alias(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(tid, "T", "joint-equal", uids)
        member = await ds.get_team_member(tid, uids[0])
        assert member is not None
        assert member["role"] == "co-lead"

    async def test_get_team_member_pseudonyms(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(tid, "T", "joint-equal", uids)
        pseudonyms = await ds.get_team_member_pseudonyms(tid)
        assert len(pseudonyms) == 2
        names = {p["pseudonym"] for p in pseudonyms}
        assert "user_0" in names
        assert "user_1" in names

    async def test_get_team_members_with_profiles(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(tid, "T", "joint-equal", uids)
        profiles = await ds.get_team_members_with_profiles(tid)
        assert len(profiles) == 2
        assert all("reputation_score" in p for p in profiles)

    async def test_get_teams_for_user(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(tid, "T", "joint-equal", uids)
        teams = await ds.get_teams_for_user(uids[0])
        assert len(teams) == 1
        assert teams[0]["id"] == tid

    async def test_update_team_license(self, ds: FirestoreDataStore):
        tid = _uid()
        await ds.insert_team(tid, "T", "joint-equal")
        await ds.update_team_license(tid, "advisory-only")
        lt = await ds.get_team_license_type(tid)
        assert lt == "advisory-only"

    async def test_update_member_contribution(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        await ds.create_team_with_members(tid, "T", "joint-equal", uids)
        await ds.update_member_contribution(tid, uids[0], 60.0)
        member = await ds.get_team_membership(tid, uids[0])
        assert member["contribution_percentage"] == 60.0

    async def test_count_teams_and_members(self, ds: FirestoreDataStore):
        uids = await self._make_users(ds)
        tid = _uid()
        assert await ds.count_teams() == 0
        await ds.create_team_with_members(tid, "T", "joint-equal", uids)
        assert await ds.count_teams() == 1
        assert await ds.count_team_members(tid) == 2


# =====================================================================
# RATINGS (7 tests)
# =====================================================================


class TestRatings:
    async def _setup_team(self, ds):
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "rater_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "rater_b", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Rating Team", "joint-equal", [uid_a, uid_b])
        return tid, uid_a, uid_b

    async def test_insert_and_find_rating(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 4, "quality": 5, "effort": 3, "comment": "good",
        })
        found = await ds.find_rating(tid, uid_a, uid_b)
        assert found is not None

    async def test_get_rating(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 5, "quality": 4, "effort": 4, "comment": "great",
        })
        r = await ds.get_rating(tid, uid_a, uid_b)
        assert r is not None
        assert r["honesty"] == 5

    async def test_get_ratings_received_desc(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 4, "quality": 4, "effort": 4, "comment": "",
        })
        ratings = await ds.get_ratings_received_desc(uid_b)
        assert len(ratings) == 1

    async def test_get_ratings_given_desc(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 4, "quality": 4, "effort": 4, "comment": "",
        })
        ratings = await ds.get_ratings_given_desc(uid_a)
        assert len(ratings) == 1

    async def test_count_ratings_received(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        assert await ds.count_ratings_received(uid_b) == 0
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 4, "quality": 4, "effort": 4, "comment": "",
        })
        assert await ds.count_ratings_received(uid_b) == 1

    async def test_reveal_team_ratings(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 4, "quality": 4, "effort": 4, "comment": "",
        })
        await ds.reveal_team_ratings(tid)
        r = await ds.find_rating(tid, uid_a, uid_b)
        assert r["is_revealed"] == 1

    async def test_count_ratings(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        assert await ds.count_ratings() == 0
        await ds.insert_rating({
            "team_id": tid, "rater_id": uid_a, "rated_id": uid_b,
            "honesty": 4, "quality": 4, "effort": 4, "comment": "",
        })
        assert await ds.count_ratings() == 1


# =====================================================================
# TICKETS (7 tests)
# =====================================================================


class TestTickets:
    async def _setup_team(self, ds):
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "ticket_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "ticket_b", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Ticket Team", "joint-equal", [uid_a, uid_b])
        return tid, uid_a, uid_b

    async def _make_ticket(self, ds, tid, author_id, **kwargs):
        ticket_id = _uid()
        await ds.insert_ticket({
            "id": ticket_id, "team_id": tid, "author_id": author_id,
            "type": kwargs.get("type", "need_help"),
            "area": kwargs.get("area", "code"),
            "title": kwargs.get("title", "Need help"),
            "description": kwargs.get("description", "Please help"),
            "priority": kwargs.get("priority", "important"),
            "status": kwargs.get("status", "open"),
        })
        return ticket_id

    async def test_insert_and_get_by_id(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        ticket_id = await self._make_ticket(ds, tid, uid_a)
        ticket = await ds.get_ticket_by_id(ticket_id)
        assert ticket is not None
        assert ticket["title"] == "Need help"
        assert ticket["team_id"] == tid

    async def test_count_open_tickets_by_author(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        assert await ds.count_open_tickets_by_author(tid, uid_a) == 0
        await self._make_ticket(ds, tid, uid_a)
        assert await ds.count_open_tickets_by_author(tid, uid_a) == 1

    async def test_list_tickets_with_filters(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        await self._make_ticket(ds, tid, uid_a, area="code")
        await self._make_ticket(ds, tid, uid_a, area="theory")
        # Filter by area
        code_tickets = await ds.list_tickets_with_filters(tid, area="code")
        assert len(code_tickets) == 1
        assert code_tickets[0]["area"] == "code"

    async def test_list_tickets_alias(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        await self._make_ticket(ds, tid, uid_a)
        tickets = await ds.list_tickets(tid)
        assert len(tickets) == 1

    async def test_resolve_ticket(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        ticket_id = await self._make_ticket(ds, tid, uid_a)
        await ds.resolve_ticket(ticket_id, uid_b)
        ticket = await ds.get_ticket_by_id(ticket_id)
        assert ticket["status"] == "resolved"
        assert ticket["resolved_by"] == uid_b

    async def test_count_resolved_tickets_by_member(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        ticket_id = await self._make_ticket(ds, tid, uid_a)
        assert await ds.count_resolved_tickets_by_member(tid, uid_b) == 0
        await ds.resolve_ticket(ticket_id, uid_b)
        assert await ds.count_resolved_tickets_by_member(tid, uid_b) == 1

    async def test_ticket_status_summary(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await self._make_ticket(ds, tid, uid_a)
        t2 = await self._make_ticket(ds, tid, uid_a)
        await ds.resolve_ticket(t2, uid_b)
        summary = await ds.get_ticket_status_summary(tid)
        status_map = {s["status"]: s["c"] for s in summary}
        assert status_map.get("open", 0) == 1
        assert status_map.get("resolved", 0) == 1


# =====================================================================
# REVEAL CONSENTS (9 tests)
# =====================================================================


class TestReveals:
    async def _setup_team(self, ds):
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "reveal_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "reveal_b", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Reveal Team", "joint-equal", [uid_a, uid_b])
        return tid, uid_a, uid_b

    async def _make_consent(self, ds, tid, requester_id, approver_id, status="pending"):
        cid = _uid()
        await ds.insert_reveal_consent({
            "id": cid, "team_id": tid, "level": 3,
            "requester_id": requester_id, "approver_id": approver_id,
            "resource_type": "commit", "resource_ref": f"commit_{requester_id[:8]}",
            "status": status,
        })
        return cid

    async def test_insert_and_find_pending(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        found = await ds.find_pending_reveal(tid, uid_a, f"commit_{uid_a[:8]}")
        assert found is not None

    async def test_find_approved_reveal(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        await ds.update_reveal_consent_status(cid, "approved", team_id=tid)
        found = await ds.find_approved_reveal(tid, uid_a, f"commit_{uid_a[:8]}")
        assert found is not None

    async def test_find_approved_reveal_for_pair(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        await ds.update_reveal_consent_status(cid, "approved", team_id=tid)
        found = await ds.find_approved_reveal_for_pair(tid, uid_a, uid_b)
        assert found is not None

    async def test_find_reveal_consent_unified(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        # Pending
        found = await ds.find_reveal_consent(tid, uid_a, f"commit_{uid_a[:8]}", status="pending")
        assert found is not None
        # Approve and check
        await ds.update_reveal_consent_status(cid, "approved", team_id=tid)
        found2 = await ds.find_reveal_consent(
            tid, uid_a, f"commit_{uid_a[:8]}", status="approved", approver_id=uid_b
        )
        assert found2 is not None

    async def test_count_pending_reveals(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        assert await ds.count_pending_reveals(tid) == 0
        await self._make_consent(ds, tid, uid_a, uid_b)
        assert await ds.count_pending_reveals(tid) == 1

    async def test_count_approved_reveals_direction(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        await ds.update_reveal_consent_status(cid, "approved", team_id=tid)
        count = await ds.count_approved_reveals_direction(tid, uid_b, uid_a)
        assert count == 1

    async def test_get_consents_with_pseudonyms(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await self._make_consent(ds, tid, uid_a, uid_b)
        consents = await ds.get_team_consents_with_pseudonyms(tid)
        assert len(consents) == 1
        assert consents[0]["requester_pseudonym"] == "reveal_a"
        assert consents[0]["approver_pseudonym"] == "reveal_b"

    async def test_reveal_visible_to_and_can_see(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        await ds.update_reveal_consent_status(cid, "approved", team_id=tid)
        # uid_b approved → uid_a can see uid_b's stuff
        visible = await ds.get_reveal_visible_to(tid, uid_b)
        assert "reveal_a" in visible
        can_see = await ds.get_reveal_can_see(tid, uid_a)
        assert "reveal_b" in can_see

    async def test_get_consent_by_id(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        cid = await self._make_consent(ds, tid, uid_a, uid_b)
        consent = await ds.get_reveal_consent_by_id(cid)
        assert consent is not None
        assert consent["team_id"] == tid


# =====================================================================
# SHARED FILES (5 tests)
# =====================================================================


class TestSharedFiles:
    async def _setup_team(self, ds):
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "file_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "file_b", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "File Team", "joint-equal", [uid_a, uid_b])
        return tid, uid_a, uid_b

    async def test_insert_and_find_by_path(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        fid = _uid()
        await ds.insert_shared_file({
            "id": fid, "team_id": tid, "shared_by": uid_a,
            "file_path": "/src/main.py", "file_hash": "abc123",
            "description": "main file", "origin_user_id": uid_a,
        })
        found = await ds.find_shared_file_by_path(tid, uid_a, "/src/main.py")
        assert found is not None

    async def test_find_shared_file_alias(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        fid = _uid()
        await ds.insert_shared_file({
            "id": fid, "team_id": tid, "shared_by": uid_a,
            "file_path": "/readme.md", "file_hash": "def456",
            "description": "readme", "origin_user_id": uid_a,
        })
        found = await ds.find_shared_file(tid, uid_a, "/readme.md")
        assert found is not None

    async def test_find_file_by_hash_other_user(self, ds: FirestoreDataStore):
        tid, uid_a, uid_b = await self._setup_team(ds)
        await ds.insert_shared_file({
            "id": _uid(), "team_id": tid, "shared_by": uid_a,
            "file_path": "/data.csv", "file_hash": "hash_xyz",
            "description": "data", "origin_user_id": uid_a,
        })
        # uid_b searches for same hash → should find uid_a's file
        found = await ds.find_file_by_hash_other_user("hash_xyz", uid_b)
        assert found is not None
        assert found["origin_user_id"] == uid_a
        # uid_a searches → should NOT find (same user)
        not_found = await ds.find_file_by_hash_other_user("hash_xyz", uid_a)
        assert not_found is None

    async def test_count_shared_files(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        assert await ds.count_shared_files() == 0
        assert await ds.count_shared_files_in_team(tid) == 0
        await ds.insert_shared_file({
            "id": _uid(), "team_id": tid, "shared_by": uid_a,
            "file_path": "/f1.py", "file_hash": "h1",
            "description": "", "origin_user_id": uid_a,
        })
        assert await ds.count_shared_files() == 1
        assert await ds.count_shared_files_in_team(tid) == 1

    async def test_list_files_with_pseudonyms(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        await ds.insert_shared_file({
            "id": _uid(), "team_id": tid, "shared_by": uid_a,
            "file_path": "/f.py", "file_hash": "hh",
            "description": "desc", "origin_user_id": uid_a,
        })
        files = await ds.list_shared_files_with_pseudonyms(tid)
        assert len(files) == 1
        assert files[0]["shared_by_pseudonym"] == "file_a"


# =====================================================================
# AUDIT LOG (5 tests)
# =====================================================================


class TestAudit:
    async def _setup(self, ds):
        uid = _uid()
        await ds.insert_user(uid, "auditor", f"h_{uid[:8]}")
        tid = _uid()
        await ds.insert_team(tid, "Audit Team")
        await ds.insert_team_member(tid, uid)
        return tid, uid

    async def test_insert_and_list(self, ds: FirestoreDataStore):
        tid, uid = await self._setup(ds)
        await ds.insert_audit_entry(_uid(), tid, uid, "file_shared", "file_123", "shared a file")
        entries = await ds.list_audit_entries(tid)
        assert len(entries) == 1
        assert entries[0]["action"] == "file_shared"
        assert entries[0]["actor_pseudonym"] == "auditor"

    async def test_list_filtered(self, ds: FirestoreDataStore):
        tid, uid = await self._setup(ds)
        await ds.insert_audit_entry(_uid(), tid, uid, "file_shared", None, None)
        await ds.insert_audit_entry(_uid(), tid, uid, "license_generated", None, '{"type":"joint"}')
        filtered = await ds.list_audit_entries_filtered(tid, "license_generated")
        assert len(filtered) == 1
        assert filtered[0]["action"] == "license_generated"

    async def test_get_audit_entries_unified(self, ds: FirestoreDataStore):
        tid, uid = await self._setup(ds)
        await ds.insert_audit_entry(_uid(), tid, uid, "reveal_approved", None, None)
        await ds.insert_audit_entry(_uid(), tid, uid, "license_generated", None, None)
        # No filter
        all_entries = await ds.get_audit_entries(tid)
        assert len(all_entries) == 2
        # With filter
        filtered = await ds.get_audit_entries(tid, action="reveal_approved")
        assert len(filtered) == 1

    async def test_get_license_change_history(self, ds: FirestoreDataStore):
        tid, uid = await self._setup(ds)
        await ds.insert_audit_entry(
            _uid(), tid, uid, "license_generated", None, '{"type":"joint-equal"}'
        )
        history = await ds.get_license_change_history(tid)
        assert len(history) == 1
        assert "joint-equal" in (history[0]["details"] or "")

    async def test_count_audit_entries(self, ds: FirestoreDataStore):
        tid, uid = await self._setup(ds)
        assert await ds.count_audit_entries() == 0
        await ds.insert_audit_entry(_uid(), tid, uid, "test", None, None)
        assert await ds.count_audit_entries() == 1


# =====================================================================
# CONTRACTS (9 tests)
# =====================================================================


class TestContracts:
    async def _setup_team(self, ds):
        uid_a, uid_b = _uid(), _uid()
        await ds.insert_user(uid_a, "contract_a", f"h_{uid_a[:8]}")
        await ds.insert_user(uid_b, "contract_b", f"h_{uid_b[:8]}")
        tid = _uid()
        await ds.create_team_with_members(tid, "Contract Team", "joint-equal", [uid_a, uid_b])
        return tid, uid_a, uid_b

    async def _make_contract(self, ds, tid, version=1, status="pending"):
        cid = _uid()
        await ds.insert_contract({
            "id": cid, "team_id": tid, "contract_version": version,
            "content_hash": "hash_abc", "content": "# Contract",
            "status": status,
            "confirmation_a_user_id": None, "confirmation_a_git_hash": None,
            "confirmation_a_repo_url": None, "confirmation_a_at": None,
            "confirmation_b_user_id": None, "confirmation_b_git_hash": None,
            "confirmation_b_repo_url": None, "confirmation_b_at": None,
        })
        return cid

    async def test_insert_and_get_by_id(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        cid = await self._make_contract(ds, tid)
        contract = await ds.get_contract_by_id(cid)
        assert contract is not None
        assert contract["team_id"] == tid

    async def test_get_contract_by_id_and_team(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        cid = await self._make_contract(ds, tid)
        found = await ds.get_contract_by_id_and_team(cid, tid)
        assert found is not None
        # Wrong team
        not_found = await ds.get_contract_by_id_and_team(cid, "wrong_team")
        assert not_found is None

    async def test_get_contract_alias(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        cid = await self._make_contract(ds, tid)
        found = await ds.get_contract(cid, tid)
        assert found is not None

    async def test_get_max_and_next_contract_version(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        assert await ds.get_max_contract_version(tid) == 0
        assert await ds.get_next_contract_version(tid) == 1
        await self._make_contract(ds, tid, version=1)
        assert await ds.get_max_contract_version(tid) == 1
        assert await ds.get_next_contract_version(tid) == 2

    async def test_supersede_pending(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        cid1 = await self._make_contract(ds, tid, version=1, status="pending")
        cid2 = await self._make_contract(ds, tid, version=2, status="partial")
        await ds.supersede_pending_contracts(tid)
        c1 = await ds.get_contract_by_id(cid1)
        c2 = await ds.get_contract_by_id(cid2)
        assert c1["status"] == "superseded"
        assert c2["status"] == "superseded"

    async def test_confirm_slot_a(self, ds: FirestoreDataStore):
        tid, uid_a, _ = await self._setup_team(ds)
        cid = await self._make_contract(ds, tid)
        now = datetime.now(timezone.utc).isoformat()
        await ds.update_contract_confirmation_a(cid, uid_a, "abc123", "https://github.com/repo", now)
        c = await ds.get_contract_by_id(cid)
        assert c["confirmation_a_user_id"] == uid_a
        assert c["confirmation_a_git_hash"] == "abc123"

    async def test_confirm_slot_b(self, ds: FirestoreDataStore):
        tid, _, uid_b = await self._setup_team(ds)
        cid = await self._make_contract(ds, tid)
        now = datetime.now(timezone.utc).isoformat()
        await ds.update_contract_confirmation_b(cid, uid_b, "def456", "https://github.com/repo", now)
        c = await ds.get_contract_by_id(cid)
        assert c["confirmation_b_user_id"] == uid_b

    async def test_update_contract_status(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        cid = await self._make_contract(ds, tid)
        await ds.update_contract_status(cid, "confirmed")
        c = await ds.get_contract_by_id(cid)
        assert c["status"] == "confirmed"

    async def test_count_confirmed_contracts(self, ds: FirestoreDataStore):
        tid, _, _ = await self._setup_team(ds)
        assert await ds.count_confirmed_contracts() == 0
        assert await ds.count_confirmed_contracts_for_team(tid) == 0
        cid = await self._make_contract(ds, tid, status="confirmed")
        assert await ds.count_confirmed_contracts() == 1
        assert await ds.count_confirmed_contracts_for_team(tid) == 1


# =====================================================================
# UTILITY + HEALTH (2 tests)
# =====================================================================


class TestUtility:
    async def test_compute_age_in_days(self, ds: FirestoreDataStore):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        age = await ds.compute_age_in_days(yesterday)
        assert 0.9 < age < 1.1  # ~1 day, with some tolerance

    async def test_compute_age_invalid(self, ds: FirestoreDataStore):
        age = await ds.compute_age_in_days("not-a-date")
        assert age == 0.0

    async def test_health_stats_empty(self, ds: FirestoreDataStore):
        stats = await ds.health_stats()
        assert stats["users"] == 0
        assert stats["commits"] == 0
        assert stats["teams"] == 0
        assert stats["ratings"] == 0
        assert stats["confirmed_contracts"] == 0

    async def test_health_stats_populated(self, ds: FirestoreDataStore):
        uid = _uid()
        await ds.insert_user(uid, "health_user", "h_health")
        tid = _uid()
        await ds.insert_team(tid, "Health Team")
        stats = await ds.health_stats()
        assert stats["users"] == 1
        assert stats["teams"] == 1


# =====================================================================
# BUG REPORTS (3 tests)
# =====================================================================


class TestBugReports:
    async def test_insert_and_list_bug_report(self, ds: FirestoreDataStore):
        report_id = _uid()
        await ds.insert_bug_report({
            "id": report_id,
            "reporter_id": "anonymous",
            "tool_name": "research_match_register",
            "error_message": "Registration fails with empty email",
            "severity": "high",
            "steps_to_reproduce": "Call register with email=''",
            "server_version": "3.2.0",
        })
        reports = await ds.list_bug_reports()
        assert len(reports) == 1
        assert reports[0]["id"] == report_id
        assert reports[0]["severity"] == "high"
        assert reports[0]["reporter_id"] == "anonymous"
        assert reports[0]["server_version"] == "3.2.0"

    async def test_list_bug_reports_ordered(self, ds: FirestoreDataStore):
        """Reports should be returned newest-first (created_at DESC)."""
        rid1 = _uid()
        rid2 = _uid()
        # Insert with explicit timestamps to guarantee order
        ts_old = "2025-01-01T00:00:00+00:00"
        ts_new = "2026-01-01T00:00:00+00:00"
        await ds.insert_bug_report({
            "id": rid1,
            "reporter_id": "anonymous",
            "tool_name": None,
            "error_message": "Old bug report for ordering test",
            "severity": "low",
            "steps_to_reproduce": None,
            "server_version": "3.2.0",
            "created_at": ts_old,
        })
        await ds.insert_bug_report({
            "id": rid2,
            "reporter_id": "anonymous",
            "tool_name": None,
            "error_message": "New bug report for ordering test",
            "severity": "medium",
            "steps_to_reproduce": None,
            "server_version": "3.2.0",
            "created_at": ts_new,
        })
        reports = await ds.list_bug_reports()
        assert len(reports) == 2
        assert reports[0]["id"] == rid2  # newer first
        assert reports[1]["id"] == rid1

    async def test_list_bug_reports_limit(self, ds: FirestoreDataStore):
        """Limit parameter should cap the number of returned reports."""
        for _ in range(5):
            await ds.insert_bug_report({
                "id": _uid(),
                "reporter_id": "anonymous",
                "tool_name": None,
                "error_message": "Bulk bug report for limit test",
                "severity": "low",
                "steps_to_reproduce": None,
                "server_version": "3.2.0",
            })
        reports = await ds.list_bug_reports(limit=3)
        assert len(reports) == 3
