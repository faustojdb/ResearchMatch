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

### 1. Rotate the three credentials (defense-in-depth before going public)
They were never committed (verified), but rotate them anyway since the repo is about to
become public and the keys sat in the working tree. See `SECURITY.md` for the checklist:
- [ ] Firebase service-account key (Google Cloud IAM → Service Accounts → Keys)
- [ ] GitHub App private key (GitHub App settings → regenerate)
- [ ] Algolia admin key (Algolia dashboard) — and issue a search-only key for read paths

### 2. Make the GitHub repo public
This is the single most likely original blocker — the reviewer got 404 on every URL.
```bash
gh repo edit faustojdb/ResearchMatch --visibility public --accept-visibility-change-consequences
```
Then verify in an **incognito window** that these all load (no 404):
- [ ] https://github.com/faustojdb/ResearchMatch
- [ ] https://github.com/faustojdb/ResearchMatch/blob/main/PRIVACY_POLICY.md
- [ ] https://github.com/faustojdb/ResearchMatch/issues

### 3. Use a deliverable contact email
Already changed in-repo to **faustojdb@gmail.com**. Use that on the submission form —
the old `@users.noreply.github.com` bounces (this is why "nunca contestaron").

### 4. Commit, tag, and push
```bash
git checkout -b release/v3.3.0
git add -A
git commit   # message suggested below
git push -u origin release/v3.3.0
# open a PR into main, or push main directly if you prefer
git tag v3.3.0 && git push --tags
```

### 5. Enable the secret-guard hook (one-time, per clone)
```bash
git config core.hooksPath .githooks
```

### 6. Resubmit
Bundle to attach: **research-match-3.3.0.dxt** (built, includes the new modules).
Form: https://forms.gle/tyiAZvch1kDADKoP9 — answers below.

---

## Form answers (copy-paste)

**Extension name:** `research-match`
**Version:** `3.3.0`
**Brief description:**
> MCP server with 27 tools that connects isolated researchers via literature-grounded
> originality scoring and bilateral matching. Runs local-first (private SQLite, no API
> key); novelty is scored against real published works via OpenAlex.

**Author:** Fausto Jose Di Bacco — https://github.com/faustojdb
**Repository / Homepage:** https://github.com/faustojdb/ResearchMatch
**Contact email:** faustojdb@gmail.com
**Support:** GitHub Issues + built-in `report_bug` tool
**Privacy policy:** https://github.com/faustojdb/ResearchMatch/blob/main/PRIVACY_POLICY.md
**License:** Business Source License 1.1 (non-commercial; marketplace distribution granted; → Apache-2.0 on 2031-02-18)
**Number of tools:** 27
**Runtime:** uv (Python ≥3.12), manifest v0.4, platforms Windows/macOS/Linux

**How to test (reviewer):**
> Install research-match-3.3.0.dxt. Say "Register me on Research Match", then submit a
> short research description — originality is scored with novelty grounded in real
> OpenAlex literature (first run downloads a ~90MB embedding model; offline it returns an
> honest neutral score). `cold_search` and `deep_search` work with no registration. All
> data stays local (SQLite); no external accounts or API keys required.

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
