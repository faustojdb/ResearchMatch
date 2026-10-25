---
name: rm-profile
description: View your Research Match profile and reputation, check collaboration requests, and rate collaborators after working together.
argument-hint: "[profile | inbox | rate]"
disable-model-invocation: true
allowed-tools: "mcp__plugin_research-match_research-match__research_match_my_profile, mcp__plugin_research-match_research-match__research_match_inbox, mcp__plugin_research-match_research-match__research_match_rate_user"
---

# Research Match — Profile, Inbox & Ratings

Identity comes from the registered session; none of these tools takes a `user_id`.

## View profile
1. Call `research_match_my_profile` (no parameters).
2. Present: pseudonym, reputation badge and score, latest Research Commit with OT/OFC
   scores and solidity impact, per-factor score breakdown, and team memberships.
3. If there are no commits yet, suggest `/research-match:rm-start`.

## Check inbox
1. Call `research_match_inbox` (no parameters).
2. Show pending requests; to accept or reject use `/research-match:rm-match`.

## Rate a collaborator
1. Ask for: `team_id`, `rated_user_id`, and three 1–5 scores — `honesty` (did they declare
   solidity accurately?), `quality`, `effort` — plus an optional private `comment`.
2. Call `research_match_rate_user`.
3. Explain the rules: ratings stay anonymous until both team members have rated, cannot
   be modified afterwards, honesty carries the highest weight (50%), and abusive patterns
   (always 1 star, always 5 stars) are detected.
