---
name: rm-start
description: Get started with Research Match — register a pseudonymous profile and submit your first Research Commit for literature-grounded originality scoring. Use for onboarding new researchers.
argument-hint: "[optional pseudonym]"
disable-model-invocation: true
allowed-tools: "mcp__plugin_research-match_research-match__research_match_register, mcp__plugin_research-match_research-match__research_match_analyze_work, mcp__plugin_research-match_research-match__research_match_submit_commit, mcp__plugin_research-match_research-match__research_match_prepare_commit, mcp__plugin_research-match_research-match__research_match_my_profile"
---

# Research Match — Onboarding

Walk the user through registration and their first Research Commit. Use the exact
field names below — every tool rejects unknown fields.

## Step 1: Register

`research_match_register` takes exactly two fields:
- `email` (required) — ask the user explicitly which email to register with. Never reuse
  an address seen elsewhere in the conversation. Tell them only its SHA-256 hash is stored.
- `pseudonym` (optional) — use `$ARGUMENTS` if provided; otherwise ask, or let the server
  generate one.

Do not send a name, research area, keywords or any other field. Registration is
idempotent: calling it again with the same email returns the existing profile.

## Step 2: Get the Research Commit template

Call `research_match_analyze_work` (no parameters). It returns the template and the
solidity guide. Explain the solidity levels briefly: `proven`, `functional`,
`speculative`, `adhoc`, `cherry_picked`. Coach the user to declare them honestly —
collaborators rate honesty later and it carries the highest weight in reputation.

## Step 3: Fill the commit together

Required fields: `domain` (e.g. "machine learning") and `problem` (at least 10 characters).

Optional fields that improve the score: `subdomain`, `hypothesis`, `theoretical_framework`,
`demonstrations_summary`, `demo_types` (math, code, data, proof_assistant, simulation),
`code_languages`, `adhoc_summary`, `adhoc_connections`, `cherry_picking`,
`solidity_levels` (per component) or `overall_solidity`, `git_repo_url`, `git_commit_hash`.

If the work lives in a local folder or a public GitHub repo, offer the proforma instead:
`research_match_prepare_commit` with `mode="extract"` and either `project_path`
(absolute path) or `repo_url`. Fill the returned narrative, check it with
`mode="validate"`, then send it with `mode="submit"`.

## Step 4: Submit and explain the result

Call `research_match_submit_commit`. Present:
- **OT** (Theoretical Originality) — novelty grounded in real published literature via
  OpenAlex, plus comparison with other registered work.
- **OFC** (Formal-Computational Originality) — strength of the declared demonstrations.
  This axis is self-declared, not verified.
- Solidity and the scoring metadata (`novelty_grounding`, `reference_works`). If the
  result is a neutral "unscored" value, explain that no reference literature was found
  (niche topic or offline) rather than inventing a number.

## Step 5: Next steps

Tell them: "You're registered. Use `/research-match:rm-match` to find collaborators, or
`/research-match:rm-profile` to review your profile." `research_match_my_profile` needs
no parameters.
