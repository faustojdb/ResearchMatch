---
name: rm-analyze
description: Analyze a GitHub repository or prepare a structured research commit. Use for deep repository analysis and proforma-based commit preparation.
argument-hint: "[GitHub URL or mode]"
disable-model-invocation: true
allowed-tools: "mcp__research-match__research_match_deep_search, mcp__research-match__research_match_prepare_commit"
---

# Research Match — Deep Analysis & Proforma

## What do you want to do?

### Option A: Deep Repository Analysis
If `$ARGUMENTS` looks like a GitHub URL:

1. Call `research_match_deep_search` with:
   - `repo_url`: the GitHub URL
   - `include_scoring`: true
   - `include_mcp_analysis`: true (if they want MCP tool analysis)
   - `include_comparison`: true (if they want comparison with Research Match)
2. Present the analysis:
   - Repository metadata (stars, commits, contributors)
   - Technology stack and architecture
   - Originality assessment (OT/OFC scores)
   - Gap analysis vs Research Match (if comparison enabled)
   - MCP tool coverage (if MCP analysis enabled)

### Option B: Prepare a Research Commit (Proforma)
If `$ARGUMENTS` is "extract", "validate", or "submit" (or user wants to prepare a commit):

1. **Extract mode**: Point to a local project path to auto-generate commit data
   - Call `research_match_prepare_commit` with mode="extract" and project_path
   - Show the generated narrative prompt — user fills it in

2. **Validate mode**: Check a filled narrative before submitting
   - Call `research_match_prepare_commit` with mode="validate" and the narrative JSON
   - Show errors (blocking) and warnings (informational)

3. **Submit mode**: Validate and submit in one step
   - Call `research_match_prepare_commit` with mode="submit", narrative JSON, and user_id
   - Show the resulting originality scores

## Tips
- Deep search is stateless — no account needed
- Proforma submit requires a registered user ID (use `/rm-start` first)
- Extract → Validate → Submit is the recommended flow for structured commits
