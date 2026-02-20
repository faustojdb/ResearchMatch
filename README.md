# Research Match

**MCP server that connects isolated researchers via AI originality scoring and bilateral matching.**

Research Match helps researchers, scientists, developers, and independent theorists find complementary collaborators while protecting intellectual property. It uses AI-powered originality scoring on two independent axes and bilateral matching with a semaphore system that shows each researcher what they gain from a potential collaboration.

## How It Works

1. **Register** with a pseudonymous identity (email is SHA-256 hashed, never stored in plain text)
2. **Submit a Research Commit** describing your work — the AI evaluates originality on two axes:
   - **Theoretical Originality (OT)**: novelty of hypotheses, interdisciplinary connections, ad-hoc content
   - **Formal-Computational Originality (OFC)**: code quality, validation power, technical sophistication
3. **Find Collaborators** — the matching engine identifies researchers with complementary strengths and assigns a bilateral semaphore (GREEN/YELLOW/RED)
4. **Collaborate** — accept requests, reveal work progressively, share files, generate contracts

## Features

- **27 MCP Tools** covering the full research collaboration lifecycle
- **Dual-Axis Originality Scoring** with solidity multipliers (proven, functional, speculative, adhoc)
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

### For Claude Desktop (Recommended)

Research Match runs as a remote MCP server on Google Cloud Run. No local installation required.

#### Option A: Settings > Connectors (Recommended)

1. Open Claude Desktop
2. Go to **Settings > Connectors**
3. Add the server URL: `https://research-match-77626397872.us-central1.run.app/mcp/`
4. Restart Claude Desktop — you should see 27 Research Match tools available

#### Option B: npx mcp-remote (Alternative)

If the Connectors option is not available in your version, you can use `mcp-remote` as a bridge. This requires [Node.js](https://nodejs.org/) installed.

Add this to your `claude_desktop_config.json`:

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

Restart Claude Desktop after saving.

#### Getting Started

Once connected, start by saying: *"Register me on Research Match"* — Claude will call the register tool and guide you through the flow.

### For Claude Code (CLI)

Add the remote MCP server:

```bash
claude mcp add research-match --transport http https://research-match-77626397872.us-central1.run.app/mcp/
```

### For Local Development

If you want to run the server locally with SQLite:

```bash
git clone https://github.com/faustojdb/ResearchMatch.git
cd ResearchMatch
uv run research-match
```

This starts the server in stdio mode. Set `RESEARCH_MATCH_DB` to customize the database path.

## Tools

| # | Tool | Description |
|---|------|-------------|
| 1 | `register` | Register with a pseudonymous identity |
| 2 | `analyze_work` | Get the Research Commit template |
| 3 | `submit_commit` | Submit work for AI originality evaluation |
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
4. Claude calls `submit_commit` — the AI evaluates originality and returns scores like:
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

**What happens**: Claude calls `cold_search` with keywords `["quantum", "error", "correction"]`. This tool requires no registration — anyone can search.

**Expected output** (from `cold_search`):
```json
{
  "query": "quantum error correction",
  "results": [
    {
      "pseudonym": "QuantumCat-7x",
      "domain": "quantum computing",
      "subdomain": "error correction",
      "hypothesis": "Surface codes with adaptive decoders reduce logical error rates by 40%",
      "ot_score": 78.2,
      "ofc_score": 81.5
    }
  ],
  "total_results": 1,
  "source": "algolia"
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
- **Search**: Algolia for cold search indexing
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
- **Additional Use Grant**: Non-commercial use only. You may not use the Licensed Work for any commercial purpose, including selling, leasing, or providing it as a service (SaaS).
- **Change Date**: February 18, 2031
- **Change License**: Apache License, Version 2.0

After the Change Date, the code becomes available under Apache 2.0.
