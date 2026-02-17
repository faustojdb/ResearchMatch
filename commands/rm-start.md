---
name: rm-start
description: Get started with Research Match. Register your profile and submit your first research commit. Use for onboarding new researchers.
argument-hint: "[your name]"
disable-model-invocation: true
allowed-tools: "mcp__research-match__research_match_register, mcp__research-match__research_match_analyze_work, mcp__research-match__research_match_submit_commit, mcp__research-match__research_match_prepare_commit"
---

# Research Match — Onboarding

Welcome to Research Match! Let's get you set up.

## Step 1: Register

Ask the user for:
- **Name** (use `$ARGUMENTS` if provided)
- **Research area** (e.g., "machine learning", "quantum computing", "genomics")
- **Keywords** (comma-separated, 3-5 terms describing their work)

Then call `research_match_register` with this information.

## Step 2: Analyze their work (optional but recommended)

Ask if they have a GitHub repository to analyze. If yes:
- Call `research_match_analyze_work` with the repo URL
- Show them what was detected (languages, frameworks, project type)

## Step 3: Submit first research commit

Guide them to describe their research contribution:
- **Title**: Short description of the work
- **Abstract**: 2-3 sentences about what makes it original
- **Research area** and **keywords**
- **Code languages** and **demo types** if applicable

If they have a GitHub repo, suggest using `research_match_prepare_commit` in extract mode to auto-generate the commit data from the repository.

Then call `research_match_submit_commit` with the data.

## Step 3 result

Show the user their originality scores:
- **OT** (Originality Threshold): How novel is this vs existing work?
- **OFC** (Originality Frontier Contribution): How much does this push the field forward?
- **Semaphore**: Overall readiness indicator

Tell them: "You're registered! Use `/rm-match` to find collaborators, or `/rm-profile` to see your profile."
