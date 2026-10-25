---
name: rm-analyze
description: Analyze a public GitHub repository (metadata, stack, optional originality estimate) or prepare a structured Research Commit from a local project or repo with the proforma workflow.
argument-hint: "[GitHub URL | extract | validate | submit]"
disable-model-invocation: true
allowed-tools: "mcp__plugin_research-match_research-match__research_match_deep_search, mcp__plugin_research-match_research-match__research_match_prepare_commit"
---

# Research Match — Deep Analysis & Proforma

## Option A: Deep repository analysis

If `$ARGUMENTS` looks like a GitHub URL (`https://github.com/owner/repo`):

1. Call `research_match_deep_search` with:
   - `repo_url`: the URL (GitHub only; other hosts are rejected)
   - `include_scoring`: true if the user wants an originality estimate
   - Leave `include_mcp_analysis` and `include_comparison` alone — they are reserved
     flags with no effect in the current release. Do not promise MCP-gap or comparison output.
2. Present what the tool actually returns: repository metadata (stars, forks, license,
   topics), language/LOC breakdown, recent commits, top-level file tree, README preview,
   dependency files and, if requested, the OT/OFC estimate with its OpenAlex reference works.
3. No account is needed and nothing is stored — the analysis is stateless and uses the
   GitHub API (no clone).

## Option B: Prepare a Research Commit (proforma)

If `$ARGUMENTS` is `extract`, `validate` or `submit`, or the user wants to turn a project
into a Research Commit:

1. **extract** — call `research_match_prepare_commit` with `mode="extract"` and either
   `project_path` (absolute path to a local folder) or `repo_url`. It returns
   machine-extracted facts plus a narrative prompt. Fill the narrative with the user:
   domain, subdomain, problem, hypothesis, theoretical_framework, demonstrations_summary,
   adhoc_summary, adhoc_connections, cherry_picking and a `solidity_assessment` with
   reasoning for each level.
2. **validate** — call it again with `mode="validate"` and `narrative_json` (the filled
   narrative as a JSON string). Show blocking errors and warnings.
3. **submit** — call it with `mode="submit"` and the same `narrative_json`. There is no
   `user_id` parameter: the server resolves identity from the registered session, so the
   user must have registered (`/research-match:rm-start`) first. Show the resulting scores.

## Tips
- Extract → validate → submit is the recommended order.
- Solidity values must be one of: proven, functional, speculative, adhoc, cherry_picked.
