# Submitting Research Match to Anthropic's directory

**Status (2026-10-25):** the submission path used in February 2026 — the Google Form for
MCPB desktop extensions — has been retired. Anthropic's directory **no longer accepts local
MCP servers packaged as MCPB**; local servers are distributed inside a **plugin bundle**
submitted from the developer portal. That is why the original submission never progressed:
there was no longer a queue to progress in. This document is the current, correct path.

Sources: [Submit a plugin](https://claude.com/docs/plugins/submit),
[Plugin pre-submission checklist](https://claude.com/docs/plugins/pre-submission-checklist),
[Publish to the directory](https://claude.com/docs/directory/publish),
[Build a desktop extension with MCPB](https://claude.com/docs/connectors/building/mcpb)
("Desktop extension listings in the directory are deprecated, and the directory no longer
accepts MCPB submissions"), [Software Directory Policy](https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy).

---

## 1. What you submit, and where

| | Plugin bundle (this repo) | MCP connector (remote server) |
|---|---|---|
| Submit as | **Plugin bundle** at [claude.ai/directory/manage](https://claude.ai/directory/manage) | **MCP connector** at the same portal |
| Source | This GitHub repository (public before publishing) | An `https://` URL |
| Research Match | **Yes — submit this.** Skill + 6 commands + local MCP server | **Not yet.** The Cloud Run instance has no OAuth; authenticated remote servers "must use secure OAuth 2.0". Submit it only after ROADMAP Stage 4 |

Requirements to submit: a paid claude.ai plan (Pro/Max/Team/Enterprise); the GitHub account
that can push to `faustojdb/ResearchMatch` connected on claude.ai (the portal checks push
access); the repository public before the listing goes live (it is public now).

## 2. Repository checks — what the portal's "Validate" will see

Status of this repository against the automated checks (as of v3.4.0):

| Check | Result for this repo |
|---|---|
| `.claude-plugin/plugin.json` at the plugin root | OK |
| `name` lowercase/hyphens, not reserved, not taken | OK (`research-match`) — the portal checks collisions live |
| `description`, `author`, `version` set | OK (3.4.0) — raise `version` on every release |
| README ≥ 40 words, LICENSE present | OK |
| Directory listing fields (`displayName`, `icon`, `documentationUrl`, `supportUrl`, `privacyPolicyUrl`) | OK |
| Every tool has `title` + `readOnlyHint`/`destructiveHint` | OK (cold_search was missing them until 3.4.0) |
| `.mcp.json` valid, local server declared with `command`/`args` | OK |
| `uv run` **must** use `--locked` or `--frozen` (otherwise **Blocks**) | OK — `--frozen`, `uv.lock` committed |
| Server command names a readable file in the plugin | OK — `python ${CLAUDE_PLUGIN_ROOT}/research_match_mcp.py` (since 3.4.1) |
| No package-manager config that sets an index/registry (`uv.toml`, `.npmrc`) | OK |
| No real credentials anywhere | OK — `.env`, `*.pem`, `*credentials*.json` are gitignored and never committed |
| No `.DS_Store` / `Thumbs.db` | OK |
| Repository < 50 MiB archived, < 10,000 files | OK (about 60 tracked files, < 3 MiB) |
| Files ≤ 256 KiB (non-image) | **Hold for reviewer**: `uv.lock` (~450 KiB) and `src/research_match_server.py` (~310 KiB) exceed it |
| Package launcher (`uv run`) even when frozen | **Hold for reviewer** ("Runs a pinned … package" — dependencies resolve at install time) |

**Expect a reviewer hold, not a rejection.** A Python/uv server cannot avoid the launcher
hold (`LAUNCHER_PACKAGE_REVIEW`), and the first validation (2026-10-25, v3.4.0) also held
`src/research_match_server.py` and `uv.lock` for size, the credential env vars the server
reads (`GITHUB_APP_PRIVATE_KEY`, `GOOGLE_APPLICATION_CREDENTIALS` — vendor hosts, a
reviewer confirms) and, until they were removed, a shell script and planning notes that
mentioned the listing icon by its path; a hold means an Anthropic reviewer reads the version before it goes live. Make the
reviewer's job easy: the README section *"What this plugin runs, sends and fetches"*
declares every process, file write and network destination (OpenAlex, GitHub API,
Hugging Face model download, PyPI, optional Firestore), including the embedding worker
process the server starts with the same interpreter (`src/embedding_worker.py`). An undisclosed destination is what
fails the **security scan**, and a first submission that fails the scan is rejected.

Optional, to remove the size holds later (ROADMAP Stage 5): split
`src/research_match_server.py` into modules under 256 KiB, and trim `uv.lock` by making the
heavy embedding stack an optional extra.

## 3. Before you open the portal

```bash
# from the parent folder of the checkout
claude plugin validate ./ResearchMatch --strict
# try it exactly as users will
claude --plugin-dir ./ResearchMatch
```

Then, from inside that session, run each slash command once and call every tool at least
once (the portal asks you to confirm you have). Commit, tag `v3.4.0`, push `main`.

Also check the old Console form queue once: open
[platform.claude.com/plugins/submissions](https://platform.claude.com/plugins/submissions).
If anything for this repository is listed there with a **Withdraw** button, withdraw it;
if it is listed without one, email `directory@anthropic.com` asking to move it to the
developer portal. Otherwise the portal can refuse **Submit for review** with
"Already submitted by another organization". (The February 2026 submission went through
the MCPB Google Form, not the Console form, so most likely nothing is listed.)

## 4. Portal steps (Plugin bundle)

1. **Submit new → Plugin bundle.**
2. **Source**: repository `faustojdb/ResearchMatch`; plugin path empty (plugin is at the
   root); branch `main` (or tag `v3.4.0` to pin). Click **Validate**, fix anything marked
   **Blocking**, re-validate.
3. **Listing details**: read from `plugin.json` and the README — nothing to type.
4. **Data handling** — honest answers:
   - Reads/stores personal data? **Yes**: a SHA-256 hash of the email the user types, a
     pseudonym, and the research descriptions the user chooses to submit. Stored locally
     in SQLite on the user's machine (plugin data directory).
   - Sends data to services other than declared connectors? **Yes**: OpenAlex (search terms
     only), GitHub API (public repo search/metadata), Hugging Face (model download, no user
     data), PyPI (dependencies). All listed in the README.
   - Retention: as long as the local database exists; the user can delete the file.
   - Intended for under-18s? **No.**
5. **Compliance**: contact email `faustojdb@gmail.com`; tick the four acknowledgements.
6. **Review and submit**: keep **GitHub push webhook** (needs admin on the repo), submit.

## 5. Listing copy (ready to paste if the portal asks for it)

**One-liner (≤ 200 chars)** — same as `plugin.json` description:

> Find complementary research collaborators while protecting unpublished work: literature-grounded originality scoring (OpenAlex), bilateral matching, consent-based reveals, git-verifiable contracts.

**Three working example prompts** (the policy asks for at least three):

1. *"Search Research Match for anyone working on quantum error correction."* → `cold_search`, no account.
2. *"Register me on Research Match and help me submit my work on federated learning for healthcare."* → `register` → `analyze_work` → `submit_commit`.
3. *"Analyze https://github.com/owner/repo with Research Match and estimate its originality."* → `deep_search` with `include_scoring=true`.

**Test account for reviewers**: none needed — the server is local and `register` creates a
pseudonymous identity from any email the reviewer types. Suggest `reviewer@example.com`.

## 6. After submission

- Each new commit on the tracked branch is scanned; publish when it passes. Raise
  `version` in `.claude-plugin/plugin.json` (and `pyproject.toml`, `manifest.json`,
  `SERVER_VERSION`) on every release.
- A listed plugin reaches claude.ai, Cowork and Claude Code. The **local MCP server runs
  only in Claude Code and Cowork** (claude.ai web chat loads the skill but does not start
  local servers). Say so in the listing if asked.
- The hosted Cloud Run connector stays out of the directory until it has OAuth 2.0.

## 7. Distribution that works today, without waiting for review

The repository is already a marketplace (`.claude-plugin/marketplace.json`), so anyone can
install right now:

```bash
claude plugin install research-match --marketplace faustojdb/ResearchMatch
```
