---
name: rm-search
description: Search registered research projects and public GitHub repositories by topic without needing an account. Use when users want to explore what research exists in a field.
argument-hint: "[search query]"
disable-model-invocation: true
allowed-tools: "mcp__plugin_research-match_research-match__research_match_cold_search"
---

# Research Match — Cold Search

Search for research matching: **$ARGUMENTS**

## Instructions

1. Call `research_match_cold_search` with `query` = `$ARGUMENTS` (2–200 characters).
   Optionally set `max_results` (1–25, default 10).
2. Present the two result groups separately:
   - **Registered researchers** (`internal_results`): pseudonym, domain, subdomain, problem,
     solidity level and date. Cold search deliberately returns no originality scores, no
     hypothesis text and no contact details — those are gated behind registration and
     bilateral reveal.
   - **GitHub repositories** (`github_results`): name, description, URL, language, stars.
3. If nothing matches, suggest broader keywords (a domain name or a technology works best).
4. Remind the user: to connect with a registered researcher they need to register first
   with `/research-match:rm-start`.

## Notes
- Read-only and free — no account needed.
- Only pseudonyms are shown, never real names or emails.
- The internal database grows as more researchers register, so early results may be sparse.
