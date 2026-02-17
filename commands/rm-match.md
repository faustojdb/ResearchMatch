---
name: rm-match
description: Find research collaborators and manage collaboration requests. Use when users want to discover matches or connect with other researchers.
argument-hint: "[your user ID]"
disable-model-invocation: true
allowed-tools: "mcp__research-match__research_match_find_collaborators, mcp__research-match__research_match_send_request, mcp__research-match__research_match_inbox, mcp__research-match__research_match_respond_request"
---

# Research Match — Find & Connect

Help the user find and connect with research collaborators.

## What do you want to do?

Ask the user (if not clear from context):

### Option A: Find collaborators
1. Call `research_match_find_collaborators` with user_id `$ARGUMENTS` (or ask for it)
2. Present matches with:
   - Semaphore color (GREEN = strong match, YELLOW = moderate, RED = weak)
   - Mutual gain score
   - Complementary strengths and weaknesses
   - Why this match could work
3. Ask if they want to send a request to any match

### Option B: Send collaboration request
1. Ask for the target user ID and a short message
2. Call `research_match_send_request`
3. Confirm the request was sent

### Option C: Check inbox
1. Call `research_match_inbox` with the user's ID
2. Show pending requests with sender info and message
3. Ask if they want to accept or decline any request

### Option D: Respond to a request
1. Call `research_match_respond_request` with the request ID and decision (accept/decline)
2. If accepted, explain the next steps:
   - Use `/rm-team` to manage the collaboration
   - The team now has access to tickets, reveals, file sharing, contracts

## Semaphore Guide
- **GREEN**: High mutual gain — both researchers benefit significantly
- **YELLOW**: Moderate gain — some complementary strengths
- **RED**: Low gain — limited collaboration potential
