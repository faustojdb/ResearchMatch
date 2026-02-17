---
name: rm-profile
description: View your Research Match profile, inbox, and rate collaborators. Use to check your status and manage your researcher identity.
argument-hint: "[your user ID]"
disable-model-invocation: true
allowed-tools: "mcp__research-match__research_match_my_profile, mcp__research-match__research_match_inbox, mcp__research-match__research_match_rate_user"
---

# Research Match — Profile & Inbox

## What do you want to do?

### View profile
1. Call `research_match_my_profile` with user_id `$ARGUMENTS` (or ask for it)
2. Present clearly:
   - Name, research area, keywords
   - Reputation scores (honesty, quality, effort)
   - Number of commits, teams, and pending requests
   - Originality scores for their commits

### Check inbox
1. Call `research_match_inbox` with the user's ID
2. Show pending collaboration requests
3. Offer to respond to any request (use `/rm-match` for that)

### Rate a collaborator
1. Ask for:
   - The user ID of the collaborator to rate
   - Honesty rating (1-5)
   - Quality rating (1-5)
   - Effort rating (1-5)
   - Optional comment
2. Call `research_match_rate_user`
3. Note: ratings use exponential smoothing — each new rating updates the running average
