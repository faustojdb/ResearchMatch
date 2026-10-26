"""
Guardrails for the packaging files: the plugin's `.mcp.json`, the desktop-extension
`manifest.json`, `pyproject.toml` and the version strings that must agree.

These files are what hosts read before any Python runs, so a mistake in them shows up as
"failed to connect" with no traceback. Each check here corresponds to a failure that was
seen in the wild:

- the environment must live outside the plugin folder (Claude Desktop's Microsoft Store
  build virtualizes its plugin folders and uv cannot write launchers there);
- uv must not install the project itself (that launcher write was the failing step, and it
  cost ~15 s per start);
- both launch commands must run the shipped `research_match_mcp.py`, not a console script
  that no longer exists once the project is not installed;
- every file that states the version must state the same one.

Run standalone with:
    pytest tests/test_packaging.py -q
"""

from __future__ import annotations

import json
import os
import re
import tomllib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(path: str) -> str:
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def pyproject():
    return tomllib.loads(_read("pyproject.toml"))


@pytest.fixture(scope="module")
def mcp_json():
    return json.loads(_read(".mcp.json"))["mcpServers"]["research-match"]


@pytest.fixture(scope="module")
def manifest():
    return json.loads(_read("manifest.json"))


# =====================================================================
# Versions agree everywhere
# =====================================================================

def test_version_is_the_same_in_every_file(pyproject, manifest):
    version = pyproject["project"]["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert manifest["version"] == version
    assert json.loads(_read(".claude-plugin/plugin.json"))["version"] == version
    marketplace = json.loads(_read(".claude-plugin/marketplace.json"))
    assert [p["version"] for p in marketplace["plugins"] if p["name"] == "research-match"] == [version]
    assert re.search(r'^SERVER_VERSION = "([^"]+)"', _read("src/research_match_server.py"), re.M).group(1) == version
    assert f'"server_version": "{version}"' in _read("README.md")
    lock = _read("uv.lock")
    assert f'name = "research-match"\nversion = "{version}"' in lock


# =====================================================================
# Plugin: .mcp.json
# =====================================================================

def test_plugin_runs_the_shipped_launcher_with_the_lockfile(mcp_json):
    assert mcp_json["command"] == "uv"
    args = mcp_json["args"]
    assert "--frozen" in args
    assert args[args.index("--directory") + 1] == "${CLAUDE_PLUGIN_ROOT}"
    assert args[-2:] == ["python", "${CLAUDE_PLUGIN_ROOT}/research_match_mcp.py"]


def test_plugin_environment_and_database_live_outside_the_plugin_folder(mcp_json):
    env = mcp_json["env"]
    assert env["UV_PROJECT_ENVIRONMENT"] == "${CLAUDE_PLUGIN_DATA}/venv"
    assert env["UV_CACHE_DIR"] == "${CLAUDE_PLUGIN_DATA}/uv-cache"
    assert env["RESEARCH_MATCH_DB"] == "${CLAUDE_PLUGIN_DATA}/research_match.db"
    assert not any("${CLAUDE_PLUGIN_ROOT}" in v for v in env.values())


# =====================================================================
# Desktop extension: manifest.json
# =====================================================================

def test_extension_runs_the_shipped_launcher(manifest):
    cfg = manifest["server"]["mcp_config"]
    assert cfg["command"] == "uv"
    assert "--frozen" in cfg["args"]
    assert cfg["args"][cfg["args"].index("--directory") + 1] == "${__dirname}"
    assert cfg["args"][-2:] == ["python", "research_match_mcp.py"]
    assert "research-match" not in cfg["args"], "the console script is not installed any more"


def test_extension_environment_lives_under_home(manifest):
    env = manifest["server"]["mcp_config"]["env"]
    assert env["UV_PROJECT_ENVIRONMENT"].startswith("${HOME}/")
    assert env["UV_CACHE_DIR"].startswith("${HOME}/")
    assert env["RESEARCH_MATCH_DB_DEFAULT"].startswith("${HOME}/")


# =====================================================================
# pyproject.toml and the launcher
# =====================================================================

def test_uv_never_installs_the_project(pyproject):
    assert pyproject["tool"]["uv"]["package"] is False


def test_launcher_delegates_to_the_server_main():
    src = _read("research_match_mcp.py")
    assert "from src.research_match_server import main" in src
    assert "main()" in src


def test_mcp_dependency_is_pinned_below_2(pyproject):
    deps = [d for d in pyproject["project"]["dependencies"] if d.startswith("mcp")]
    assert deps and all("<2" in d for d in deps)
