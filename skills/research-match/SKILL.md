---
name: research-match
description: Research Match connects isolated researchers via literature-grounded originality scoring and bilateral matching. Use when users mention research matching, originality scoring, find collaborators, research collaboration, OT/OFC scores, bilateral matching, research privacy, or academic networking.
user-invocable: false
allowed-tools: "mcp__research-match__research_match_register, mcp__research-match__research_match_analyze_work, mcp__research-match__research_match_submit_commit, mcp__research-match__research_match_my_profile, mcp__research-match__research_match_find_collaborators, mcp__research-match__research_match_send_request, mcp__research-match__research_match_inbox, mcp__research-match__research_match_respond_request, mcp__research-match__research_match_rate_user, mcp__research-match__research_match_cold_search, mcp__research-match__research_match_deep_search, mcp__research-match__research_match_prepare_commit, mcp__research-match__research_match_needs_create, mcp__research-match__research_match_needs_list, mcp__research-match__research_match_needs_resolve, mcp__research-match__research_match_reveal_request, mcp__research-match__research_match_reveal_respond, mcp__research-match__research_match_reveal_status, mcp__research-match__research_match_team_license, mcp__research-match__research_match_share_file, mcp__research-match__research_match_shared_files, mcp__research-match__research_match_audit_log, mcp__research-match__research_match_export_contract, mcp__research-match__research_match_confirm_contract, mcp__research-match__research_match_connect_github, mcp__research-match__research_match_disconnect_github, mcp__research-match__research_match_report_bug"
---

# Research Match — Literature-Grounded Research Collaboration

Research Match is an MCP server with 27 tools that connects isolated researchers through literature-grounded originality scoring, bilateral matching, GitHub App integration, and privacy-first collaboration.

## Core Concepts

### Originality Scoring (OT/OFC)
Every research commit is evaluated on two axes:
- **OT (Theoretical Originality)**: How novel are the hypotheses, interdisciplinary connections, and ad-hoc reasoning compared to real published literature and other registered work.
- **OFC (Formal-Computational Originality)**: How strong is the formal/computational demonstration — code, data, validation, technical sophistication (structured self-assessment).

Scores are 0-100%, with solidity multipliers applied based on evidence quality (theory, demos, ad-hoc).

### Bilateral Matching (Semaphore System)
When finding collaborators, each pair gets a semaphore:
- **GREEN**: High mutual gain — both researchers benefit significantly from collaboration
- **YELLOW**: Moderate gain — some complementary strengths exist
- **RED**: Low gain — limited collaboration potential

The system uses a 5-rule calibration to ensure fair matching based on complementary strengths and weaknesses.

### Privacy Model (Levels 1-4)
1. **Level 1**: Registration — only name, area, keywords visible
2. **Level 2**: Matching — originality scores visible to matches
3. **Level 3**: Reveals — bilateral consent to view commit content
4. **Level 4**: File sharing — only after mutual Level 3 consent

## Tool Groups & Flow

### Getting Started (no account needed)
- `cold_search` — Search the global database for research projects

### Onboarding
- `register` — Create a researcher profile
- `analyze_work` — Analyze a project's research characteristics
- `submit_commit` — Submit a research contribution for scoring
- `prepare_commit` — Structured proforma for commit preparation (extract/validate/submit)

### Discovery & Matching
- `find_collaborators` — Get ranked matches with semaphore indicators
- `send_request` — Send a collaboration request
- `inbox` — View pending requests
- `respond_request` — Accept or decline a collaboration request

### Profile & Reputation
- `my_profile` — View your profile and stats
- `rate_user` — Rate a collaborator (honesty, quality, effort)

### Team Collaboration (after matching)
- `needs_create` / `needs_list` / `needs_resolve` — Structured ticket system
- `reveal_request` / `reveal_respond` / `reveal_status` — Bilateral content reveals
- `team_license` — Automatic license computation
- `share_file` / `shared_files` — Metadata-only file registry (Level 4)
- `audit_log` — Immutable audit trail viewer
- `export_contract` / `confirm_contract` — Git-verifiable collaboration contracts

### GitHub Integration
- `connect_github` — Connect your GitHub account via GitHub App for bilateral repo access
- `disconnect_github` — Disconnect GitHub and revoke all repo access

### Analysis (stateless, no account)
- `deep_search` — Clone and analyze any public GitHub repository

### Bug Reporting (no account needed)
- `report_bug` — Report a bug or issue with Research Match, works anonymously

## Slash Commands
Users can also use these slash commands for guided workflows:
- `/rm-search [query]` — Search for research projects
- `/rm-start [name]` — Register and submit first commit
- `/rm-match [user ID]` — Find collaborators and manage requests
- `/rm-profile [user ID]` — View profile and rate collaborators
- `/rm-team [team ID]` — Full team management hub
- `/rm-analyze [GitHub URL]` — Deep analysis and proforma

## When to Use Research Match
Activate this skill when users:
- Want to find research collaborators in any field
- Ask about originality or novelty scoring of research
- Need to evaluate if their work is original
- Want privacy-preserving research collaboration
- Mention OT, OFC, bilateral matching, or research semaphores
- Want to analyze a GitHub repository for research value
- Need to create collaboration contracts or licenses
