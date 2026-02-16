"""Tests for Deep Repository Analysis Tool (NEED-06).

Tests cover: DeepSearchInput Pydantic validation, helper functions
(_import_analyze_repo, _deep_search_clone, _deep_search_check_size,
_deep_search_sanitize_report), and integration tests with mocked clone.
"""
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from research_match_server import (
    DeepSearchInput,
    _import_analyze_repo,
    _deep_search_clone,
    _deep_search_check_size,
    _deep_search_sanitize_report,
    DEEP_SEARCH_CLONE_TIMEOUT,
    DEEP_SEARCH_MAX_REPO_SIZE_MB,
)


# ============================================================
# TestDeepSearchPydantic — Pydantic model validation
# ============================================================

class TestDeepSearchPydantic:
    """Tests for DeepSearchInput Pydantic model."""

    def test_valid_url(self):
        """Accept a standard GitHub URL."""
        inp = DeepSearchInput(repo_url="https://github.com/owner/repo")
        assert inp.repo_url == "https://github.com/owner/repo"

    def test_trailing_slash_stripped(self):
        """Trailing slash should be removed."""
        inp = DeepSearchInput(repo_url="https://github.com/owner/repo/")
        assert inp.repo_url == "https://github.com/owner/repo"

    def test_git_suffix_stripped(self):
        """.git suffix should be removed."""
        inp = DeepSearchInput(repo_url="https://github.com/owner/repo.git")
        assert inp.repo_url == "https://github.com/owner/repo"

    def test_non_github_rejected(self):
        """Non-GitHub URLs should be rejected."""
        with pytest.raises(Exception):
            DeepSearchInput(repo_url="https://gitlab.com/owner/repo")

    def test_no_repo_path_rejected(self):
        """URLs without owner/repo should be rejected."""
        with pytest.raises(Exception):
            DeepSearchInput(repo_url="https://github.com/owner")

    def test_defaults_correct(self):
        """Default values for optional fields."""
        inp = DeepSearchInput(repo_url="https://github.com/owner/repo")
        assert inp.include_mcp_analysis is True
        assert inp.include_comparison is True
        assert inp.include_scoring is False

    def test_extra_fields_rejected(self):
        """Extra fields should be rejected (extra='forbid')."""
        with pytest.raises(Exception):
            DeepSearchInput(
                repo_url="https://github.com/owner/repo",
                unknown_field="bad"
            )


# ============================================================
# TestDeepSearchHelpers — Helper function tests
# ============================================================

class TestDeepSearchHelpers:
    """Tests for deep search helper functions."""

    def test_sanitize_replaces_path(self):
        """_deep_search_sanitize_report replaces repo.path with URL."""
        report = {
            "repo": {"path": "/tmp/rm_deep_abc123/repo", "name": "test"},
            "files": {"largest_files": []},
        }
        result = _deep_search_sanitize_report(report, "https://github.com/a/b")
        assert result["repo"]["path"] == "https://github.com/a/b"

    def test_sanitize_empty_dict(self):
        """Sanitize handles empty report dict without error."""
        result = _deep_search_sanitize_report({}, "https://github.com/a/b")
        assert result == {}

    def test_sanitize_largest_files(self):
        """Sanitize strips absolute paths from largest_files."""
        report = {
            "repo": {"path": "/tmp/rm_deep_x/repo"},
            "files": {
                "largest_files": [
                    ["/tmp/rm_deep_x/repo/src/main.py", 5000],
                    ["/tmp/rm_deep_x/repo/README.md", 1000],
                ]
            },
        }
        result = _deep_search_sanitize_report(report, "https://github.com/a/b")
        for entry in result["files"]["largest_files"]:
            assert not entry[0].startswith("/tmp")

    def test_import_analyze_repo_returns_functions(self):
        """_import_analyze_repo should return a dict of callable functions."""
        funcs = _import_analyze_repo()
        expected_keys = [
            "analyze_git", "analyze_readme", "analyze_file_tree",
            "analyze_dependencies", "analyze_mcp", "compare_tool_lists",
            "map_repo_to_commit_data", "score_originality", "asdict",
            "AnalysisReport",
        ]
        for key in expected_keys:
            assert key in funcs, f"Missing key: {key}"
        # All except AnalysisReport should be callable
        for key in expected_keys:
            if key != "AnalysisReport":
                assert callable(funcs[key]), f"{key} is not callable"

    def test_check_size_returns_none_on_failure(self):
        """_deep_search_check_size returns None when API fails."""
        with patch("research_match_server.urllib.request.urlopen", side_effect=Exception("fail")):
            result = _deep_search_check_size("https://github.com/nonexist/repo")
            assert result is None


# ============================================================
# TestDeepSearchIntegration — Integration tests (mocked clone)
# ============================================================

class TestDeepSearchIntegration:
    """Integration tests for deep search with mocked subprocess."""

    def test_analysis_on_own_repo(self):
        """Run analysis on our own repo (without cloning)."""
        funcs = _import_analyze_repo()
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Layer 1
        report = funcs["AnalysisReport"]()
        report.repo = funcs["analyze_git"](repo_root)
        title, desc = funcs["analyze_readme"](repo_root)
        report.repo.readme_title = title
        report.repo.readme_description = desc
        report.files = funcs["analyze_file_tree"](repo_root)
        report.deps = funcs["analyze_dependencies"](repo_root)

        assert report.repo.git_exists is True
        assert report.files.total_files > 0
        assert "Python" in report.files.loc_by_language or "py" in str(report.files.files_by_extension)

        # Layer 2
        report.mcp = funcs["analyze_mcp"](repo_root, report.deps)
        assert report.mcp.tool_count > 0

        # Serialize
        report_dict = funcs["asdict"](report)
        sanitized = _deep_search_sanitize_report(report_dict, "https://github.com/test/repo")
        assert sanitized["repo"]["path"] == "https://github.com/test/repo"

    def test_clone_timeout_raises_error(self):
        """Clone timeout should raise RuntimeError."""
        import subprocess as sp
        with patch("research_match_server.subprocess.run", side_effect=sp.TimeoutExpired(cmd="git clone", timeout=60)):
            with pytest.raises(RuntimeError, match="timed out"):
                _deep_search_clone("https://github.com/a/b", "/tmp/test")

    def test_clone_failure_raises_error(self):
        """Clone returning non-zero exit should raise RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stderr = "fatal: repository not found"
        with patch("research_match_server.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="repository not found"):
                _deep_search_clone("https://github.com/a/b", "/tmp/test")

    def test_repo_too_large_check(self):
        """Check that size check returns KB value correctly."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"size": 512000}).encode()

        with patch("research_match_server.urllib.request.urlopen", return_value=mock_resp):
            result = _deep_search_check_size("https://github.com/owner/repo")
            assert result == 512000  # 512000 KB = 500 MB


# ============================================================
# TestDeepSearchConstants — Constant validation
# ============================================================

class TestDeepSearchConstants:
    """Tests for deep search constants."""

    def test_clone_timeout_positive(self):
        assert DEEP_SEARCH_CLONE_TIMEOUT > 0

    def test_max_repo_size_reasonable(self):
        assert 100 <= DEEP_SEARCH_MAX_REPO_SIZE_MB <= 2000
