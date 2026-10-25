# Research Match

**A Claude plugin and MCP server that connects isolated researchers via literature-grounded originality scoring and bilateral matching.**

Research Match helps researchers, scientists, developers, and independent theorists find complementary collaborators while protecting intellectual property. It scores originality on two independent axes — grounding novelty in real published literature (via the free OpenAlex API) using semantic-embedding similarity, combined with a transparent structured self-assessment — and pairs it with bilateral matching via a semaphore system that shows each researcher what they gain from a potential collaboration.

## How It Works

1. **Register** with a pseudonymous identity (email is SHA-256 hashed, never stored in plain text)
2. **Submit a Research Commit** describing your work — originality is scored on two axes:
   - **Theoretical Originality (OT)**: novelty of hypotheses, interdisciplinary connections, ad-hoc content
   - **Formal-Computational Originality (OFC)**: code quality, validation power, technical sophistication (self-declared)
3. **Find Collaborators** — the matching engine identifies researchers with complementary strengths and assigns a bilateral semaphore (GREEN/YELLOW/RED)
4. **Collaborate** — accept requests, reveal work progressively, share files, generate contracts

## Features

- **27 MCP Tools** covering the full research collaboration lifecycle
- **Dual-Axis Originality Scoring** — novelty grounded in real published literature via the free OpenAlex API using semantic-embedding similarity, plus a transparent structured self-assessment with solidity multipliers (proven, functional, speculative, adhoc). Runs locally with no API key and no LLM; when offline it degrades to a neutral "unscored" state rather than fabricating a number.
- **Bilateral Matching** with perspective-aware reasoning — each side sees gains from their viewpoint
- **Privacy by Design** — pseudonymous identities, SHA-256 hashed emails, progressive disclosure
- **Reputation System** — anti-retaliation ratings, exponential smoothing, honesty-weighted
- **Collaboration Tickets** — structured need_help/can_offer/warning/question system
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

Research Match is **local-first**: the server runs on your own machine over stdio with SQLite storage, works offline, keeps all data private on your device, and needs no account or API key. It is packaged as a **Claude plugin** (skill + slash commands + the local MCP server). A shared remote connector exists as an optional, experimental demo.

### Requirements

- [uv](https://github.com/astral-sh/uv) on your `PATH`. uv fetches Python 3.12 automatically if you don't have it.
- A surface that runs local MCP servers: **Claude Code** (terminal, IDE extensions, or the desktop app's Code tab) or **Cowork** in the Claude desktop app. In claude.ai web chat the skill loads but the local server does not start, so the tools are unavailable there.
- Disk space and a few minutes on first start: `uv` installs the Python dependencies (several hundred MB, including PyTorch for the embedding model). Later starts are instant.

### Option 1 — Install the plugin in Claude Code (recommended)

From your shell:

```bash
claude plugin install research-match --marketplace faustojdb/ResearchMatch
```

Or inside a Claude Code session:

```
/plugin install research-match --marketplace faustojdb/ResearchMatch
```

This adds the repository as a marketplace and installs the `research-match` plugin from it. Update later with `claude plugin update research-match@research-match-marketplace`.

Once the plugin is listed in [Anthropic's directory](https://claude.ai/directory), you will also be able to add it from **Customize > Plugins > Discover** on claude.ai; a plugin added there syncs to Cowork and to your Claude Code sessions.

### Option 2 — Run from source

```bash
git clone https://github.com/faustojdb/ResearchMatch.git
cd ResearchMatch
claude --plugin-dir .            # load the checkout as a plugin for one session
```

or register only the MCP server, without the skill and slash commands:

```bash
claude mcp add research-match -- uv run --directory /path/to/ResearchMatch --frozen research-match
```

### Option 3 — Claude Desktop extension (.mcpb, manual install)

A desktop-extension bundle can still be built with `mcpb pack` (the `.mcpbignore` file keeps development files out of it) and installed by hand in Claude Desktop under **Settings > Extensions > Advanced settings > Install Extension…**. Note that Anthropic no longer lists desktop extensions in its directory, so this is a side channel, not the main distribution path.

### Option 4 — Experimental remote connector

> **Experimental — demo only.** A shared hosted instance runs on Google Cloud Run so you can try the tools without a local Python setup. It has **no authentication** (identity is a self-asserted email hash) and it is **not kept in lockstep with releases** — check `/health` for the version it is serving. Do **not** put sensitive or unpublished research into the hosted instance; use local mode for anything private.

Claude Desktop: **Settings > Connectors**, add `https://research-match-77626397872.us-central1.run.app/mcp/`.

Claude Code:

```bash
claude mcp add research-match --transport http https://research-match-77626397872.us-central1.run.app/mcp/
```

### Where your data lives

In plugin mode the SQLite database is stored in the plugin's persistent data directory (`${CLAUDE_PLUGIN_DATA}/research_match.db`, which survives plugin updates). Set `RESEARCH_MATCH_DB` to use another path. Databases created by releases before 3.4.0 (which lived inside the plugin folder) are migrated automatically on first start.

### Getting Started

Once installed, say: *"Register me on Research Match"* — Claude will ask for the email you want to register with (only its hash is stored) and guide you through the flow. Slash commands are namespaced under the plugin name:

| Command | Purpose |
|---------|---------|
| `/research-match:rm-search <query>` | Cold search — no account needed |
| `/research-match:rm-start [pseudonym]` | Register and submit a first Research Commit |
| `/research-match:rm-analyze <GitHub URL>` | Deep repository analysis or proforma workflow |
| `/research-match:rm-match` | Find collaborators, send and answer requests |
| `/research-match:rm-profile` | Profile, inbox, rate collaborators |
| `/research-match:rm-team <team ID>` | Tickets, reveals, license, files, audit log, contracts |

## What this plugin runs, sends and fetches

Everything the plugin does is in this repository's readable source. In summary:

- **Runs**: `uv run --frozen python research_match_mcp.py` from the plugin folder — a three-line launcher that starts the Python stdio MCP server in `src/research_match_server.py`. Dependencies are pinned in `uv.lock`.
- **Writes locally**: one SQLite database (see *Where your data lives*) and uv's dependency cache. No other files are written.
- **Network calls, local mode**:
  - `api.openalex.org` — originality scoring sends only your domain/topic search terms to find related published works. Disable with `RESEARCH_MATCH_DISABLE_OPENALEX=1`.
  - `api.github.com` — `cold_search` repository search, `deep_search` repository metadata, and the GitHub App calls behind `connect_github` (only if a GitHub App is configured by the operator).
  - `huggingface.co` — one-time download of the `all-MiniLM-L6-v2` sentence-embedding model on first scoring, cached locally afterwards. If the download fails the server falls back to word-overlap (Jaccard) similarity.
  - PyPI (via uv) — dependency installation on first start.
- **Network calls, hosted mode only**: Google Cloud Firestore for storage. Algolia is referenced in the code but is not configured.
- **Never**: no telemetry, no analytics, no conversation content, no raw email addresses (only SHA-256 hashes).

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

All tool names are prefixed `research_match_` on the wire (e.g. `research_match_register`).

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

**What happens**: Claude calls `cold_search` with the query `quantum error correction`. This tool requires no registration — anyone can search. Cold search returns basic public info only — no scores, and NOT the full hypothesis text (the hypothesis is gated behind bilateral reveal / progressive disclosure).

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
  "server_version": "3.4.1",
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

## Why register?

Research Match is a two-sided network — `find_collaborators` and part of the
originality scoring only get better as real, honest work gets registered. See
[ROADMAP.md](ROADMAP.md) for exactly what your registration unlocks and what
happens next as real usage grows.

## Architecture

- **Backend**: Python + [FastMCP](https://github.com/jlowin/fastmcp) framework (`mcp` SDK)
- **Database**: SQLite (local-first default) / Firebase Firestore (hosted, experimental)
- **Search**: keyword matching over SQLite/Firestore. Algolia full-text indexing is an
  optional, currently-unconfigured enhancement — `cold_search` works fully without it.
- **Novelty grounding**: OpenAlex (free, no key) for literature-grounded originality scoring
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2) with Jaccard fallback
- **GitHub Integration**: GitHub App for bilateral repo access (PyJWT + httpx)
- **Hosting (optional)**: Google Cloud Run (streamable-http transport)
- **Plugin layout**: `.claude-plugin/plugin.json` (manifest), `.mcp.json` (local server), `research_match_mcp.py` (launcher), `skills/research-match/SKILL.md`, `commands/*.md`

## Development

```bash
git clone https://github.com/faustojdb/ResearchMatch.git
cd ResearchMatch
uv sync --extra dev
RESEARCH_MATCH_DISABLE_OPENALEX=1 uv run pytest -q      # offline unit tests (emulator tests auto-skip)
claude plugin validate .                                 # manifest / component checks
claude --plugin-dir .                                    # try the plugin in a session
git config core.hooksPath .githooks                      # enable the secret-guard pre-commit hook
```

See [SUBMISSION.md](SUBMISSION.md) for the directory submission checklist, [SECURITY.md](SECURITY.md) for the threat model and secret handling, and [ROADMAP.md](ROADMAP.md) for what comes next.

## Privacy Policy

See [PRIVACY_POLICY.md](PRIVACY_POLICY.md) for the full privacy policy.

**Summary**: Research Match hashes your email with SHA-256 (never stores plain text), uses pseudonymous identities, and shares research data only through bilateral consent. No advertising, no data sales, no tracking. In local mode all data stays in a SQLite file on your machine; the optional hosted instance stores data in Google Cloud Firestore (encrypted at rest and in transit). See the full policy for details on data collection, usage, retention, and your rights.

## Support

- **Issues**: [github.com/faustojdb/ResearchMatch/issues](https://github.com/faustojdb/ResearchMatch/issues)
- **Bug reports**: Use the built-in `report_bug` tool directly from Claude
- **Security**: see [SECURITY.md](SECURITY.md)
- **Developer**: Fausto Jose Di Bacco — [github.com/faustojdb](https://github.com/faustojdb) — faustojdb@gmail.com

## License

This project is licensed under the [Business Source License 1.1](LICENSE) (SPDX: `BUSL-1.1`).

- **Licensor**: Fausto Jose Di Bacco
- **Licensed Work**: ResearchMatch
- **Additional Use Grant**: You may use and redistribute the Licensed Work for any non-commercial purpose, including non-commercial production use and distribution through application directories and marketplaces (such as the Anthropic directory). You may NOT use it for a commercial purpose, which includes selling or leasing it, or offering it to third parties as a paid hosted or managed service (SaaS).
- **Change Date**: February 18, 2031
- **Change License**: Apache License, Version 2.0

After the Change Date, the code becomes available under Apache 2.0.
