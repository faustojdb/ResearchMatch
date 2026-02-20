# Research Match — Marketplace Submission Answers

**Form URL**: https://forms.gle/tyiAZvch1kDADKoP9
**Date**: 2026-02-20
**Bundle**: `research-match-3.2.0.mcpb` (100.6kB, 14 files)

---

## Extension Name
```
research-match
```

## Version
```
3.2.0
```

## Brief Description (1-2 sentences)
```
MCP server with 27 tools that connects isolated researchers via AI originality scoring and bilateral matching. Helps researchers find complementary collaborators while protecting intellectual property through pseudonymous identities, progressive disclosure, and git-verifiable contracts.
```

## Long Description / What does it do?
```
Research Match is an MCP server for Claude Desktop that helps researchers, scientists, developers, and independent theorists find complementary collaborators while protecting intellectual property.

Core capabilities:
- AI-powered dual-axis originality scoring (Theoretical Originality + Formal-Computational Originality) with solidity multipliers
- Bilateral matching with a semaphore system (GREEN/YELLOW/RED) showing each researcher what they gain from a potential collaboration
- Privacy by design: emails are SHA-256 hashed (never stored in plain text), pseudonymous identities, consent-based progressive disclosure
- Full collaboration lifecycle: tickets, reveal system, automatic licensing, file sharing registry, git-verifiable contracts
- GitHub App integration for automatic bilateral read-only repo access on contract confirmation
- Cold search and deep repository analysis — no registration required
- Built-in bug reporting for beta feedback

The server runs locally via UV (Python package manager) with SQLite storage. No external accounts or API keys required for core functionality.
```

## Author Name
```
Fausto Jose Di Bacco
```

## Author URL / GitHub
```
https://github.com/faustojdb
```

## Repository URL
```
https://github.com/faustojdb/ResearchMatch
```

## Homepage URL
```
https://github.com/faustojdb/ResearchMatch
```

## Contact Email
```
faustojdb@users.noreply.github.com
```

## Support Channel
```
GitHub Issues: https://github.com/faustojdb/ResearchMatch/issues
Built-in: Users can use the report_bug tool directly from Claude Desktop
```

## Privacy Policy URL
```
https://github.com/faustojdb/ResearchMatch/blob/main/PRIVACY_POLICY.md
```

## License
```
Business Source License 1.1 (BSL-1.1)
Non-commercial use only. Changes to Apache 2.0 on February 18, 2031.
```

## Number of Tools
```
27
```

## List of Tools (with annotations)
```
1. register — readOnly:false, destructive:false, idempotent:true
2. analyze_work — readOnly:true, destructive:false, idempotent:true
3. submit_commit — readOnly:false, destructive:false, idempotent:false
4. my_profile — readOnly:true, destructive:false, idempotent:true
5. find_collaborators — readOnly:true, destructive:false, idempotent:true
6. send_request — readOnly:false, destructive:false, idempotent:false
7. inbox — readOnly:true, destructive:false, idempotent:true
8. respond_request — readOnly:false, destructive:false, idempotent:false
9. rate_user — readOnly:false, destructive:false, idempotent:false
10. cold_search — readOnly:true, destructive:false, idempotent:true
11. deep_search — readOnly:true, destructive:false, idempotent:true
12. prepare_commit — readOnly:true, destructive:false, idempotent:true
13. needs_create — readOnly:false, destructive:false, idempotent:false
14. needs_list — readOnly:true, destructive:false, idempotent:true
15. needs_resolve — readOnly:false, destructive:false, idempotent:false
16. reveal_request — readOnly:false, destructive:false, idempotent:false
17. reveal_respond — readOnly:false, destructive:false, idempotent:false
18. reveal_status — readOnly:true, destructive:false, idempotent:true
19. team_license — readOnly:true, destructive:false, idempotent:true
20. share_file — readOnly:false, destructive:false, idempotent:false
21. shared_files — readOnly:true, destructive:false, idempotent:true
22. audit_log — readOnly:true, destructive:false, idempotent:true
23. export_contract — readOnly:false, destructive:false, idempotent:false
24. confirm_contract — readOnly:false, destructive:false, idempotent:false
25. connect_github — readOnly:false, destructive:false, idempotent:false
26. disconnect_github — readOnly:false, destructive:true, idempotent:false
27. report_bug — readOnly:false, destructive:false, idempotent:false
```

## Example 1: Register and Submit Research
```
User prompt: "Register me on Research Match with my email researcher@university.edu, then help me submit my work on federated learning for healthcare."

What happens:
1. Claude calls register (email is SHA-256 hashed, never stored in plain text)
2. Claude calls analyze_work to get the Research Commit template
3. Claude helps fill in structured fields (domain, hypothesis, methodology, solidity)
4. Claude calls submit_commit — AI evaluates originality

Expected output from submit_commit:
{
  "status": "submitted",
  "version": 1,
  "scores": {
    "ot_score": 72.5,
    "ofc_score": 65.8,
    "overall_solidity": "functional"
  },
  "next_step": "Use find_collaborators to discover complementary researchers"
}
```

## Example 2: Free Cold Search (No Registration)
```
User prompt: "Search Research Match for anyone working on quantum error correction."

What happens: Claude calls cold_search with keywords ["quantum", "error", "correction"]. No registration required.

Expected output from cold_search:
{
  "query": "quantum error correction",
  "results": [
    {
      "pseudonym": "QuantumCat-7x",
      "domain": "quantum computing",
      "subdomain": "error correction",
      "hypothesis": "Surface codes with adaptive decoders reduce logical error rates by 40%",
      "ot_score": 78.2,
      "ofc_score": 81.5
    }
  ],
  "total_results": 1,
  "source": "algolia"
}
```

## Example 3: Report a Bug (No Registration Required)
```
User prompt: "The cold_search tool returned an empty result when I searched for 'machine learning'. Can you report this bug?"

What happens: Claude calls report_bug with error details. Works without registration.

Expected output from report_bug:
{
  "status": "reported",
  "report_id": "a1b2c3d4-...",
  "severity": "medium",
  "server_version": "3.2.0",
  "reporter": "anonymous",
  "message": "Bug report received (severity: medium). Report ID: a1b2c3d4-.... Thank you for helping improve Research Match!"
}
```

## Testing Credentials
```
No external API keys or accounts are required for core functionality. The MCPB bundle runs locally with SQLite storage via UV (Python package manager).

To test:
1. Install the .mcpb bundle in Claude Desktop
2. Say "Register me on Research Match" — Claude will guide through the flow
3. All 27 tools work out of the box with local SQLite storage

Optional features (not required for testing):
- Algolia (cold_search full-text) — falls back to Firestore/SQLite keyword matching
- GitHub App (connect_github) — gracefully degrades if not configured
```

## Runtime / Platform
```
Type: UV (Python)
Python: >=3.12
Platforms: Windows, macOS, Linux
Dependencies managed by UV automatically from pyproject.toml
```

## Keywords / Categories
```
research, collaboration, matching, originality, mcp, ai, contracts, licensing, privacy, academic
```

## Manifest Version
```
0.4
```

## Additional Notes
```
Research Match is in beta. The built-in report_bug tool (Tool #27) allows any user — even unregistered — to report issues directly from Claude Desktop. This was specifically designed to gather beta feedback before GA release.

The server uses sentence-transformers (all-MiniLM-L6-v2) for semantic embeddings. First run downloads the model (~90MB) which takes 1-2 minutes. Subsequent runs are instant.
```

---

## Pre-Submission Checklist ✓

- [x] All 27 tools have readOnlyHint AND destructiveHint annotations
- [x] All 27 tools have title annotation
- [x] Privacy policy in README.md (section + link)
- [x] privacy_policies array in manifest.json
- [x] manifest_version 0.4 (≥0.3 required)
- [x] 3 working examples with prompts and expected outputs
- [x] README.md has all required sections (Description, Features, Installation, Configuration, Examples, Privacy Policy, Support)
- [x] LICENSE file included (BSL-1.1)
- [x] Icon included (512×512 recommended, current: 3.4kB PNG)
- [x] Bundle validated: mcpb validate ✓
- [x] Bundle packed: research-match-3.2.0.mcpb (100.6kB)
- [x] 101 tests passing (Firestore emulator)
