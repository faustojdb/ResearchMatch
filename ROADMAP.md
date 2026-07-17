# Roadmap

Research Match is a two-sided network. Code alone cannot make it useful — it needs
real, honest research descriptions from real researchers. This document explains why
registering is a genuine contribution (not just "signing up"), and what happens next
as real usage grows. Stages are triggered by real signals, not calendar dates.

## Why registering your project matters — concretely, not as a slogan

When you run `register` + `submit_commit`, you are not just creating an account. You
are writing a row into `research_commits` with your domain, subdomain, problem,
hypothesis, theoretical framework, and declared demonstrations (see `SubmitCommitInput`
in `src/research_match_server.py`). That row does two specific things for *other*
people the moment it exists:

1. **It becomes matching inventory.** `find_collaborators` looks up candidates by
   querying `research_commits` in your domain (`_get_corpus_async` /
   `get_corpus_commits`). Right now, for almost every domain, that query returns
   nothing — there is no one to match with yet. Every real commit submitted is one
   more person the *next* researcher in that field can actually be matched against.
2. **It becomes novelty reference material.** Originality scoring grounds novelty
   against real published literature via OpenAlex (see `src/openalex_client.py`), but
   it *also* compares against other registered commits in the same domain
   (`_build_novelty_context`). A thin corpus means everyone's "how novel is this
   compared to the community" signal is weak. A real corpus makes that signal mean
   something.

**Important honesty note:** value today is asymmetric. The OpenAlex-grounded novelty
score for *your own* submission is real and useful from the moment you submit it,
independent of anyone else — that part doesn't need a network effect. What *does* need
real registrations is `find_collaborators` and the peer-comparison half of scoring.
Don't submit a placeholder to "help the corpus" — a fake or padded commit pollutes the
exact signal this depends on. The honesty-rated reputation system exists precisely to
make truthful, modest self-assessment the winning strategy over inflation.

## Roadmap stages (trigger-based, not dated)

### Stage 0 — Today (v3.3.0): local-first, single-player value
**Status: shipped.** `deep_search` and `submit_commit` work with zero other
registered users — novelty is grounded in real literature via OpenAlex, and the
result is honest even with an empty local corpus (a neutral, clearly-labelled score
instead of a fabricated number). This is deliberate: the product must give you a
reason to try it before it can ask you to seed it.

### Stage 1 — First real cohort
**Trigger:** a handful of genuine (non-test) commits registered across a few domains.
**Unlocks:** `find_collaborators` starts returning real candidates instead of empty
results; intra-corpus novelty grounding activates alongside OpenAlex.
**Known engineering debt to fix before/as this happens:** the matching-gain formula
(`_calculate_gain`, `src/research_match_server.py`) computes gain from the *positive
difference* between two profiles' scores (`max(0, their_score - my_score)`). Two
researchers with **equally strong, similar profiles** produce a difference near zero on
both sides, which the semaphore (`_calculate_semaphore`) currently reads as low mutual
benefit — falling through to RED instead of recognizing a strong peer match. Early
adopters are disproportionately likely to be exactly this kind of strong, similar
profile, so this needs fixing before real trust is on the line — not after someone gets
a RED against an obviously great match and writes the product off.

### Stage 2 — Search needs real ranking
**Trigger:** `cold_search` on common queries returns enough results that plain keyword
matching (`LIKE` over Firestore/SQLite) produces noisy or irrelevant results, or users
explicitly ask for better search.
**Unlocks:** recreate an Algolia application (the original one, `1TAPVC99Z1`, was
deleted for inactivity — see `SECURITY.md`) and re-index, using a **search-only** key
for the read path. Recreating it before there's a real corpus to index is pure
overhead with nothing to show for it, so this is deliberately gated on demand, not on
"getting around to it."

### Stage 3 — First real collaboration
**Trigger:** two real users form a team organically through `send_request` /
`respond_request` — not a staged test account.
**Unlocks/validates:** the full `reveal_request` → `team_license` → `export_contract`
→ `confirm_contract` → `connect_github` (bilateral repo escrow) chain has only ever
been exercised against a manually-created test/ghost user. The first real pair is the
actual end-to-end test. Treat any friction found here as high-priority — it's the core
promise of the "protect IP while collaborating" pitch.

### Stage 4 — Remote backend hardening
**Trigger:** someone wants to use the shared Cloud Run server for non-trivial or
sensitive work, rather than local-first SQLite.
**Required before recommending that:** real authentication (OAuth / verified token) on
the remote endpoint. It is currently explicitly labelled experimental / no
authentication (see `SECURITY.md`) — identity there is a self-asserted email hash, and
must not hold sensitive unpublished research until this lands.

### Stage 5 — Engineering debt, paid down as it starts hurting
No magic trigger number — these become worth doing when they cause visible pain
(latency, contributor friction), not before:
- Finish `SQLiteDataStore` implementing the `DataStore` ABC and delete the ~86
  duplicated dual-backend branches in `src/research_match_server.py`.
- Move Firestore/Algolia calls off the event loop (`asyncio.to_thread` or
  `firestore.AsyncClient`) so concurrent users on Cloud Run stop serializing behind
  each other's I/O.
- Split `research_match_server.py` into modules (engines / models / tools by domain).

## How to contribute right now

1. **Highest leverage, by far: register and submit one real Research Commit.** This
   is the one action that literally seeds the network — nothing else in this list
   works without it.
2. **Form a real collaboration if you find one worth pursuing.** You'd be the first
   real test of Stage 3's full chain — genuinely valuable even (especially) if
   something breaks.
3. **File an issue or PR** against any item above. The matching-gain fix in Stage 1 is
   a well-scoped, self-contained starting point if you want to contribute code.
