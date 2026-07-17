---
name: rm-search
description: Search for research projects and researchers globally without needing an account. Use when users want to explore what research exists in a field.
argument-hint: "[search query]"
disable-model-invocation: true
allowed-tools: "mcp__research-match__research_match_cold_search"
---

# Research Match — Cold Search

Search the global research database for projects matching: **$ARGUMENTS**

## Instructions

1. Call `research_match_cold_search` with the query `$ARGUMENTS`
2. Present results clearly:
   - For each result show: title, research area, originality scores (OT/OFC), and semaphore color
   - Highlight what makes each project original
   - If no results found, suggest refining the query
3. Remind the user: to connect with any researcher, they need to register first with `/rm-start`

## Notes
- This is a read-only search — no account needed
- Results show anonymized researcher IDs (not real names)
- Originality scores: OT = Theoretical Originality, OFC = Formal-Computational Originality
