---
name: rm-match
description: Find complementary research collaborators and manage collaboration requests (find, send, inbox, accept or reject). Use when users want to discover matches or connect with other researchers.
argument-hint: "[find | inbox | request | respond]"
disable-model-invocation: true
allowed-tools: "mcp__plugin_research-match_research-match__research_match_find_collaborators, mcp__plugin_research-match_research-match__research_match_send_request, mcp__plugin_research-match_research-match__research_match_inbox, mcp__plugin_research-match_research-match__research_match_respond_request"
---

# Research Match — Find & Connect

All four tools resolve the current user from the registered session — none of them takes
a `user_id`. If the server reports no identity, send the user to `/research-match:rm-start`.

## Option A: Find collaborators
1. Requires at least one submitted Research Commit.
2. Call `research_match_find_collaborators` with optional `limit` (1–20, default 5) and
   optional `min_semaphore` (`green`, `yellow` or `red`).
3. For each candidate show: pseudonym, semaphore and its reason **from the user's
   perspective**, what the user gains and what they contribute (percentages), the
   candidate's OT/OFC scores, reputation badge and solidity level.
4. Ask whether they want to send a request to any candidate.

## Option B: Send a collaboration request
1. Call `research_match_send_request` with `candidate_user_id` (taken from the
   find_collaborators results — a match record must exist) and an optional `message`
   (max 1000 characters) describing what they are looking for.
2. Only one pending request per candidate is allowed. The recipient sees scores from their
   own perspective and never sees the user's content.

## Option C: Check the inbox
1. Call `research_match_inbox` (no parameters).
2. Show incoming and outgoing requests with pseudonym, semaphore, status
   (pending, accepted, rejected, expired), message and date.

## Option D: Respond to a request
1. Call `research_match_respond_request` with `request_id` (from the inbox) and
   `accept` = true or false. Only pending requests can be answered.
2. If accepted, a team is created with joint-equal (50/50) licensing. Point the user to
   `/research-match:rm-team <team_id>` for tickets, reveals, files and contracts.

## Semaphore guide
Each match carries a `match_rule` naming the rule that fired; use it to explain the color.
- **GREEN** — high mutual benefit (`green_mutual`), one side gains a lot and the other
  still gains (`green_complementary`), or a strong peer pair: both ≥ 70% on OT and OFC
  with low complementarity only because the profiles are similar (`green_peer`).
- **YELLOW** — asymmetric or moderate benefit (`yellow_asymmetric`, `yellow_moderate`,
  `yellow_bilateral`), or a solid peer pair / shared strength on one axis (`yellow_peer`).
- **RED** — low measured benefit and no shared strength (`red`).
When the rule is a peer rule, say explicitly that the low "you gain / you contribute"
percentages reflect similar profiles, not a weak match.
