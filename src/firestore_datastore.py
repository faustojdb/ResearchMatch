"""
FirestoreDataStore — Firebase Firestore + Algolia implementation of DataStore.

Uses:
- Firebase Admin SDK for document storage (12 collections)
- Algolia for full-text search on research commits (cold_search)

Environment variables required:
- GOOGLE_APPLICATION_CREDENTIALS: path to Firebase service account JSON
- ALGOLIA_APP_ID: Algolia application ID
- ALGOLIA_API_KEY: Algolia admin API key
- ALGOLIA_INDEX_NAME: Algolia index name (default: research_commits)

Firestore collections:
  Top-level: users, research_commits, matches, collaboration_requests, teams,
             collaboration_contracts
  Subcollections under teams/{team_id}:
    members, ratings, tickets, reveal_consents, shared_files, audit_log
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from google.cloud import firestore  # type: ignore[import-untyped]
from google.cloud.firestore_v1.base_query import FieldFilter  # type: ignore[import-untyped]

from .datastore import DataStore, Record

logger = logging.getLogger("research_match.firestore")

# Algolia is optional — gracefully degrade if not installed / not configured
try:
    from algoliasearch.search.client import SearchClientSync  # type: ignore[import-untyped]
    HAS_ALGOLIA = True
except ImportError:
    HAS_ALGOLIA = False


def _now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _doc_to_record(doc_snapshot) -> Record:
    """Convert a Firestore DocumentSnapshot to a plain dict with 'id' field."""
    data = doc_snapshot.to_dict()
    if data is not None:
        data["id"] = doc_snapshot.id
    return data or {}


class FirestoreDataStore(DataStore):
    """Firestore + Algolia implementation of the DataStore protocol."""

    def __init__(self) -> None:
        self._db: Optional[firestore.Client] = None
        self._algolia: Any = None
        self._algolia_index: str = ""

    # =================================================================
    # SCHEMA / LIFECYCLE
    # =================================================================

    async def initialize(self) -> None:
        """Initialize Firestore client and Algolia (if configured)."""
        self._db = firestore.Client()
        logger.info("Firestore client initialized")

        # Algolia (optional)
        app_id = os.environ.get("ALGOLIA_APP_ID", "")
        api_key = os.environ.get("ALGOLIA_API_KEY", "")
        self._algolia_index = os.environ.get("ALGOLIA_INDEX_NAME", "research_commits")

        if HAS_ALGOLIA and app_id and api_key:
            self._algolia = SearchClientSync(app_id, api_key)
            logger.info("Algolia client initialized (index: %s)", self._algolia_index)
        else:
            logger.info("Algolia not configured — cold_search will use Firestore only")

    async def close(self) -> None:
        """Close Firestore client."""
        if self._db:
            self._db.close()
            self._db = None

    @property
    def db(self) -> firestore.Client:
        assert self._db is not None, "DataStore not initialized. Call initialize() first."
        return self._db

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _users_ref(self):
        return self.db.collection("users")

    def _commits_ref(self):
        return self.db.collection("research_commits")

    def _matches_ref(self):
        return self.db.collection("matches")

    def _requests_ref(self):
        return self.db.collection("collaboration_requests")

    def _teams_ref(self):
        return self.db.collection("teams")

    def _contracts_ref(self):
        return self.db.collection("collaboration_contracts")

    # Subcollection helpers
    def _team_members_ref(self, team_id: str):
        return self.db.collection("teams").document(team_id).collection("members")

    def _team_ratings_ref(self, team_id: str):
        return self.db.collection("teams").document(team_id).collection("ratings")

    def _team_tickets_ref(self, team_id: str):
        return self.db.collection("teams").document(team_id).collection("tickets")

    def _team_consents_ref(self, team_id: str):
        return self.db.collection("teams").document(team_id).collection("reveal_consents")

    def _team_files_ref(self, team_id: str):
        return self.db.collection("teams").document(team_id).collection("shared_files")

    def _team_audit_ref(self, team_id: str):
        return self.db.collection("teams").document(team_id).collection("audit_log")

    def _algolia_sync_commit(self, commit: Record) -> None:
        """Sync a research commit to Algolia for full-text search."""
        if not self._algolia:
            return
        try:
            obj = {
                "objectID": commit["id"],
                "user_id": commit.get("user_id", ""),
                "pseudonym": commit.get("pseudonym", ""),
                "domain": commit.get("domain", ""),
                "subdomain": commit.get("subdomain", ""),
                "problem": commit.get("problem", ""),
                "hypothesis": commit.get("hypothesis", ""),
                "overall_solidity": commit.get("overall_solidity", ""),
                "ot_score": commit.get("ot_score", 0),
                "ofc_score": commit.get("ofc_score", 0),
                "created_at_timestamp": commit.get("created_at", ""),
            }
            self._algolia.save_object(self._algolia_index, obj)
        except Exception as e:
            logger.error("Algolia sync failed for commit %s: %s", commit.get("id"), e)

    # =================================================================
    # USERS
    # =================================================================

    async def find_user_by_email_hash(self, email_hash: str) -> Optional[Record]:
        docs = list(
            self._users_ref()
            .where(filter=FieldFilter("email_hash", "==", email_hash))
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def insert_user(self, user_id: str, pseudonym: str, email_hash: str) -> None:
        self._users_ref().document(user_id).set({
            "pseudonym": pseudonym,
            "email_hash": email_hash,
            "created_at": _now_iso(),
            "reputation_score": 100.0,
            "total_ratings_received": 0,
            "avg_honesty": 0.0,
            "avg_quality": 0.0,
            "avg_effort": 0.0,
            "running_honesty": None,
            "running_quality": None,
            "running_effort": None,
        })

    async def get_most_recent_user(self) -> Optional[Record]:
        docs = list(
            self._users_ref()
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def get_user_by_id(self, user_id: str) -> Optional[Record]:
        doc = self._users_ref().document(user_id).get()
        return _doc_to_record(doc) if doc.exists else None

    async def get_user_pseudonym(self, user_id: str) -> Optional[str]:
        doc = self._users_ref().document(user_id).get(field_paths=["pseudonym"])
        if doc.exists:
            data = doc.to_dict()
            return data.get("pseudonym") if data else None
        return None

    async def get_user_running_averages(self, user_id: str) -> Optional[Record]:
        doc = self._users_ref().document(user_id).get(
            field_paths=["running_honesty", "running_quality", "running_effort", "total_ratings_received"]
        )
        if doc.exists:
            data = doc.to_dict()
            if data:
                data["id"] = doc.id
            return data or None
        return None

    async def get_user_running_effort(self, user_id: str) -> Optional[float]:
        doc = self._users_ref().document(user_id).get(field_paths=["running_effort"])
        if doc.exists:
            data = doc.to_dict()
            return data.get("running_effort") if data else None
        return None

    async def update_user_running_averages(
        self, user_id: str, running_honesty: float,
        running_quality: float, running_effort: float
    ) -> None:
        self._users_ref().document(user_id).update({
            "running_honesty": running_honesty,
            "running_quality": running_quality,
            "running_effort": running_effort,
        })

    async def update_user_running_effort(self, user_id: str, running_effort: float) -> None:
        self._users_ref().document(user_id).update({"running_effort": running_effort})

    async def update_user_reputation_stats(
        self, user_id: str, reputation_score: float,
        total_ratings_received: int, avg_honesty: float,
        avg_quality: float, avg_effort: float
    ) -> None:
        self._users_ref().document(user_id).update({
            "reputation_score": reputation_score,
            "total_ratings_received": total_ratings_received,
            "avg_honesty": avg_honesty,
            "avg_quality": avg_quality,
            "avg_effort": avg_effort,
        })

    async def penalize_user_honesty(
        self, user_id: str, running_honesty: float, avg_honesty: float
    ) -> None:
        self._users_ref().document(user_id).update({
            "running_honesty": running_honesty,
            "avg_honesty": avg_honesty,
        })

    async def count_users(self) -> int:
        return len(list(self._users_ref().select([]).stream()))

    # =================================================================
    # RESEARCH COMMITS
    # =================================================================

    async def get_corpus_commits(
        self, domain: str, exclude_user_id: str, subdomain: Optional[str] = None
    ) -> list[Record]:
        query = self._commits_ref().where(filter=FieldFilter("domain", "==", domain))
        if subdomain:
            query = query.where(filter=FieldFilter("subdomain", "==", subdomain))
        docs = list(query.stream())
        return [_doc_to_record(d) for d in docs if d.to_dict().get("user_id") != exclude_user_id]

    async def get_latest_commit_by_user(self, user_id: str) -> Optional[Record]:
        docs = list(
            self._commits_ref()
            .where(filter=FieldFilter("user_id", "==", user_id))
            .order_by("version", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def get_latest_commit_id_by_user(self, user_id: str) -> Optional[str]:
        commit = await self.get_latest_commit_by_user(user_id)
        return commit["id"] if commit else None

    async def get_latest_scores_by_user(self, user_id: str) -> Optional[Record]:
        commit = await self.get_latest_commit_by_user(user_id)
        if commit:
            return {"ot_score": commit.get("ot_score"), "ofc_score": commit.get("ofc_score")}
        return None

    async def get_all_commits_by_user(self, user_id: str) -> list[Record]:
        docs = list(
            self._commits_ref()
            .where(filter=FieldFilter("user_id", "==", user_id))
            .order_by("version", direction=firestore.Query.DESCENDING)
            .stream()
        )
        return [_doc_to_record(d) for d in docs]

    async def get_commit_by_id(self, commit_id: str) -> Optional[Record]:
        doc = self._commits_ref().document(commit_id).get()
        return _doc_to_record(doc) if doc.exists else None

    async def get_max_commit_version(self, user_id: str) -> int:
        docs = list(
            self._commits_ref()
            .where(filter=FieldFilter("user_id", "==", user_id))
            .order_by("version", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        if docs:
            data = docs[0].to_dict()
            return data.get("version", 0) if data else 0
        return 0

    async def insert_commit(self, commit: Record) -> None:
        commit_id = commit.pop("id", None) or commit.get("id")
        if "created_at" not in commit:
            commit["created_at"] = _now_iso()
        self._commits_ref().document(commit_id).set(commit)

    async def find_candidate_commits_in_domain(
        self, exclude_user_id: str, domain: str
    ) -> list[Record]:
        # Get latest commits (is_latest=true) in domain, excluding current user
        docs = list(
            self._commits_ref()
            .where(filter=FieldFilter("domain", "==", domain))
            .where(filter=FieldFilter("is_latest", "==", True))
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            if rec.get("user_id") == exclude_user_id:
                continue
            # Join user data
            user_doc = self._users_ref().document(rec["user_id"]).get()
            if user_doc.exists:
                user_data = user_doc.to_dict() or {}
                rec["pseudonym"] = user_data.get("pseudonym", "")
                rec["reputation_score"] = user_data.get("reputation_score", 100.0)
            results.append(rec)
        return results

    async def search_commits_by_keywords(
        self, keywords: list[str], limit: int = 10
    ) -> list[Record]:
        query = " ".join(keywords)

        # Try Algolia first (fast full-text search)
        if self._algolia:
            try:
                resp = self._algolia.search_single_index(
                    self._algolia_index,
                    {"query": query, "hitsPerPage": limit},
                )
                results = []
                for hit in (resp.hits or []):
                    d = hit.to_dict() if hasattr(hit, "to_dict") else hit
                    results.append({
                        "domain": d.get("domain", ""),
                        "subdomain": d.get("subdomain", ""),
                        "problem": d.get("problem", ""),
                        "hypothesis": d.get("hypothesis", ""),
                        "overall_solidity": d.get("overall_solidity", ""),
                        "created_at": d.get("created_at_timestamp", ""),
                        "pseudonym": d.get("pseudonym", ""),
                    })
                return results
            except Exception as e:
                logger.warning("Algolia search failed, falling back to Firestore: %s", e)

        # Fallback: Firestore (limited — no full-text, just domain match)
        results: list[Record] = []
        for kw in keywords:
            docs = list(
                self._commits_ref()
                .where(filter=FieldFilter("domain", "==", kw.lower()))
                .limit(limit)
                .stream()
            )
            for doc in docs:
                rec = _doc_to_record(doc)
                # Join pseudonym
                user_id = rec.get("user_id", "")
                pseudonym = await self.get_user_pseudonym(user_id)
                rec["pseudonym"] = pseudonym or ""
                results.append(rec)
        # Deduplicate by id
        seen = set()
        unique = []
        for r in results:
            rid = r.get("id", "")
            if rid not in seen:
                seen.add(rid)
                unique.append(r)
        return unique[:limit]

    async def count_commits(self) -> int:
        return len(list(self._commits_ref().select([]).stream()))

    # =================================================================
    # MATCHES
    # =================================================================

    async def upsert_match(self, match: Record) -> None:
        match_id = match.get("id", "")
        data = {k: v for k, v in match.items() if k != "id"}
        if "created_at" not in data:
            data["created_at"] = _now_iso()
        self._matches_ref().document(match_id).set(data, merge=True)

    async def find_match_between_users(self, user_a_id: str, user_b_id: str) -> Optional[Record]:
        # Check both directions
        for a, b in [(user_a_id, user_b_id), (user_b_id, user_a_id)]:
            docs = list(
                self._matches_ref()
                .where(filter=FieldFilter("user_a_id", "==", a))
                .where(filter=FieldFilter("user_b_id", "==", b))
                .order_by("created_at", direction=firestore.Query.DESCENDING)
                .limit(1)
                .stream()
            )
            if docs:
                return _doc_to_record(docs[0])
        return None

    async def count_matches(self) -> int:
        return len(list(self._matches_ref().select([]).stream()))

    # =================================================================
    # COLLABORATION REQUESTS
    # =================================================================

    async def find_pending_request(
        self, requester_id: str, recipient_id: str
    ) -> Optional[Record]:
        docs = list(
            self._requests_ref()
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .where(filter=FieldFilter("recipient_id", "==", recipient_id))
            .where(filter=FieldFilter("status", "==", "pending"))
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def insert_collaboration_request(
        self, request_id: str, match_id: str,
        requester_id: str, recipient_id: str, message: str
    ) -> None:
        self._requests_ref().document(request_id).set({
            "match_id": match_id,
            "requester_id": requester_id,
            "recipient_id": recipient_id,
            "message": message,
            "status": "pending",
            "created_at": _now_iso(),
            "responded_at": None,
        })

    async def get_incoming_requests(self, recipient_id: str) -> list[Record]:
        docs = list(
            self._requests_ref()
            .where(filter=FieldFilter("recipient_id", "==", recipient_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            # Join match data
            match_doc = self._matches_ref().document(rec.get("match_id", "")).get()
            if match_doc.exists:
                match_data = match_doc.to_dict() or {}
                rec.update({
                    "semaphore": match_data.get("semaphore", ""),
                    "complementarity_score": match_data.get("complementarity_score", 0),
                    "semaphore_reason_a": match_data.get("semaphore_reason_a", ""),
                    "semaphore_reason_b": match_data.get("semaphore_reason_b", ""),
                    "a_gains_from_b": match_data.get("a_gains_from_b", 0),
                    "b_gains_from_a": match_data.get("b_gains_from_a", 0),
                })
            # Join requester pseudonym
            requester_ps = await self.get_user_pseudonym(rec.get("requester_id", ""))
            rec["requester_pseudonym"] = requester_ps or ""
            results.append(rec)
        return results

    async def get_outgoing_requests(self, requester_id: str) -> list[Record]:
        docs = list(
            self._requests_ref()
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            # Join match data
            match_doc = self._matches_ref().document(rec.get("match_id", "")).get()
            if match_doc.exists:
                match_data = match_doc.to_dict() or {}
                rec.update({
                    "semaphore": match_data.get("semaphore", ""),
                    "complementarity_score": match_data.get("complementarity_score", 0),
                    "semaphore_reason_a": match_data.get("semaphore_reason_a", ""),
                    "semaphore_reason_b": match_data.get("semaphore_reason_b", ""),
                    "a_gains_from_b": match_data.get("a_gains_from_b", 0),
                    "b_gains_from_a": match_data.get("b_gains_from_a", 0),
                })
            # Join recipient pseudonym
            recipient_ps = await self.get_user_pseudonym(rec.get("recipient_id", ""))
            rec["recipient_pseudonym"] = recipient_ps or ""
            results.append(rec)
        return results

    async def get_request_for_recipient(
        self, request_id: str, recipient_id: str
    ) -> Optional[Record]:
        doc = self._requests_ref().document(request_id).get()
        if doc.exists:
            rec = _doc_to_record(doc)
            if rec.get("recipient_id") == recipient_id:
                return rec
        return None

    async def update_request_status(
        self, request_id: str, status: str, responded_at: Optional[str] = None
    ) -> None:
        self._requests_ref().document(request_id).update({
            "status": status,
            "responded_at": responded_at or _now_iso(),
        })

    async def count_pending_requests(self) -> int:
        docs = list(
            self._requests_ref()
            .where(filter=FieldFilter("status", "==", "pending"))
            .select([])
            .stream()
        )
        return len(docs)

    # =================================================================
    # TEAMS
    # =================================================================

    async def get_team_by_id(self, team_id: str) -> Optional[Record]:
        doc = self._teams_ref().document(team_id).get()
        return _doc_to_record(doc) if doc.exists else None

    async def get_team_name(self, team_id: str) -> Optional[str]:
        doc = self._teams_ref().document(team_id).get(field_paths=["name"])
        if doc.exists:
            data = doc.to_dict()
            return data.get("name") if data else None
        return None

    async def get_team_created_at(self, team_id: str) -> Optional[str]:
        doc = self._teams_ref().document(team_id).get(field_paths=["created_at"])
        if doc.exists:
            data = doc.to_dict()
            return data.get("created_at") if data else None
        return None

    async def get_team_license_type(self, team_id: str) -> Optional[str]:
        doc = self._teams_ref().document(team_id).get(field_paths=["license_type"])
        if doc.exists:
            data = doc.to_dict()
            return data.get("license_type") if data else None
        return None

    async def get_team_license_info(self, team_id: str) -> Optional[Record]:
        doc = self._teams_ref().document(team_id).get(
            field_paths=["license_type", "license_updated_at"]
        )
        if doc.exists:
            data = doc.to_dict()
            if data:
                data["id"] = doc.id
            return data or None
        return None

    async def get_teams_by_user(self, user_id: str) -> list[Record]:
        # Query all teams, then filter by membership
        # (Firestore can't join — we query membership first)
        results = []
        # Get all teams where this user is a member
        # We need to query across all team subcollections — use collection group
        member_docs = list(
            self.db.collection_group("members")
            .where(filter=FieldFilter("user_id", "==", user_id))
            .stream()
        )
        for mdoc in member_docs:
            # mdoc.reference.parent.parent is the team document ref
            team_ref = mdoc.reference.parent.parent
            if team_ref:
                team_doc = team_ref.get()
                if team_doc.exists:
                    results.append(_doc_to_record(team_doc))
        return results

    async def insert_team(self, team_id: str, name: str, license_type: str = "joint-equal") -> None:
        self._teams_ref().document(team_id).set({
            "name": name,
            "license_type": license_type,
            "created_at": _now_iso(),
            "repository_url": None,
            "license_updated_at": None,
        })

    async def update_team_license(
        self, team_id: str, license_type: str, updated_at: Optional[str] = None
    ) -> None:
        self._teams_ref().document(team_id).update({
            "license_type": license_type,
            "license_updated_at": updated_at or _now_iso(),
        })

    async def count_teams(self) -> int:
        return len(list(self._teams_ref().select([]).stream()))

    # =================================================================
    # TEAM MEMBERS (subcollection: teams/{team_id}/members)
    # =================================================================

    async def get_team_membership(self, team_id: str, user_id: str) -> Optional[Record]:
        doc = self._team_members_ref(team_id).document(user_id).get()
        if doc.exists:
            data = doc.to_dict() or {}
            data["team_id"] = team_id
            data["user_id"] = user_id
            return data
        return None

    async def get_team_member_ids(self, team_id: str) -> list[str]:
        docs = list(self._team_members_ref(team_id).select(["user_id"]).stream())
        return [d.id for d in docs]

    async def get_team_member_pseudonyms(self, team_id: str) -> list[Record]:
        member_docs = list(self._team_members_ref(team_id).stream())
        results = []
        for mdoc in member_docs:
            user_id = mdoc.id
            pseudonym = await self.get_user_pseudonym(user_id)
            results.append({"user_id": user_id, "pseudonym": pseudonym or ""})
        return results

    async def get_team_members_with_profiles(self, team_id: str) -> list[Record]:
        member_docs = list(self._team_members_ref(team_id).stream())
        results = []
        for mdoc in member_docs:
            data = mdoc.to_dict() or {}
            user_id = mdoc.id
            data["user_id"] = user_id
            data["team_id"] = team_id
            # Join user profile
            user_doc = self._users_ref().document(user_id).get()
            if user_doc.exists:
                user_data = user_doc.to_dict() or {}
                data["pseudonym"] = user_data.get("pseudonym", "")
                data["reputation_score"] = user_data.get("reputation_score", 100.0)
            results.append(data)
        return results

    async def insert_team_member(
        self, team_id: str, user_id: str, role: str = "co-lead"
    ) -> None:
        self._team_members_ref(team_id).document(user_id).set({
            "user_id": user_id,
            "role": role,
            "contribution_percentage": None,
            "joined_at": _now_iso(),
        })

    async def update_member_contribution(
        self, team_id: str, user_id: str, contribution_percentage: float
    ) -> None:
        self._team_members_ref(team_id).document(user_id).update({
            "contribution_percentage": contribution_percentage,
        })

    async def count_team_members(self, team_id: str) -> int:
        return len(list(self._team_members_ref(team_id).select([]).stream()))

    # =================================================================
    # RATINGS (subcollection: teams/{team_id}/ratings)
    # =================================================================

    def _rating_doc_id(self, rater_id: str, rated_id: str) -> str:
        """Deterministic ID for rating documents: rater_rated."""
        return f"{rater_id}_{rated_id}"

    async def find_rating(
        self, team_id: str, rater_id: str, rated_id: str
    ) -> Optional[Record]:
        doc_id = self._rating_doc_id(rater_id, rated_id)
        doc = self._team_ratings_ref(team_id).document(doc_id).get()
        if doc.exists:
            data = _doc_to_record(doc)
            data["team_id"] = team_id
            return data
        return None

    async def get_rating(
        self, team_id: str, rater_id: str, rated_id: str
    ) -> Optional[Record]:
        return await self.find_rating(team_id, rater_id, rated_id)

    async def get_ratings_received_desc(self, rated_id: str) -> list[Record]:
        # Collection group query across all team rating subcollections
        docs = list(
            self.db.collection_group("ratings")
            .where(filter=FieldFilter("rated_id", "==", rated_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        return [_doc_to_record(d) for d in docs]

    async def get_ratings_given_desc(self, rater_id: str) -> list[Record]:
        docs = list(
            self.db.collection_group("ratings")
            .where(filter=FieldFilter("rater_id", "==", rater_id))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        return [_doc_to_record(d) for d in docs]

    async def count_ratings_received(self, rated_id: str) -> int:
        docs = list(
            self.db.collection_group("ratings")
            .where(filter=FieldFilter("rated_id", "==", rated_id))
            .select([])
            .stream()
        )
        return len(docs)

    async def insert_rating(self, rating: Record) -> None:
        team_id = rating["team_id"]
        rater_id = rating["rater_id"]
        rated_id = rating["rated_id"]
        doc_id = rating.get("id") or self._rating_doc_id(rater_id, rated_id)
        data = {k: v for k, v in rating.items() if k != "id"}
        if "created_at" not in data:
            data["created_at"] = _now_iso()
        data["is_revealed"] = 0
        self._team_ratings_ref(team_id).document(doc_id).set(data)

    async def reveal_team_ratings(self, team_id: str) -> None:
        docs = list(self._team_ratings_ref(team_id).stream())
        batch = self.db.batch()
        for doc in docs:
            batch.update(doc.reference, {"is_revealed": 1})
        batch.commit()

    async def count_ratings(self) -> int:
        docs = list(
            self.db.collection_group("ratings").select([]).stream()
        )
        return len(docs)

    # =================================================================
    # TEAM TICKETS (subcollection: teams/{team_id}/tickets)
    # =================================================================

    async def get_ticket_by_id(self, ticket_id: str) -> Optional[Record]:
        # We need the team_id to query subcollection, use collection group
        docs = list(
            self.db.collection_group("tickets")
            .where(filter=FieldFilter("ticket_id", "==", ticket_id))
            .limit(1)
            .stream()
        )
        if docs:
            rec = _doc_to_record(docs[0])
            # Extract team_id from path
            team_ref = docs[0].reference.parent.parent
            rec["team_id"] = team_ref.id if team_ref else ""
            return rec
        # Fallback: direct lookup if ticket_id == doc id
        return None

    async def count_open_tickets_by_author(self, team_id: str, author_id: str) -> int:
        count = 0
        for status in ("open", "in_progress"):
            docs = list(
                self._team_tickets_ref(team_id)
                .where(filter=FieldFilter("author_id", "==", author_id))
                .where(filter=FieldFilter("status", "==", status))
                .select([])
                .stream()
            )
            count += len(docs)
        return count

    async def count_resolved_tickets_by_member(self, team_id: str, resolved_by: str) -> int:
        docs = list(
            self._team_tickets_ref(team_id)
            .where(filter=FieldFilter("resolved_by", "==", resolved_by))
            .where(filter=FieldFilter("status", "==", "resolved"))
            .select([])
            .stream()
        )
        return len(docs)

    async def get_ticket_status_summary(self, team_id: str) -> list[Record]:
        docs = list(self._team_tickets_ref(team_id).select(["status"]).stream())
        counts: dict[str, int] = {}
        for doc in docs:
            data = doc.to_dict() or {}
            s = data.get("status", "open")
            counts[s] = counts.get(s, 0) + 1
        return [{"status": k, "c": v} for k, v in counts.items()]

    async def list_tickets_with_filters(
        self, team_id: str,
        status: Optional[str] = None,
        area: Optional[str] = None,
        ticket_type: Optional[str] = None
    ) -> list[Record]:
        query = self._team_tickets_ref(team_id)
        if status:
            query = query.where(filter=FieldFilter("status", "==", status))
        if area:
            query = query.where(filter=FieldFilter("area", "==", area))
        if ticket_type:
            query = query.where(filter=FieldFilter("type", "==", ticket_type))
        docs = list(query.stream())
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            rec["team_id"] = team_id
            # Join author pseudonym
            author_ps = await self.get_user_pseudonym(rec.get("author_id", ""))
            rec["author_pseudonym"] = author_ps or ""
            results.append(rec)
        # Sort by priority then created_at desc
        priority_order = {"critical": 0, "important": 1, "nice_to_have": 2}
        results.sort(key=lambda x: (
            priority_order.get(x.get("priority", "important"), 1),
            x.get("created_at", ""),
        ))
        return results

    async def insert_ticket(self, ticket: Record) -> None:
        team_id = ticket["team_id"]
        ticket_id = ticket["id"]
        data = {k: v for k, v in ticket.items() if k not in ("id",)}
        data["ticket_id"] = ticket_id  # Store id in document for collection group queries
        if "created_at" not in data:
            data["created_at"] = _now_iso()
        if "updated_at" not in data:
            data["updated_at"] = _now_iso()
        data["status"] = data.get("status", "open")
        self._team_tickets_ref(team_id).document(ticket_id).set(data)

    async def resolve_ticket(
        self, ticket_id: str, resolved_by: str, status: str = "resolved"
    ) -> None:
        # Find ticket via collection group
        docs = list(
            self.db.collection_group("tickets")
            .where(filter=FieldFilter("ticket_id", "==", ticket_id))
            .limit(1)
            .stream()
        )
        if docs:
            docs[0].reference.update({
                "status": status,
                "resolved_by": resolved_by,
                "resolved_at": _now_iso(),
                "updated_at": _now_iso(),
            })

    async def count_tickets(self) -> int:
        return len(list(self.db.collection_group("tickets").select([]).stream()))

    # =================================================================
    # REVEAL CONSENTS (subcollection: teams/{team_id}/reveal_consents)
    # =================================================================

    async def find_pending_reveal(
        self, team_id: str, requester_id: str, resource_ref: str
    ) -> Optional[Record]:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .where(filter=FieldFilter("resource_ref", "==", resource_ref))
            .where(filter=FieldFilter("status", "==", "pending"))
            .where(filter=FieldFilter("level", "==", 3))
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def find_approved_reveal(
        self, team_id: str, requester_id: str, resource_ref: str
    ) -> Optional[Record]:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .where(filter=FieldFilter("resource_ref", "==", resource_ref))
            .where(filter=FieldFilter("status", "==", "approved"))
            .where(filter=FieldFilter("level", "==", 3))
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def find_approved_reveal_for_pair(
        self, team_id: str, requester_id: str, approver_id: str
    ) -> Optional[Record]:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .where(filter=FieldFilter("approver_id", "==", approver_id))
            .where(filter=FieldFilter("status", "==", "approved"))
            .where(filter=FieldFilter("level", "==", 3))
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def count_pending_reveals(self, team_id: str) -> int:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("status", "==", "pending"))
            .select([])
            .stream()
        )
        return len(docs)

    async def count_approved_reveals_direction(
        self, team_id: str, approver_id: str, requester_id: str
    ) -> int:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("level", "==", 3))
            .where(filter=FieldFilter("status", "==", "approved"))
            .where(filter=FieldFilter("approver_id", "==", approver_id))
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .select([])
            .stream()
        )
        return len(docs)

    async def get_reveal_consent_by_id(self, consent_id: str) -> Optional[Record]:
        # Use collection group to find by document ID
        docs = list(
            self.db.collection_group("reveal_consents")
            .where(filter=FieldFilter("consent_id", "==", consent_id))
            .limit(1)
            .stream()
        )
        if docs:
            rec = _doc_to_record(docs[0])
            team_ref = docs[0].reference.parent.parent
            rec["team_id"] = team_ref.id if team_ref else ""
            return rec
        return None

    async def get_team_consents_with_pseudonyms(self, team_id: str) -> list[Record]:
        docs = list(
            self._team_consents_ref(team_id)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            rec["team_id"] = team_id
            req_ps = await self.get_user_pseudonym(rec.get("requester_id", ""))
            app_ps = await self.get_user_pseudonym(rec.get("approver_id", ""))
            rec["requester_pseudonym"] = req_ps or ""
            rec["approver_pseudonym"] = app_ps or ""
            results.append(rec)
        return results

    async def get_reveal_visible_to(self, team_id: str, approver_id: str) -> list[str]:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("approver_id", "==", approver_id))
            .where(filter=FieldFilter("status", "==", "approved"))
            .where(filter=FieldFilter("level", "==", 3))
            .stream()
        )
        pseudonyms = []
        for doc in docs:
            data = doc.to_dict() or {}
            ps = await self.get_user_pseudonym(data.get("requester_id", ""))
            if ps:
                pseudonyms.append(ps)
        return pseudonyms

    async def get_reveal_can_see(self, team_id: str, requester_id: str) -> list[str]:
        docs = list(
            self._team_consents_ref(team_id)
            .where(filter=FieldFilter("requester_id", "==", requester_id))
            .where(filter=FieldFilter("status", "==", "approved"))
            .where(filter=FieldFilter("level", "==", 3))
            .stream()
        )
        pseudonyms = []
        for doc in docs:
            data = doc.to_dict() or {}
            ps = await self.get_user_pseudonym(data.get("approver_id", ""))
            if ps:
                pseudonyms.append(ps)
        return pseudonyms

    async def insert_reveal_consent(self, consent: Record) -> None:
        team_id = consent["team_id"]
        consent_id = consent["id"]
        data = {k: v for k, v in consent.items() if k not in ("id",)}
        data["consent_id"] = consent_id  # Store for collection group lookups
        if "created_at" not in data:
            data["created_at"] = _now_iso()
        data["status"] = data.get("status", "pending")
        data["resolved_at"] = None
        self._team_consents_ref(team_id).document(consent_id).set(data)

    async def update_reveal_consent_status(
        self, consent_id: str, status: str,
        team_id: Optional[str] = None, resolved_at: Optional[str] = None
    ) -> None:
        # If team_id provided, go direct; otherwise use collection group
        if team_id:
            doc_ref = self._team_consents_ref(team_id).document(consent_id)
            doc_ref.update({
                "status": status,
                "resolved_at": resolved_at or _now_iso(),
            })
        else:
            docs = list(
                self.db.collection_group("reveal_consents")
                .where(filter=FieldFilter("consent_id", "==", consent_id))
                .limit(1)
                .stream()
            )
            if docs:
                docs[0].reference.update({
                    "status": status,
                    "resolved_at": resolved_at or _now_iso(),
                })

    # =================================================================
    # SHARED FILES (subcollection: teams/{team_id}/shared_files)
    # =================================================================

    async def find_file_by_hash_other_user(
        self, file_hash: str, user_id: str
    ) -> Optional[Record]:
        docs = list(
            self.db.collection_group("shared_files")
            .where(filter=FieldFilter("file_hash", "==", file_hash))
            .limit(5)
            .stream()
        )
        for doc in docs:
            rec = _doc_to_record(doc)
            if rec.get("origin_user_id") != user_id:
                team_ref = doc.reference.parent.parent
                rec["team_id"] = team_ref.id if team_ref else ""
                return rec
        return None

    async def find_shared_file_by_path(
        self, team_id: str, shared_by: str, file_path: str
    ) -> Optional[Record]:
        docs = list(
            self._team_files_ref(team_id)
            .where(filter=FieldFilter("shared_by", "==", shared_by))
            .where(filter=FieldFilter("file_path", "==", file_path))
            .limit(1)
            .stream()
        )
        return _doc_to_record(docs[0]) if docs else None

    async def count_shared_files_in_team(self, team_id: str) -> int:
        return len(list(self._team_files_ref(team_id).select([]).stream()))

    async def list_shared_files_with_pseudonyms(self, team_id: str) -> list[Record]:
        docs = list(
            self._team_files_ref(team_id)
            .order_by("shared_at", direction=firestore.Query.DESCENDING)
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            rec["team_id"] = team_id
            ps = await self.get_user_pseudonym(rec.get("shared_by", ""))
            rec["shared_by_pseudonym"] = ps or ""
            results.append(rec)
        return results

    async def insert_shared_file(self, file_record: Record) -> None:
        team_id = file_record["team_id"]
        file_id = file_record["id"]
        data = {k: v for k, v in file_record.items() if k not in ("id",)}
        if "shared_at" not in data:
            data["shared_at"] = _now_iso()
        self._team_files_ref(team_id).document(file_id).set(data)

    async def count_shared_files(self, team_id: Optional[str] = None) -> int:
        if team_id:
            return await self.count_shared_files_in_team(team_id)
        return len(list(self.db.collection_group("shared_files").select([]).stream()))

    # =================================================================
    # AUDIT LOG (subcollection: teams/{team_id}/audit_log)
    # =================================================================

    async def insert_audit_entry(
        self, entry_id: str, team_id: str, actor_id: str,
        action: str, resource_ref: Optional[str], details: Optional[str]
    ) -> None:
        self._team_audit_ref(team_id).document(entry_id).set({
            "team_id": team_id,
            "actor_id": actor_id,
            "action": action,
            "resource_ref": resource_ref,
            "details": details,
            "created_at": _now_iso(),
        })

    async def get_license_change_history(
        self, team_id: str, limit: int = 10
    ) -> list[Record]:
        docs = list(
            self._team_audit_ref(team_id)
            .where(filter=FieldFilter("action", "==", "license_generated"))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        return [
            {"details": (d.to_dict() or {}).get("details"), "created_at": (d.to_dict() or {}).get("created_at")}
            for d in docs
        ]

    async def list_audit_entries(
        self, team_id: str, limit: int = 100
    ) -> list[Record]:
        docs = list(
            self._team_audit_ref(team_id)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            rec["team_id"] = team_id
            ps = await self.get_user_pseudonym(rec.get("actor_id", ""))
            rec["actor_pseudonym"] = ps or ""
            results.append(rec)
        return results

    async def list_audit_entries_filtered(
        self, team_id: str, action: str, limit: int = 100
    ) -> list[Record]:
        docs = list(
            self._team_audit_ref(team_id)
            .where(filter=FieldFilter("action", "==", action))
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .stream()
        )
        results = []
        for doc in docs:
            rec = _doc_to_record(doc)
            rec["team_id"] = team_id
            ps = await self.get_user_pseudonym(rec.get("actor_id", ""))
            rec["actor_pseudonym"] = ps or ""
            results.append(rec)
        return results

    async def count_audit_entries(self) -> int:
        return len(list(self.db.collection_group("audit_log").select([]).stream()))

    # =================================================================
    # COLLABORATION CONTRACTS
    # =================================================================

    async def get_max_contract_version(self, team_id: str) -> int:
        docs = list(
            self._contracts_ref()
            .where(filter=FieldFilter("team_id", "==", team_id))
            .order_by("contract_version", direction=firestore.Query.DESCENDING)
            .limit(1)
            .stream()
        )
        if docs:
            data = docs[0].to_dict()
            return data.get("contract_version", 0) if data else 0
        return 0

    async def get_contract_by_id(self, contract_id: str) -> Optional[Record]:
        doc = self._contracts_ref().document(contract_id).get()
        return _doc_to_record(doc) if doc.exists else None

    async def get_contract_by_id_and_team(
        self, contract_id: str, team_id: str
    ) -> Optional[Record]:
        doc = self._contracts_ref().document(contract_id).get()
        if doc.exists:
            rec = _doc_to_record(doc)
            if rec.get("team_id") == team_id:
                return rec
        return None

    async def count_confirmed_contracts(self) -> int:
        docs = list(
            self._contracts_ref()
            .where(filter=FieldFilter("status", "==", "confirmed"))
            .select([])
            .stream()
        )
        return len(docs)

    async def count_confirmed_contracts_for_team(self, team_id: str) -> int:
        docs = list(
            self._contracts_ref()
            .where(filter=FieldFilter("team_id", "==", team_id))
            .where(filter=FieldFilter("status", "==", "confirmed"))
            .select([])
            .stream()
        )
        return len(docs)

    async def supersede_pending_contracts(self, team_id: str) -> None:
        for status in ("pending", "partial"):
            docs = list(
                self._contracts_ref()
                .where(filter=FieldFilter("team_id", "==", team_id))
                .where(filter=FieldFilter("status", "==", status))
                .stream()
            )
            batch = self.db.batch()
            for doc in docs:
                batch.update(doc.reference, {"status": "superseded"})
            batch.commit()

    async def insert_contract(self, contract: Record) -> None:
        contract_id = contract.get("id", "")
        data = {k: v for k, v in contract.items() if k != "id"}
        if "generated_at" not in data:
            data["generated_at"] = _now_iso()
        self._contracts_ref().document(contract_id).set(data)

    async def update_contract_confirmation_a(
        self, contract_id: str, user_id: str,
        git_hash: str, repo_url: str, confirmed_at: str
    ) -> None:
        self._contracts_ref().document(contract_id).update({
            "confirmation_a_user_id": user_id,
            "confirmation_a_git_hash": git_hash,
            "confirmation_a_repo_url": repo_url,
            "confirmation_a_at": confirmed_at,
        })

    async def update_contract_confirmation_b(
        self, contract_id: str, user_id: str,
        git_hash: str, repo_url: str, confirmed_at: str
    ) -> None:
        self._contracts_ref().document(contract_id).update({
            "confirmation_b_user_id": user_id,
            "confirmation_b_git_hash": git_hash,
            "confirmation_b_repo_url": repo_url,
            "confirmation_b_at": confirmed_at,
        })

    async def update_contract_status(self, contract_id: str, status: str) -> None:
        self._contracts_ref().document(contract_id).update({"status": status})

    # =================================================================
    # GITHUB CONNECTIONS (embedded in users/{user_id}.github_connection)
    # =================================================================

    async def get_github_connection(self, user_id: str) -> Optional[Record]:
        doc = self._users_ref().document(user_id).get(
            field_paths=["github_connection"]
        )
        if doc.exists:
            data = doc.to_dict()
            if data and data.get("github_connection"):
                conn = dict(data["github_connection"])
                conn["user_id"] = user_id
                return conn
        return None

    async def upsert_github_connection(
        self, user_id: str, github_username: str,
        installation_id: int, authorized_repos: list[str]
    ) -> None:
        self._users_ref().document(user_id).update({
            "github_connection": {
                "github_username": github_username,
                "installation_id": installation_id,
                "authorized_repos": authorized_repos,
                "connected_at": _now_iso(),
            }
        })

    async def delete_github_connection(self, user_id: str) -> None:
        self._users_ref().document(user_id).update({
            "github_connection": None,
        })

    async def get_github_connections_for_team(self, team_id: str) -> list[Record]:
        member_ids = await self.get_team_member_ids(team_id)
        results = []
        for uid in member_ids:
            conn = await self.get_github_connection(uid)
            if conn:
                results.append(conn)
        return results

    async def update_github_authorized_repos(
        self, user_id: str, authorized_repos: list[str]
    ) -> None:
        self._users_ref().document(user_id).update({
            "github_connection.authorized_repos": authorized_repos,
        })

    # =================================================================
    # UTILITY
    # =================================================================

    async def compute_age_in_days(self, iso_timestamp: str) -> float:
        """Compute age in fractional days from ISO timestamp to now."""
        try:
            # Handle both ISO formats
            ts = iso_timestamp.replace("Z", "+00:00")
            if "T" in ts:
                dt = datetime.fromisoformat(ts)
            else:
                dt = datetime.fromisoformat(ts + "T00:00:00+00:00")
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            return delta.total_seconds() / 86400.0
        except (ValueError, TypeError):
            return 0.0

    # =================================================================
    # HEALTH / STATS
    # =================================================================

    async def health_stats(self) -> Record:
        return {
            "users": await self.count_users(),
            "commits": await self.count_commits(),
            "matches": await self.count_matches(),
            "teams": await self.count_teams(),
            "pending_requests": await self.count_pending_requests(),
            "ratings": await self.count_ratings(),
            "tickets": await self.count_tickets(),
            "audit_entries": await self.count_audit_entries(),
            "shared_files": await self.count_shared_files(),
            "confirmed_contracts": await self.count_confirmed_contracts(),
        }

    # =================================================================
    # BATCH OPERATIONS
    # =================================================================

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
        """Atomic batch: create team + all members.
        Accepts either positional args or dict-based kwargs."""
        # Resolve dict-based kwargs if provided
        if team is not None:
            team_id = team.get("id", team_id)
            team_name = team.get("name", team_name)
            license_type = team.get("license_type", license_type)
            created_at = team.get("created_at", _now_iso())
        else:
            created_at = _now_iso()

        batch = self.db.batch()

        # Team document
        team_ref = self._teams_ref().document(team_id)
        batch.set(team_ref, {
            "name": team_name,
            "license_type": license_type,
            "created_at": created_at,
            "repository_url": None,
            "license_updated_at": None,
        })

        # Member documents — from member dicts or user_id list
        if members is not None:
            for m in members:
                uid = m["user_id"]
                member_ref = self._team_members_ref(team_id).document(uid)
                batch.set(member_ref, {
                    "user_id": uid,
                    "role": m.get("role", role),
                    "contribution_percentage": None,
                    "joined_at": m.get("joined_at", _now_iso()),
                })
        elif member_user_ids:
            for uid in member_user_ids:
                member_ref = self._team_members_ref(team_id).document(uid)
                batch.set(member_ref, {
                    "user_id": uid,
                    "role": role,
                    "contribution_percentage": None,
                    "joined_at": _now_iso(),
                })

        batch.commit()

    async def submit_commit_and_mark_latest(
        self, commit: Record, previous_commit_id: Optional[str] = None
    ) -> None:
        """Atomic batch: insert commit + mark previous as not-latest + Algolia sync."""
        batch = self.db.batch()

        commit_id = commit.get("id", "")
        data = {k: v for k, v in commit.items() if k != "id"}
        data["is_latest"] = True
        if "created_at" not in data:
            data["created_at"] = _now_iso()

        # New commit
        new_ref = self._commits_ref().document(commit_id)
        batch.set(new_ref, data)

        # Mark previous as not-latest
        if previous_commit_id:
            old_ref = self._commits_ref().document(previous_commit_id)
            batch.update(old_ref, {"is_latest": False})

        batch.commit()

        # Algolia sync (outside batch — Firestore batch is Firestore-only)
        sync_data = dict(data)
        sync_data["id"] = commit_id
        # Fetch pseudonym for Algolia
        user_id = data.get("user_id", "")
        ps = await self.get_user_pseudonym(user_id)
        sync_data["pseudonym"] = ps or ""
        self._algolia_sync_commit(sync_data)
