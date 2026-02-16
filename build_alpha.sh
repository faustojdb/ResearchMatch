#!/usr/bin/env bash
# build_alpha.sh — Build DXT + Plugin ZIP for Research Match v2.8.0
# Usage: chmod +x build_alpha.sh && ./build_alpha.sh

set -euo pipefail

VERSION="2.8.0"
DXT_NAME="research-match-${VERSION}.dxt"
ZIP_NAME="research-match-plugin-${VERSION}.zip"

echo "=== Research Match Alpha Build v${VERSION} ==="
echo ""

# ── 1. Clean previous artifacts ──────────────────────────────────────
echo "[1/6] Cleaning previous artifacts..."
rm -f "${DXT_NAME}" "${ZIP_NAME}"
rm -rf .build_tmp
echo "  Done."

# ── 2. Validate required files exist ─────────────────────────────────
echo "[2/6] Validating required files..."
REQUIRED_FILES=(
    "manifest.json"
    "pyproject.toml"
    "requirements.txt"
    "src/research_match_server.py"
    "assets/icon.png"
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
echo "  All files present. manifest v${MANIFEST_VERSION}, ${TOOL_COUNT} tools."

# ── 3. Build DXT ─────────────────────────────────────────────────────
echo "[3/6] Building ${DXT_NAME}..."
zip -q "${DXT_NAME}" \
    manifest.json \
    pyproject.toml \
    requirements.txt \
    src/research_match_server.py \
    assets/icon.png
echo "  Done."

# ── 4. Generate plugin temporaries ───────────────────────────────────
echo "[4/6] Generating plugin metadata..."
mkdir -p .build_tmp/.claude-plugin

# Generate .claude-plugin/plugin.json
cat > .build_tmp/.claude-plugin/plugin.json << 'PLUGIN_EOF'
{
  "name": "research-match",
  "version": "2.8.0",
  "description": "MCP server with 24 tools that connects isolated researchers via AI originality scoring, bilateral matching, collaboration contracts, and privacy-first knowledge sharing.",
  "entry_point": "src/research_match_server.py",
  "runtime": "python",
  "min_python_version": "3.12"
}
PLUGIN_EOF

# Generate .mcp.json
cat > .build_tmp/.mcp.json << 'MCP_EOF'
{
  "mcpServers": {
    "research-match": {
      "command": "uv",
      "args": ["--directory", ".", "run", "research-match"],
      "env": {
        "RESEARCH_MATCH_DB": "research_match.db"
      }
    }
  }
}
MCP_EOF

echo "  Done."

# ── 5. Build Plugin ZIP ──────────────────────────────────────────────
echo "[5/6] Building ${ZIP_NAME}..."
zip -q "${ZIP_NAME}" \
    manifest.json \
    pyproject.toml \
    requirements.txt \
    src/research_match_server.py \
    assets/icon.png

# Add plugin metadata from temp dir
(cd .build_tmp && zip -q "../${ZIP_NAME}" \
    .claude-plugin/plugin.json \
    .mcp.json)
echo "  Done."

# ── 6. Cleanup and report ────────────────────────────────────────────
echo "[6/6] Cleaning up temporaries..."
rm -rf .build_tmp

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

echo "Next: Import ${ZIP_NAME} into Claude Desktop for testing."
