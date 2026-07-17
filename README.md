# Research Match

**MCP server that connects isolated researchers via literature-grounded originality scoring and bilateral matching.**

Research Match helps researchers, scientists, developers, and independent theorists find complementary collaborators while protecting intellectual property. It scores originality on two independent axes — grounding novelty in real published literature (via the free OpenAlex API) using semantic-embedding similarity, combined with a transparent structured self-assessment — and pairs it with bilateral matching via a semaphore system that shows each researcher what they gain from a potential collaboration.

## How It Works

1. **Register** with a pseudonymous identity (email is SHA-256 hashed, never stored in plain text)
2. **Submit a Research Commit** describing your work — originality is scored on two axes:
   - **Theoretical Originality (OT)**: novelty of hypotheses, interdisciplinary connections, ad-hoc content
   - **Formal-Computational Originality (OFC)**: code quality, validation power, technical sophistication
3. **Find Collaborators** — the matching engine identifies researchers with complementary strengths and assigns a bilateral semaphore (GREEN/YELLOW/RED)
4. **Collaborate** — accept requests, reveal work progressively, share files, generate contracts

## Features

- **27 MCP Tools** covering the full research collaboration lifecycle
- **Dual-Axis Originality Scoring** — novelty grounded in real published literature via the free OpenAlex API using semantic-embedding similarity, plus a transparent structured self-assessment with solidity multipliers (proven, functional, speculative, adhoc). Runs locally with no API key and no LLM; when offline it degrades to a neutral "unscored" state rather than fabricating a number.
- **Bilateral Matching** with perspective-aware reasoning — each side sees gains from their viewpoint
- **Privacy by Design** — pseudonymous identities, SHA-256 hashed emails, progressive disclosure
- **Reputation System** — anti-retaliation ratings, exponential smoothing, honesty-weighted
- **Collaboration Tickets** — structured need_help/question/bug/suggestion system
- **Bilateral Reveal System** — consent-based progressive disclosure of research content
- **Automatic Licensing** — 5-rule system (joint-equal, advisory-only, joint-weighted, time-limited)
- **File Sharing Registry** — metadata-only sharing with MAD re-sharing detection
- **Git-Verifiable Contracts** — bilateral confirmation with git commit hash verification
- **GitHub App Integration** — automatic bilateral read-only repo access on contract confirmation
- **Immutable Audit Log** — full audit trail viewer
- **Cold Search** — free search across internal DB and GitHub, no registration required
- **Deep Repository Analysis** — analyze any public GitHub repo for originality scoring
- **Universal Proforma** — 3-mode workflow (extract/validate/submit) for structured commits
- **Beta Bug Reporting** — built-in bug reporting tool, works without registration

## Installation

Research Match is **local-first**. The recommended path runs the server on your own machine with SQLite storage — it works offline, keeps all data private on your device, and requires no account or API key. A shared remote connector is also available as an optional, experimental convenience.

### For Claude Desktop (Recommended: local)

The desktop extension runs Research Match locally via UV (Python). Requires [Python 3.12+](https://www.python.org/) and [uv](https://github.com/astral-sh/uv).

1. Install the Research Match desktop extension (the `.mcpb` bundle) in Claude Desktop
2. Claude Desktop launches the server locally on demand — all data is stored in a local SQLite database on your machine, and nothing is transmitted to any server
3. Restart Claude Desktop — you should see 27 Research Match tools available

Prefer to run it yourself from source:

```bash
git clone https://github.com/faustojdb/ResearchMatch.git
cd ResearchMatch
uv run research-match
```

This starts the server in stdio mode with local SQLite storage. Set `RESEARCH_MATCH_DB` to customize the database path.

### For Claude Code (CLI, local)

```bash
git clone https://github.com/faustojdb/ResearchMatch.git
cd ResearchMatch
claude mcp add research-match -- uv run --directory . research-match
```

### Optional: Experimental remote connector

> **Experimental.** A shared hosted instance runs on Google Cloud Run for quick trials without a local Python setup. This shared remote mode currently has **no authentication** — until OAuth lands, do **not** put sensitive or unpublished research into the hosted instance. Use local mode for anything private.

Claude Desktop — go to **Settings > Connectors** and add the URL:

```
https://research-match-77626397872.us-central1.run.app/mcp/
```

Claude Code:

```bash
claude mcp add research-match --transport http https://research-match-77626397872.us-central1.run.app/mcp/
```

If your Claude Desktop version lacks the Connectors option, bridge with `mcp-remote` (requires [Node.js](https://nodejs.org/)) by adding this to `claude_desktop_config.json`:

| OS | Config file path |
|----|------------------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "research-match": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://research-match-77626397872.us-central1.run.app/mcp/"
      ]
    }
  }
}
```

### Getting Started

Once connected, start by saying: *"Register me on Research Match"* — Claude will call the register tool and guide you through the flow.

## Tools

| # | Tool | Description |
|---|------|-------------|
| 1 | `register` | Register with a pseudonymous identity |
| 2 | `analyze_work` | Get the Research Commit template |
| 3 | `submit_commit` | Submit work for originality scoring |
| 4 | `my_profile` | View your profile, scores, and history |
| 5 | `find_collaborators` | Find complementary researchers |
| 6 | `send_request` | Send a collaboration request |
| 7 | `inbox` | View incoming/outgoing requests |
| 8 | `respond_request` | Accept or reject a request |
| 9 | `rate_user` | Rate a collaborator (anonymous until mutual) |
| 10 | `cold_search` | Free search — no registration needed |
| 11 | `deep_search` | Analyze any GitHub repo for originality |
| 12 | `prepare_commit` | Universal proforma (extract/validate/submit) |
| 13 | `needs_create` | Create a collaboration ticket |
| 14 | `needs_list` | List tickets for a team |
| 15 | `needs_resolve` | Resolve a collaboration ticket |
| 16 | `reveal_request` | Request to view teammate's commit content |
| 17 | `reveal_respond` | Approve or deny a reveal request |
| 18 | `reveal_status` | View reveal matrix and approved content |
| 19 | `team_license` | View/recalculate team license |
| 20 | `share_file` | Share file metadata with a team |
| 21 | `shared_files` | List shared files for a team |
| 22 | `audit_log` | View the immutable audit trail |
| 23 | `export_contract` | Export a git-verifiable contract |
| 24 | `confirm_contract` | Confirm a contract with a git hash |
| 25 | `connect_github` | Connect GitHub account via GitHub App |
| 26 | `disconnect_github` | Disconnect GitHub and revoke repo access |
| 27 | `report_bug` | Report a bug — works without registration |

## Examples

### Example 1: Register and Submit Research

**User prompt**: *"Register me on Research Match with my email researcher@university.edu, then help me submit my work on federated learning for healthcare."*

**What happens**:
1. Claude calls `register` with the email (SHA-256 hashed, never stored in plain text)
2. Claude calls `analyze_work` to get the Research Commit template
3. Claude helps the user fill in the structured fields (domain, hypothesis, methodology, solidity level)
4. Claude calls `submit_commit` — originality is scored (novelty grounded in published literature via OpenAlex) and returns scores like:
   - Theoretical Originality: 72.5% (functional solidity)
   - Formal-Computational Originality: 65.8% (functional solidity)

**Expected output** (from `submit_commit`):
```json
{
  "status": "submitted",
  "version": 1,
  "scores": {
    "ot_score": 72.5,
    "ofc_score": 65.8,
    "overall_solidity": "functional"
  },
  "next_step": "Use find_collaborators to discover complementary researchers"
}
```

### Example 2: Free Cold Search (No Registration)

**User prompt**: *"Search Research Match for anyone working on quantum error correction."*

**What happens**: Claude calls `cold_search` with keywords `["quantum", "error", "correction"]`. This tool requires no registration — anyone can search. Cold search returns basic public info only — no scores, and NOT the full hypothesis text (the hypothesis is gated behind bilateral reveal / progressive disclosure).

**Expected output** (from `cold_search`):
```json
{
  "status": "ok",
  "query": "quantum error correction",
  "total_results": 2,
  "note": "Cold search is FREE — no registration needed. Register to submit your own work and find collaborators.",
  "internal_results": [
    {"source": "internal", "pseudonym": "QuantumCat-7x", "domain": "quantum computing", "subdomain": "error correction", "problem": "Reducing logical error rates in surface codes", "solidity": "functional", "date": "2026-02-19T10:30:00Z"}
  ],
  "github_results": [
    {"source": "github", "name": "owner/qec-toolkit", "description": "Surface code decoders and benchmarks", "url": "https://github.com/owner/qec-toolkit", "language": "Python", "stars": 128, "updated": "2026-01-15T08:00:00Z"}
  ]
}
```

### Example 3: Report a Bug (No Registration Required)

**User prompt**: *"The cold_search tool returned an empty result when I searched for 'machine learning'. Can you report this bug?"*

**What happens**: Claude calls `report_bug` with the error details. This works even if the user is not registered.

**Expected output** (from `report_bug`):
```json
{
  "status": "reported",
  "report_id": "a1b2c3d4-...",
  "severity": "medium",
  "server_version": "3.2.0",
  "reporter": "anonymous",
  "message": "Bug report received (severity: medium). Report ID: a1b2c3d4-.... Thank you for helping improve Research Match!"
}
```

## Typical Flow

```
register -> submit_commit -> find_collaborators -> send_request -> inbox
    -> respond_request -> reveal_request -> reveal_respond -> team_license
    -> share_file -> export_contract -> confirm_contract -> connect_github
```

## Requirements

- **Claude Desktop** or **Claude Code** (for MCP client)
- No local dependencies needed when using the Cloud Run server
- For local development: Python 3.12+, [uv](https://github.com/astral-sh/uv)

## Architecture

- **Backend**: Python + [FastMCP](https://github.com/jlowin/fastmcp) framework
- **Database**: Firebase Firestore (production) / SQLite (local development)
- **Search**: keyword matching over Firestore/SQLite. Algolia full-text indexing is an
  optional, currently-unconfigured enhancement — `cold_search` works fully without it.
- **Novelty grounding**: OpenAlex (free, no key) for literature-grounded originality scoring
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2) with Jaccard fallback
- **GitHub Integration**: GitHub App for bilateral repo access (PyJWT + httpx)
- **Hosting**: Google Cloud Run (streamable-http transport)

## Privacy Policy

See [PRIVACY_POLICY.md](PRIVACY_POLICY.md) for the full privacy policy.

**Summary**: Research Match hashes your email with SHA-256 (never stores plain text), uses pseudonymous identities, and shares research data only through bilateral consent. No advertising, no data sales, no tracking. Data is stored in Google Cloud Firestore (encrypted at rest and in transit). See the full policy for details on data collection, usage, retention, and your rights.

## Support

- **Issues**: [github.com/faustojdb/ResearchMatch/issues](https://github.com/faustojdb/ResearchMatch/issues)
- **Bug reports**: Use the built-in `report_bug` tool directly from Claude Desktop or Claude Code
- **Developer**: [github.com/faustojdb](https://github.com/faustojdb)

## License

This project is licensed under the [Business Source License 1.1](LICENSE).

- **Licensor**: Fausto Jose Di Bacco
- **Licensed Work**: ResearchMatch
- **Additional Use Grant**: You may use and redistribute the Licensed Work for any non-commercial purpose, including non-commercial production use and distribution through application directories and marketplaces (such as the Anthropic MCP directory). You may NOT use it for a commercial purpose, which includes selling or leasing it, or offering it to third parties as a paid hosted or managed service (SaaS).
- **Change Date**: February 18, 2031
- **Change License**: Apache License, Version 2.0

After the Change Date, the code becomes available under Apache 2.0.
