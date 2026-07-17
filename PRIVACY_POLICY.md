# Privacy Policy — Research Match

**Effective Date**: February 20, 2026
**Last Updated**: February 20, 2026

## Overview

Research Match is an MCP server that connects researchers via literature-grounded originality scoring and bilateral matching. This privacy policy explains how we collect, use, and protect your data.

## Data We Collect

### Registration Data
- **Email address**: Immediately SHA-256 hashed on the server. The application stores **only the SHA-256 hash** — the plain-text email is not written to the app's database. Note that hosting infrastructure (e.g., Google Cloud) may log request metadata such as IP addresses outside the application's control. In local-first mode, all data stays on your machine and nothing is transmitted. Only the irreversible hash is retained for identity purposes.
- **Pseudonym**: A display name you choose (or auto-generated). This is the only human-readable identifier visible to other users.

### Research Commits
- Structured descriptions of your research work (domain, hypothesis, methodology).
- Literature-grounded originality scores (Theoretical Originality and Formal-Computational Originality).
- These are stored to enable matching and collaboration features.

### Collaboration Data
- Collaboration requests, team memberships, ratings, tickets, reveal consents, shared file metadata, and contracts.
- All collaboration data is scoped to bilateral relationships — only team members can access their shared data.

### Bug Reports
- Error descriptions, tool names, severity, and reproduction steps submitted via the `report_bug` tool.
- Reporter identity is captured if registered (user ID only), otherwise stored as "anonymous".
- Server version is captured automatically.

### Technical Data
- Server logs may contain tool invocation timestamps and anonymized error traces.
- No IP addresses, browser fingerprints, or device identifiers are collected by the MCP server.

## Data We Do NOT Collect

- Raw email addresses (only SHA-256 hashes)
- Chat history or conversation content between you and Claude
- File contents (only metadata like file paths and hashes for the sharing registry)
- Payment or financial information
- Location data
- Cookies or tracking identifiers

## How We Use Your Data

- **Matching**: Research commits are compared using semantic (sentence) embeddings to find complementary collaborators.
- **Scoring**: Originality scores are computed from your structured research descriptions.
- **Collaboration**: Team data enables bilateral workflows (reveal, licensing, contracts).
- **Bug tracking**: Bug reports help us improve the service during beta testing.
- **No advertising**: Your data is never used for advertising, marketing, or sold to third parties.

## Data Storage and Security

- **Production database**: Google Cloud Firestore (us-central1 region), encrypted at rest and in transit.
- **Search index**: Algolia (for cold_search full-text search on research commits only — domain, subdomain, hypothesis fields).
- **Local mode**: SQLite database stored locally on your machine (no cloud transmission).
- **Access control**: Firestore security rules deny all client-side access. Data is only accessible through the server's Admin SDK.

## Data Sharing

- **With other users**: Only pseudonyms and originality scores are visible to potential collaborators. Full research commit content is only shared after bilateral consent (Level 3 reveal system).
- **With third parties**: We do not sell, rent, or share your data with third parties.
- **GitHub integration**: If you connect your GitHub account, your GitHub username and authorized repository list are stored to enable bilateral read-only repo access. This is revocable via `disconnect_github`.

## Data Retention

- Your data is retained as long as your account exists.
- Bug reports are retained indefinitely for service improvement.
- There is currently no automated account deletion tool. To request data deletion, contact us (see below).

## Your Rights

- **Access**: Use the `my_profile` tool to view all data associated with your account.
- **Portability**: Use `export_contract` to export your collaboration data.
- **Deletion**: Contact us to request account and data deletion.
- **Correction**: Re-submit research commits to update your data.

## Children's Privacy

Research Match is designed for researchers, scientists, and developers. We do not knowingly collect data from children under 13.

## Changes to This Policy

We may update this policy as the service evolves. Material changes will be noted in the changelog and README.

## Contact

- **Developer**: Fausto Jose Di Bacco
- **GitHub**: [github.com/faustojdb](https://github.com/faustojdb)
- **Issues**: [github.com/faustojdb/ResearchMatch/issues](https://github.com/faustojdb/ResearchMatch/issues)
- **Email**: faustojdb@gmail.com
