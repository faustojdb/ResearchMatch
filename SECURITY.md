# Security Policy

## Reporting a vulnerability

Email **faustojdb@gmail.com** with details. Please do not open a public issue for
security-sensitive reports until a fix is available.

## Threat model & current posture

Research Match is designed **local-first**: in the default mode all data lives in a
private SQLite database on your machine and nothing is transmitted except optional,
anonymous OpenAlex literature queries (which contain only your search terms, never
your stored research).

The **shared remote backend (Firestore on Cloud Run) is experimental and currently
has no user authentication** — identity is a self-asserted email hash. Do not put
sensitive or unpublished research into the shared backend until token-based auth
(OAuth) is in place. The server:

- fails closed on identity: an unidentified request never resolves to another user's
  account (there is no "most recent user" fallback);
- re-enables DNS-rebinding protection with a Host allow-list on the HTTP transport;
- stores only the SHA-256 hash of emails, never plaintext.

## Secrets — rotation checklist

Real credentials must live **outside** the repository and be loaded from environment
variables or a secrets manager. They are gitignored (`.env`, `*.pem`,
`*credentials*.json`) and have never been committed, but if a machine holding them is
shared or the repo is ever made public, rotate all of them:

- [ ] **Firebase service-account key** (`firebase-credentials.json`) — revoke the key
      in Google Cloud IAM → Service Accounts → Keys, generate a new one.
- [ ] **GitHub App private key** (`*.private-key.pem`) — regenerate in the GitHub App
      settings; the old key stops minting installation tokens.
- [x] ~~Algolia admin API key~~ — the Algolia application (`1TAPVC99Z1`) was deleted by
      Algolia for inactivity (verified 2026-07-17: the app's endpoint no longer resolves
      in DNS, and the dashboard shows only the default "My First Application"). There is
      nothing to rotate. `cold_search` runs on its keyword-matching fallback without it.
      If full-text search is wanted later, create a fresh Algolia app and re-index —
      prefer a **search-only** key for the read path, never the admin key.

Never paste real keys into commits, plans, logs, or issue trackers.

## Pre-commit protection

A hook at `.githooks/pre-commit` blocks staging of `.env`, `*.pem`,
`*credentials*.json`, `*.db`, and `*-debug.log`. Enable it once per clone:

```bash
git config core.hooksPath .githooks
```
