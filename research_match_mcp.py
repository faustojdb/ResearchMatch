"""Research Match — plugin entry point.

`.mcp.json` starts the local MCP server with

    uv --directory ${CLAUDE_PLUGIN_ROOT} run --frozen python ${CLAUDE_PLUGIN_ROOT}/research_match_mcp.py

so that the command names a readable file shipped in the plugin. The server itself lives
in the `src` package (it uses package-relative imports, so it cannot be run as a bare
file); this launcher only delegates to its `main()`.
"""
from src.research_match_server import main

if __name__ == "__main__":
    main()
