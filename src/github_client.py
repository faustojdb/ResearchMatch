"""
GitHubAppClient — GitHub App integration for Research Match.

Manages bilateral read-only repository access between collaborating researchers
after contract confirmation. Uses GitHub App installation tokens for
fine-grained permissions.

Environment variables:
- GITHUB_APP_ID: GitHub App numeric ID
- GITHUB_APP_PRIVATE_KEY: PEM private key (inline content or path to .pem file)
- GITHUB_APP_SLUG: App slug for installation URL (e.g. 'research-match-collaborator')
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("research_match.github")

try:
    import jwt  # PyJWT
    HAS_JWT = True
except ImportError:
    HAS_JWT = False

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


GITHUB_API_BASE = "https://api.github.com"
JWT_EXPIRY_SECONDS = 600  # 10 minutes (GitHub max)
TOKEN_CACHE_SECONDS = 3300  # 55 minutes (tokens last 60 min)
MAX_REPOS_PER_GRANT = 5  # Safety limit on repos per access grant


class GitHubAppClient:
    """Client for GitHub App operations: JWT auth, installation tokens, collaborator management."""

    def __init__(self) -> None:
        self._app_id = os.environ.get("GITHUB_APP_ID", "")
        self._private_key_raw = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
        self._app_slug = os.environ.get("GITHUB_APP_SLUG", "research-match-collaborator")
        self._private_key: Optional[str] = None
        self._client: Optional[httpx.Client] = None

        # Installation token cache: {installation_id: (token, expires_at)}
        self._token_cache: dict[int, tuple[str, float]] = {}

        if self.is_configured:
            self._private_key = self._load_private_key()
            self._client = httpx.Client(
                base_url=GITHUB_API_BASE,
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
            logger.info("GitHubAppClient initialized (app_id=%s)", self._app_id)
        else:
            logger.info("GitHubAppClient not configured — GitHub integration disabled")

    @property
    def is_configured(self) -> bool:
        """Check if GitHub App credentials are available."""
        return bool(
            HAS_JWT and HAS_HTTPX
            and self._app_id
            and self._private_key_raw
        )

    def _load_private_key(self) -> str:
        """Load PEM private key from env var (inline content or file path)."""
        raw = self._private_key_raw
        if raw.startswith("-----BEGIN"):
            return raw
        # Treat as file path
        if os.path.isfile(raw):
            with open(raw) as f:
                return f.read()
        raise ValueError(
            f"GITHUB_APP_PRIVATE_KEY is neither PEM content nor a valid file path: {raw[:50]}..."
        )

    def _generate_jwt(self) -> str:
        """Generate a JWT for GitHub App authentication (RS256, 10-min expiry)."""
        now = int(time.time())
        payload = {
            "iat": now - 60,  # Allow clock drift
            "exp": now + JWT_EXPIRY_SECONDS,
            "iss": self._app_id,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    def _get_installation_token(self, installation_id: int) -> str:
        """Get an installation access token, using cache when possible."""
        cached = self._token_cache.get(installation_id)
        if cached:
            token, expires_at = cached
            if time.time() < expires_at:
                return token

        app_jwt = self._generate_jwt()
        resp = self._client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}"},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["token"]
        self._token_cache[installation_id] = (token, time.time() + TOKEN_CACHE_SECONDS)
        return token

    def get_installation_url(self) -> str:
        """Return the URL where users install the GitHub App on their repos."""
        return f"https://github.com/apps/{self._app_slug}/installations/new"

    def find_installation_for_user(self, github_username: str) -> Optional[dict[str, Any]]:
        """Find the App installation for a given GitHub username.

        Returns dict with 'id', 'account_login', 'account_type' or None.
        """
        app_jwt = self._generate_jwt()
        page = 1
        while True:
            resp = self._client.get(
                "/app/installations",
                params={"per_page": 100, "page": page},
                headers={"Authorization": f"Bearer {app_jwt}"},
            )
            resp.raise_for_status()
            installations = resp.json()
            if not installations:
                break
            for inst in installations:
                account = inst.get("account", {})
                if account.get("login", "").lower() == github_username.lower():
                    return {
                        "id": inst["id"],
                        "account_login": account["login"],
                        "account_type": account.get("type", "User"),
                    }
            page += 1
        return None

    def get_installation_repos(self, installation_id: int) -> list[dict[str, Any]]:
        """List repositories accessible to an installation.

        Returns list of dicts with 'full_name', 'private', 'permissions'.
        """
        token = self._get_installation_token(installation_id)
        repos = []
        page = 1
        while True:
            resp = self._client.get(
                "/installation/repositories",
                params={"per_page": 100, "page": page},
                headers={"Authorization": f"token {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            for repo in data.get("repositories", []):
                repos.append({
                    "full_name": repo["full_name"],
                    "private": repo["private"],
                    "permissions": repo.get("permissions", {}),
                })
            if len(data.get("repositories", [])) < 100:
                break
            page += 1
        return repos

    def add_collaborator(
        self, installation_id: int, repo_full_name: str,
        username: str, permission: str = "pull"
    ) -> dict[str, Any]:
        """Add a collaborator with specified permission to a repository.

        Args:
            installation_id: GitHub App installation ID for the repo owner.
            repo_full_name: Full repo name (e.g. 'owner/repo').
            username: GitHub username to invite.
            permission: Permission level ('pull', 'push', 'admin'). Default: 'pull'.

        Returns:
            dict with 'status' ('invited' or 'already_collaborator') and 'repo'.
        """
        token = self._get_installation_token(installation_id)
        resp = self._client.put(
            f"/repos/{repo_full_name}/collaborators/{username}",
            json={"permission": permission},
            headers={"Authorization": f"token {token}"},
        )
        if resp.status_code == 201:
            return {"status": "invited", "repo": repo_full_name}
        elif resp.status_code == 204:
            return {"status": "already_collaborator", "repo": repo_full_name}
        else:
            resp.raise_for_status()
            return {"status": "unknown", "repo": repo_full_name}

    def remove_collaborator(
        self, installation_id: int, repo_full_name: str, username: str
    ) -> dict[str, Any]:
        """Remove a collaborator from a repository.

        Returns dict with 'status' ('removed' or 'not_found') and 'repo'.
        """
        token = self._get_installation_token(installation_id)
        resp = self._client.delete(
            f"/repos/{repo_full_name}/collaborators/{username}",
            headers={"Authorization": f"token {token}"},
        )
        if resp.status_code == 204:
            return {"status": "removed", "repo": repo_full_name}
        elif resp.status_code == 404:
            return {"status": "not_found", "repo": repo_full_name}
        else:
            resp.raise_for_status()
            return {"status": "unknown", "repo": repo_full_name}

    def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
        self._token_cache.clear()
