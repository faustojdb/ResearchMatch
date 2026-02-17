---
name: rm-team
description: Manage your research collaboration team. Access tickets, reveals, licensing, file sharing, audit logs, and contracts. Use after accepting a collaboration request.
argument-hint: "[team ID]"
disable-model-invocation: true
allowed-tools: "mcp__research-match__research_match_needs_create, mcp__research-match__research_match_needs_list, mcp__research-match__research_match_needs_resolve, mcp__research-match__research_match_reveal_request, mcp__research-match__research_match_reveal_respond, mcp__research-match__research_match_reveal_status, mcp__research-match__research_match_team_license, mcp__research-match__research_match_share_file, mcp__research-match__research_match_shared_files, mcp__research-match__research_match_audit_log, mcp__research-match__research_match_export_contract, mcp__research-match__research_match_confirm_contract"
---

# Research Match — Team Management Hub

Team ID: **$ARGUMENTS**

## Available Actions

Ask the user what they need, then execute the appropriate flow:

### 1. Tickets (needs_create, needs_list, needs_resolve)
- **Create ticket**: Ask for type (need_help, question, bug_report, feature_request) and description
- **List tickets**: Show all open tickets for the team
- **Resolve ticket**: Mark a ticket as resolved with a resolution message

### 2. Reveals (reveal_request, reveal_respond, reveal_status)
- **Request reveal**: Ask to see a teammate's commit content (bilateral consent required)
- **Respond to reveal**: Accept or decline a reveal request from teammate
- **Reveal status**: Show the reveal matrix — who has consented to share what
- Both parties must consent before any content is shown (privacy-first)

### 3. License (team_license)
- View the automatically computed license for the collaboration
- License types: joint-equal, advisory-only, joint-weighted, time-limited
- Contribution percentages are calculated from commits, reveals, and resolved tickets

### 4. File Sharing (share_file, shared_files)
- **Share a file**: Register file metadata (path, description, hash) — requires bilateral Level 3 reveals
- **List shared files**: See all files shared in the team
- Re-sharing detection (MAD): sharing another user's file tanks your honesty score

### 5. Audit Log (audit_log)
- View the immutable audit trail for the team
- Filter by action type: license_generated, reveal_approved, violation_detected, etc.

### 6. Contracts (export_contract, confirm_contract)
- **Export contract**: Generate a markdown collaboration contract with scores, license, and verification instructions
- **Confirm contract**: Confirm a contract with a git commit hash (bilateral — both parties must confirm)

## Collaboration Flow
The typical progression is: Tickets → Reveals → File Sharing → License Review → Contract
