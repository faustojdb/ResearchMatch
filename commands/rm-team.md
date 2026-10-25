---
name: rm-team
description: Manage a research collaboration team — tickets, consent-based reveals, automatic licensing, file-sharing registry, audit log, git-verifiable contracts and GitHub repo access. Use after a collaboration request is accepted.
argument-hint: "[team ID]"
disable-model-invocation: true
allowed-tools: "mcp__plugin_research-match_research-match__research_match_needs_create, mcp__plugin_research-match_research-match__research_match_needs_list, mcp__plugin_research-match_research-match__research_match_needs_resolve, mcp__plugin_research-match_research-match__research_match_reveal_request, mcp__plugin_research-match_research-match__research_match_reveal_respond, mcp__plugin_research-match_research-match__research_match_reveal_status, mcp__plugin_research-match_research-match__research_match_team_license, mcp__plugin_research-match_research-match__research_match_share_file, mcp__plugin_research-match_research-match__research_match_shared_files, mcp__plugin_research-match_research-match__research_match_audit_log, mcp__plugin_research-match_research-match__research_match_export_contract, mcp__plugin_research-match_research-match__research_match_confirm_contract, mcp__plugin_research-match_research-match__research_match_connect_github, mcp__plugin_research-match_research-match__research_match_disconnect_github"
---

# Research Match — Team Hub

Team ID: **$ARGUMENTS** (ask for it if missing; it comes from the accepted request or
`research_match_my_profile`). Ask what the user needs, then run the matching flow with the
exact field values below.

### 1. Tickets
- **Create**: `research_match_needs_create` — `team_id`, `type` (need_help, can_offer,
  warning, question), `area` (theory, code, data, review, infrastructure), `title`,
  `description`, `priority` (critical, important, nice_to_have).
- **List**: `research_match_needs_list` — `team_id`, optional `status` (open, in_progress,
  resolved, wont_fix), `area`, `type`.
- **Resolve**: `research_match_needs_resolve` — `ticket_id`, `resolution` (resolved or
  wont_fix), optional `resolution_note`. Resolving a teammate's ticket boosts effort reputation.

### 2. Reveals (consent-based disclosure of Research Commit content)
- **Request**: `research_match_reveal_request` — `team_id`, `target_user_id`.
- **Respond**: `research_match_reveal_respond` — `consent_id`, `approve` (true/false).
  Approval triggers a license recalculation.
- **Status**: `research_match_reveal_status` — `team_id`. Shows the consent matrix and any
  content already approved for the user.
- Nothing is shown until the owner approves.

### 3. License
- `research_match_team_license` — `team_id`. Shows (and recalculates) the automatic license:
  joint-equal, advisory-only, joint-weighted or time-limited, with contribution percentages.

### 4. File sharing (metadata only)
- **Share**: `research_match_share_file` — `team_id`, `file_path`, optional `file_hash`
  (SHA-256) and `description`. Requires bilateral reveals first. Re-sharing another
  member's file is detected and penalises honesty reputation.
- **List**: `research_match_shared_files` — `team_id`.

### 5. Audit log
- `research_match_audit_log` — `team_id`, optional `action_filter` (e.g. file_shared,
  violation_detected, license_generated) and `limit` (1–200).

### 6. Contracts
- **Export**: `research_match_export_contract` — `team_id`. Returns a markdown contract with
  parties, scores, license terms and verification instructions. The user commits it to git.
- **Confirm**: `research_match_confirm_contract` — `team_id`, `contract_id`,
  `git_commit_hash` (40-character lowercase hex), optional `repo_url`. Both members must
  confirm. When both have connected GitHub, read-only repo access is granted bilaterally.

### 7. GitHub access
- **Connect**: `research_match_connect_github` — `github_username`. Returns the GitHub App
  installation link if needed.
- **Disconnect**: `research_match_disconnect_github` — `confirm` must be true; revokes all
  access granted through Research Match.

## Typical progression
Tickets → Reveals → License review → File sharing → Contract → GitHub access
