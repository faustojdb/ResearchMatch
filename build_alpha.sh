#!/usr/bin/env bash
# build_alpha.sh — Build the MCPB bundle (manual Claude Desktop install) + a plugin ZIP
# Usage: chmod +x build_alpha.sh && ./build_alpha.sh

set -euo pipefail

VERSION="3.4.0"
DXT_NAME="research-match-${VERSION}.mcpb"
ZIP_NAME="research-match-plugin-${VERSION}.zip"

echo "=== Research Match Alpha Build v${VERSION} ==="
echo ""

# ── 1. Clean previous artifacts ──────────────────────────────────────
echo "[1/6] Cleaning previous artifacts..."
rm -f "${DXT_NAME}" "${ZIP_NAME}"
echo "  Done."

# ── 2. Validate required files exist ─────────────────────────────────
echo "[2/6] Validating required files..."
REQUIRED_FILES=(
    "manifest.json"
    "pyproject.toml"
    "requirements.txt"
    "README.md"
    "src/__init__.py"
    "src/research_match_server.py"
    "src/datastore.py"
    "src/firestore_datastore.py"
    "src/firebase_init.py"
    "src/algolia_client.py"
    "src/openalex_client.py"
    "src/github_client.py"
    "assets/icon.png"
    ".python-version"
    "skills/research-match/SKILL.md"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [[ ! -f "$f" ]]; then
        echo "  ERROR: Missing required file: $f"
        exit 1
    fi
done

# Validate manifest version matches
MANIFEST_VERSION=$(python3 -c "import json; print(json.load(open('manifest.json'))['version'])")
if [[ "$MANIFEST_VERSION" != "$VERSION" ]]; then
    echo "  ERROR: manifest.json version ($MANIFEST_VERSION) != expected ($VERSION)"
    exit 1
fi

TOOL_COUNT=$(python3 -c "import json; print(len(json.load(open('manifest.json'))['tools']))")
CMD_COUNT=$(ls -1 commands/*.md 2>/dev/null | wc -l)
if [[ "$CMD_COUNT" -eq 0 ]]; then
    echo "  ERROR: No command files found in commands/"
    exit 1
fi
echo "  All files present. manifest v${MANIFEST_VERSION}, ${TOOL_COUNT} tools, ${CMD_COUNT} commands, 1 skill."

# ── 3. Build DXT ─────────────────────────────────────────────────────
echo "[3/6] Building ${DXT_NAME}..."
zip -q "${DXT_NAME}" \
    manifest.json \
    pyproject.toml \
    requirements.txt \
    README.md \
    src/__init__.py \
    src/research_match_server.py \
    src/datastore.py \
    src/firestore_datastore.py \
    src/firebase_init.py \
    src/algolia_client.py \
    src/openalex_client.py \
    src/github_client.py \
    assets/icon.png \
    .python-version \
    LICENSE \
    uv.lock
echo "  Done."

# ── 4. Plugin metadata ───────────────────────────────────────────────
# The ZIP ships the SAME .claude-plugin/plugin.json and .mcp.json that the git
# repository uses (no generated copies that can drift). uv.lock is included so
# `uv run --frozen` in .mcp.json resolves reproducibly.
echo "[4/6] Checking plugin metadata..."
for f in .claude-plugin/plugin.json .mcp.json uv.lock LICENSE analyze_repo.py; do
    if [[ ! -f "$f" ]]; then
        echo "  ERROR: Missing required file: $f"
        exit 1
    fi
done
PLUGIN_VERSION=$(python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])")
if [[ "$PLUGIN_VERSION" != "$VERSION" ]]; then
    echo "  ERROR: .claude-plugin/plugin.json version ($PLUGIN_VERSION) != expected ($VERSION)"
    exit 1
fi
echo "  Done."

# ── 5. Build Plugin ZIP ──────────────────────────────────────────────
echo "[5/6] Building ${ZIP_NAME}..."
zip -q "${ZIP_NAME}" \
    manifest.json \
    pyproject.toml \
    requirements.txt \
    README.md \
    src/__init__.py \
    src/research_match_server.py \
    src/datastore.py \
    src/firestore_datastore.py \
    src/firebase_init.py \
    src/algolia_client.py \
    src/openalex_client.py \
    src/github_client.py \
    assets/icon.png \
    .python-version \
    LICENSE \
    uv.lock \
    analyze_repo.py \
    commands/*.md \
    skills/research-match/SKILL.md \
    .claude-plugin/plugin.json \
    .mcp.json
echo "  Done."

# ── 6. Cleanup and report ────────────────────────────────────────────
echo "[6/6] Reporting..."

echo ""
echo "=== Build Complete ==="
echo ""

# File sizes
DXT_SIZE=$(du -h "${DXT_NAME}" | cut -f1)
ZIP_SIZE=$(du -h "${ZIP_NAME}" | cut -f1)
echo "Artifacts:"
echo "  ${DXT_NAME}  (${DXT_SIZE})"
echo "  ${ZIP_NAME}  (${ZIP_SIZE})"
echo ""

# DXT contents
echo "--- ${DXT_NAME} contents ---"
unzip -l "${DXT_NAME}"
echo ""

# ZIP contents
echo "--- ${ZIP_NAME} contents ---"
unzip -l "${ZIP_NAME}"
echo ""

echo "Next: unzip ${ZIP_NAME} and load it with: claude --plugin-dir <folder>"
