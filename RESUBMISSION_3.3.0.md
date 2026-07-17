# Research Match v3.3.0 — Resubmission Guide

This release fixes the concrete blockers that most likely caused the first submission
to go unanswered, and makes the "originality scoring" claim true. Below: what changed,
the **manual steps only you can do**, and copy-paste-ready form answers.

---

## What changed in 3.3.0

**Security (was: account-takeover hole)**
- Identity now **fails closed**: an unidentified request never resolves to another
  user's account. The `get_most_recent_user()` fallback is gone.
- DNS-rebinding protection re-enabled with a Host allow-list on the HTTP transport.
- The remote shared backend is now clearly labelled **experimental / no-auth**; local-first
  (private SQLite) is the recommended mode.

**Honesty (was: "AI-powered" but really word-counts)**
- Novelty is now **grounded in real published literature via OpenAlex** (free, no API
  key): your problem/hypothesis is compared by semantic-embedding similarity against the
  most-related prior works. When no reference exists (offline/niche), it returns an honest
  neutral "unscored" value instead of a fabricated 90.
- Every score records how it was produced (`scoring_version`, `similarity_method`,
  `novelty_grounding`, `reference_works`). OFC is explicitly labelled `self_declared`.
- All docs de-claim "AI evaluates your work"; OT/OFC naming unified everywhere.

**Bug fixes**
- `cold_search` no longer leaks hypothesis text (IP-protection story is now consistent).
- `deep_search` `include_scoring` now actually produces a literature-grounded estimate.
- Fixed the `analyze_repo.py` un-awaited coroutine and the `sqlite3.Row.get()` crash.

**Tests / CI**
- New offline unit tests (engines, auth fail-closed, OpenAlex) — 24 passing with no
  emulator/network. Emulator suite (101) auto-skips when the emulator is down instead of
  hanging. GitHub Actions CI added.

---

## MANUAL STEPS — only you can do these

### 1. Rotate the two live credentials (defense-in-depth before going public)
They were never committed (verified), but rotate them anyway since the repo is about to
become public and the keys sat in the working tree. See `SECURITY.md` for the checklist:
- [x] Firebase service-account key — rotated (new `private_key_id` verified, new key
      confirmed working against production Firestore). Old key must be deleted in
      Google Cloud IAM → Service Accounts → Keys if not already done.
- [x] GitHub App private key — rotated (new `.pem` verified: generates a valid JWT).
      Old key must be deleted in GitHub App settings → Private keys if not already done.
- [x] ~~Algolia admin key~~ — confirmed deleted by Algolia for inactivity (dashboard
      shows only the default "My First Application", app `1TAPVC99Z1` no longer
      resolves). Nothing to rotate; `cold_search` already falls back to keyword
      matching without it. `.env` updated to comment out the dead references.

### 1b. Corrected diagnosis — what we got wrong and right the first time
Checking Gmail directly (2026-07-17) surfaced the actual Google Forms receipt from the
original 2026-02-20 submission. Two corrections to the original root-cause theory:

- **The contact email was NOT the problem.** The real submitted "Primary Contact Email"
  was already **faustojdb@gmail.com** — the `@users.noreply.github.com` address only
  ever existed in a planning doc (`sessions/2026-02-20_submission-answers.md`), never in
  the actual form. Still worth having it consistent everywhere (done), but it wasn't why
  Anthropic never replied.
- **The private repo (404) is still the most likely real blocker** — unchanged, still
  needs fixing (step 2 below).
- **New finding, now resolved:** the form itself (as of Feb 2026) said it "primarily
  considers" MIT-licensed, Node.js-built extensions. Research Match is BSL-1.1 + Python,
  so this looked like a second blocker. Checked the *current* policy
  (https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy,
  which explicitly superseded the older page linked from that Feb form) — it specifies
  **no license requirement** and **no Node.js requirement** (only "reasonably current
  dependencies" for local servers). That February form text reflected an early,
  narrow phase of the directory and is outdated. **No relicensing or rewrite needed.**
  One real, current, hard requirement worth remembering for later: *"Remote MCP servers
  that require authentication must use secure OAuth 2.0 with certificates from
  recognized authorities"* — confirms the remote Cloud Run backend must stay
  experimental/unlabeled-for-sensitive-use until real OAuth 2.0 is implemented (Stage 4
  in `ROADMAP.md`).

### 2. Make the GitHub repo public
This is the single most likely original blocker — the reviewer got 404 on every URL.
```bash
gh repo edit faustojdb/ResearchMatch --visibility public --accept-visibility-change-consequences
```
Then verify in an **incognito window** that these all load (no 404):
- [ ] https://github.com/faustojdb/ResearchMatch
- [ ] https://github.com/faustojdb/ResearchMatch/blob/main/PRIVACY_POLICY.md
- [ ] https://github.com/faustojdb/ResearchMatch/issues

### 3. Contact email
Already correct — the real form submission on 2026-02-20 already used
**faustojdb@gmail.com** (verified from the actual Google Forms receipt in Gmail). This
was never the blocker; it's just now also consistent across every doc in the repo.

### 4. Commit, tag, and push
**Status: commits done** on `release/v3.3.0` (see `git log`). Still to do:
```bash
git push -u origin release/v3.3.0
# open a PR into main, or push main directly if you prefer
git tag v3.3.0 && git push --tags
```

### 5. Enable the secret-guard hook (one-time, per clone)
```bash
git config core.hooksPath .githooks
```

### 6. Resubmit
Bundle to attach: **research-match-3.3.0.mcpb** (built; renamed from `.dxt` to match
what the actual form expects — see the "Real form" section below).
Form: https://forms.gle/tyiAZvch1kDADKoP9 (redirects to the same
"MCPB Desktop Extensions Submission Form" used in Feb 2026 — confirmed via the actual
Gmail receipt of that submission).

---

## The real form (verified from the actual Feb 2026 Gmail receipt)

This is **much shorter** than the field list originally drafted in
`sessions/2026-02-20_submission-answers.md` (that doc appears to have been prepared
for a more detailed process that was never what got submitted). The actual form has
exactly these fields — answers for the v3.3.0 resubmission:

| Field | Answer |
|---|---|
| Is this an update to an existing extension? | **Yes** |
| Primary Contact Name | Fausto Jose Di Bacco |
| Primary Contact Email | faustojdb@gmail.com |
| MCP Server Description (50 words max) | MCP server with 27 tools connecting isolated researchers through originality scoring grounded in real published literature (via OpenAlex) and bilateral matching. Protects IP with pseudonymous identities, progressive disclosure, and git-verifiable contracts including automatic GitHub repo escrow. Local-first — private SQLite, no API key, works offline. *(45 words)* |
| Desktop Extension GitHub Link | https://github.com/faustojdb/ResearchMatch |
| Primary Party Confirmation (do you work for the company this connects to?) | No |
| Attach your .mcpb file | `research-match-3.3.0.mcpb` |
| Agree to MCP Directory Terms & Conditions | ✓ (read them first: https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy) |
| Optional feedback | Leave blank, or note the v2.3.0 form's stated "MIT/Node.js" preference appears outdated vs. the current consolidated policy — flagging in case that's worth a docs update on Anthropic's side. |

**What we verified about current policy** (so you don't second-guess this later): the
Feb 2026 form text said extensions were "primarily" MIT-licensed and Node.js-built.
The *current* consolidated policy
(https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy)
has **no license requirement** and **no Node.js requirement** — that Feb-2026 framing
was from an early, narrow phase of the directory. BSL-1.1 + Python are fine. The one
hard, current, and relevant requirement: remote MCP servers needing auth **must** use
OAuth 2.0 with a recognized-authority certificate — this is why the Cloud Run backend
stays labelled experimental/no-auth rather than being submitted as the primary mode.

---

## Suggested commit message
```
release: v3.3.0 — fail-closed auth, literature-grounded scoring (OpenAlex), honest docs

- security: remove get_most_recent_user fallback; identity fails closed; re-enable
  DNS-rebinding protection with Host allow-list; label remote mode experimental/no-auth
- scoring: ground novelty in real literature via OpenAlex (free, no key); honest neutral
  when no reference; record scoring method/version; OFC labelled self-declared
- fix: cold_search no longer returns hypothesis text; deep_search include_scoring works;
  analyze_repo await bug; sqlite3.Row.get crash
- docs: drop false "AI evaluates" claims; unify OT/OFC naming; fix fabricated example;
  affirmative BSL Additional Use Grant; local-first README; real contact email
- tests/ci: offline engine+auth+openalex unit tests; emulator auto-skip; GitHub Actions
- hygiene: .env.example, SECURITY.md, pre-commit secret guard; remove stale artifacts
```
