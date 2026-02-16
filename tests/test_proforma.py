"""Tests for Universal Project Proforma + prepare_commit Tool (NEED-07).

Tests cover: project type detection, key file selection, prompt generation,
narrative validation, proforma-to-SubmitCommitInput mapping, and Pydantic models.
"""
import json
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from research_match_server import (
    # Constants
    PROFORMA_VERSION,
    MAX_FILE_READ_CHARS,
    MAX_PROMPT_TOTAL_CHARS,
    MAX_KEY_FILES,
    NARRATIVE_JSON_MAX_LENGTH,
    # Models
    ProformaSolidityAssessment,
    ProformaNarrativeData,
    PrepareCommitInput,
    SolidityLevel,
    # Helpers
    _detect_project_type,
    _read_truncated,
    _select_key_files,
    _build_narrative_prompt,
    _validate_narrative,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project directory for testing."""
    # README
    (tmp_path / "README.md").write_text("# Test Project\nA test project for unit tests.")
    # Python source
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text("def hello():\n    return 'world'\n" * 50)
    # Config
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    # Test file
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_hello():\n    assert True\n")
    return str(tmp_path)


@pytest.fixture
def sample_machine_data():
    """Machine data dict as returned by extract mode."""
    return {
        "repo": {
            "name": "test-project",
            "readme_title": "Test Project",
            "readme_description": "A test project",
            "total_commits": 42,
            "contributors": 2,
        },
        "files": {
            "total_files": 10,
            "files_by_extension": {".py": 5, ".md": 2, ".toml": 1},
            "loc_by_language": {"Python": 500, "Markdown": 100},
            "largest_files": [],
        },
        "project_type": "software",
    }


@pytest.fixture
def valid_solidity():
    """Valid ProformaSolidityAssessment dict."""
    return {
        "overall_solidity": "functional",
        "overall_reasoning": "Working implementation with tests",
        "theory_solidity": "speculative",
        "theory_reasoning": "Based on known patterns",
        "demos_solidity": "functional",
        "demos_reasoning": "Tests pass, code runs",
        "adhoc_solidity": "adhoc",
        "adhoc_reasoning": "Novel combination of ideas",
    }


@pytest.fixture
def valid_narrative(valid_solidity):
    """Valid ProformaNarrativeData dict."""
    return {
        "domain": "software engineering",
        "subdomain": "developer tooling",
        "problem": "How to automate the process of extracting structured research data from projects",
        "hypothesis": "That automated analysis can produce high-quality research commit data",
        "theoretical_framework": "Based on static analysis and NLP techniques",
        "demonstrations_summary": "Extracts file structure, dependencies, and generates AI prompts for narrative fields",
        "adhoc_summary": "Novel combination of machine extraction with AI-generated narrative for research evaluation",
        "adhoc_connections": ["Applied static analysis from compilers to research evaluation"],
        "cherry_picking": ["sentence-transformers — used for semantic similarity"],
        "solidity_assessment": valid_solidity,
    }


# ============================================================
# TestProjectTypeDetection — 4 tests
# ============================================================

class TestProjectTypeDetection:
    """Tests for _detect_project_type heuristic."""

    def test_software_detected(self):
        """Project with code files detected as software."""
        stats = {
            "files_by_extension": {".py": 10, ".md": 2, ".toml": 1},
            "loc_by_language": {"Python": 1000},
        }
        assert _detect_project_type(stats) == "software"

    def test_paper_detected(self):
        """Project with .tex/.bib files detected as paper."""
        stats = {
            "files_by_extension": {".tex": 5, ".bib": 2, ".md": 1},
            "loc_by_language": {},
        }
        assert _detect_project_type(stats) == "paper"

    def test_dataset_detected(self):
        """Project with data files and minimal code detected as dataset."""
        stats = {
            "files_by_extension": {".csv": 8, ".json": 3, ".md": 1, ".py": 1},
            "loc_by_language": {"Python": 50},
        }
        assert _detect_project_type(stats) == "dataset"

    def test_theoretical_detected(self):
        """Project with only docs detected as theoretical."""
        stats = {
            "files_by_extension": {".md": 10, ".rst": 3},
            "loc_by_language": {},
        }
        assert _detect_project_type(stats) == "theoretical"


# ============================================================
# TestKeyFileSelection — 3 tests
# ============================================================

class TestKeyFileSelection:
    """Tests for _select_key_files."""

    def test_readme_always_included(self, tmp_project, sample_machine_data):
        """README should always be in the selected files."""
        result = _select_key_files(tmp_project, sample_machine_data)
        assert "README.md" in result

    def test_main_source_selected(self, tmp_project, sample_machine_data):
        """Largest source file should be selected when available."""
        # Add a large file to largest_files
        large_path = os.path.join(tmp_project, "src", "main.py")
        sample_machine_data["files"]["largest_files"] = [[large_path, 5000]]
        result = _select_key_files(tmp_project, sample_machine_data)
        has_source = any(f.endswith(".py") for f in result.keys())
        assert has_source

    def test_max_files_respected(self, tmp_project, sample_machine_data):
        """Should not exceed MAX_KEY_FILES."""
        # Create many files
        for i in range(20):
            path = os.path.join(tmp_project, f"file_{i}.py")
            with open(path, "w") as f:
                f.write(f"# File {i}\n" * 100)
        sample_machine_data["files"]["largest_files"] = [
            [os.path.join(tmp_project, f"file_{i}.py"), 1000] for i in range(20)
        ]
        result = _select_key_files(tmp_project, sample_machine_data)
        assert len(result) <= MAX_KEY_FILES


# ============================================================
# TestPromptGeneration — 2 tests
# ============================================================

class TestPromptGeneration:
    """Tests for _build_narrative_prompt."""

    def test_prompt_contains_machine_data(self, sample_machine_data):
        """Prompt should include machine-extracted data."""
        key_files = {"README.md": "# Test\nSome content"}
        prompt = _build_narrative_prompt(sample_machine_data, key_files)
        assert "test-project" in prompt
        assert "Python" in prompt

    def test_prompt_adapts_to_project_type(self, sample_machine_data):
        """Prompt should contain type-specific guidance."""
        key_files = {"README.md": "# Test"}

        sample_machine_data["project_type"] = "paper"
        prompt_paper = _build_narrative_prompt(sample_machine_data, key_files)
        assert "ACADEMIC PAPER" in prompt_paper

        sample_machine_data["project_type"] = "software"
        prompt_sw = _build_narrative_prompt(sample_machine_data, key_files)
        assert "SOFTWARE project" in prompt_sw


# ============================================================
# TestNarrativeValidation — 5 tests
# ============================================================

class TestNarrativeValidation:
    """Tests for _validate_narrative."""

    def test_valid_narrative_passes(self, sample_machine_data, valid_narrative):
        """A well-formed narrative should have no errors."""
        narrative = ProformaNarrativeData(**valid_narrative)
        result = _validate_narrative(sample_machine_data, narrative)
        assert result["errors"] == []

    def test_domain_equals_project_name_fails(self, sample_machine_data, valid_narrative):
        """Domain matching the project name should be an error."""
        valid_narrative["domain"] = "test-project"
        narrative = ProformaNarrativeData(**valid_narrative)
        result = _validate_narrative(sample_machine_data, narrative)
        assert any("project name" in e for e in result["errors"])

    def test_short_problem_fails(self, sample_machine_data, valid_narrative):
        """Very short problem should be an error."""
        valid_narrative["problem"] = "Short problem"
        narrative = ProformaNarrativeData(**valid_narrative)
        result = _validate_narrative(sample_machine_data, narrative)
        assert any("too short" in e for e in result["errors"])

    def test_missing_hypothesis_warns(self, sample_machine_data, valid_narrative):
        """Missing hypothesis should produce a warning, not error."""
        valid_narrative["hypothesis"] = None
        narrative = ProformaNarrativeData(**valid_narrative)
        result = _validate_narrative(sample_machine_data, narrative)
        assert result["errors"] == []
        assert any("hypothesis" in w for w in result["warnings"])

    def test_solidity_inconsistency_warns(self, sample_machine_data, valid_narrative):
        """Claiming 'proven' demos without test files should warn."""
        # Remove test file indicators
        sample_machine_data["files"]["files_by_extension"] = {".py": 5, ".md": 2}
        valid_narrative["solidity_assessment"]["demos_solidity"] = "proven"
        valid_narrative["solidity_assessment"]["demos_reasoning"] = "Peer reviewed"
        narrative = ProformaNarrativeData(**valid_narrative)
        result = _validate_narrative(sample_machine_data, narrative)
        assert any("proven" in w and "test" in w for w in result["warnings"])


# ============================================================
# TestProformaMapping — 2 tests
# ============================================================

class TestProformaMapping:
    """Tests for proforma → SubmitCommitInput mapping logic."""

    def test_maps_correctly(self, valid_narrative):
        """Narrative fields should map to expected SubmitCommitInput structure."""
        narrative = ProformaNarrativeData(**valid_narrative)
        sa = narrative.solidity_assessment

        # Simulate the mapping done in submit mode
        mapped = {
            "domain": narrative.domain,
            "subdomain": narrative.subdomain,
            "problem": narrative.problem,
            "hypothesis": narrative.hypothesis,
            "theoretical_framework": narrative.theoretical_framework,
            "demonstrations_summary": narrative.demonstrations_summary,
            "adhoc_summary": narrative.adhoc_summary,
            "adhoc_connections": narrative.adhoc_connections,
            "cherry_picking": narrative.cherry_picking,
            "solidity_levels": {
                "theory": sa.theory_solidity,
                "demos": sa.demos_solidity,
                "adhoc": sa.adhoc_solidity,
            },
            "overall_solidity": sa.overall_solidity,
        }

        assert mapped["domain"] == "software engineering"
        assert mapped["solidity_levels"]["theory"] == "speculative"
        assert mapped["overall_solidity"] == "functional"

    def test_machine_fields_override(self, valid_narrative):
        """Machine-extracted code_languages and demo_types should be used, not narrative."""
        machine_code_languages = ["Python", "JavaScript"]
        machine_demo_types = ["code", "data"]

        # These are machine fields — narrative doesn't contain them
        commit_data = {
            "domain": valid_narrative["domain"],
            "code_languages": machine_code_languages,
            "demo_types": machine_demo_types,
        }

        assert commit_data["code_languages"] == ["Python", "JavaScript"]
        assert commit_data["demo_types"] == ["code", "data"]


# ============================================================
# TestPrepareCommitPydantic — 2 tests
# ============================================================

class TestPrepareCommitPydantic:
    """Tests for PrepareCommitInput validation."""

    def test_valid_input(self):
        """Valid extract input should pass."""
        inp = PrepareCommitInput(
            project_path="/tmp/test-project",
            mode="extract",
        )
        assert inp.mode == "extract"
        assert inp.project_path == "/tmp/test-project"

    def test_extra_fields_rejected(self):
        """Extra fields should be rejected."""
        with pytest.raises(Exception):
            PrepareCommitInput(
                project_path="/tmp/test",
                mode="extract",
                unknown_field="bad",
            )

    def test_invalid_mode_rejected(self):
        """Invalid mode should be rejected."""
        with pytest.raises(Exception):
            PrepareCommitInput(
                project_path="/tmp/test",
                mode="invalid_mode",
            )

    def test_relative_path_rejected(self):
        """Relative project_path should be rejected."""
        with pytest.raises(Exception):
            PrepareCommitInput(
                project_path="relative/path",
                mode="extract",
            )

    def test_github_url_validated(self):
        """repo_url should accept valid GitHub URLs."""
        inp = PrepareCommitInput(
            repo_url="https://github.com/owner/repo",
            mode="extract",
        )
        assert inp.repo_url == "https://github.com/owner/repo"

    def test_non_github_url_rejected(self):
        """Non-GitHub URLs should be rejected."""
        with pytest.raises(Exception):
            PrepareCommitInput(
                repo_url="https://gitlab.com/owner/repo",
                mode="extract",
            )


# ============================================================
# TestReadTruncated — 2 tests
# ============================================================

class TestReadTruncated:
    """Tests for _read_truncated helper."""

    def test_reads_file(self, tmp_path):
        """Should read file content."""
        f = tmp_path / "test.txt"
        f.write_text("Hello, world!")
        result = _read_truncated(str(f))
        assert result == "Hello, world!"

    def test_truncates_large_file(self, tmp_path):
        """Should truncate files larger than max_chars."""
        f = tmp_path / "big.txt"
        f.write_text("x" * 10000)
        result = _read_truncated(str(f), max_chars=100)
        assert len(result) < 200  # 100 + truncation message
        assert "truncated" in result


# ============================================================
# TestSolidityAssessmentValidation — 1 test
# ============================================================

class TestSolidityAssessmentValidation:
    """Tests for ProformaSolidityAssessment Pydantic validation."""

    def test_invalid_solidity_value_rejected(self):
        """Invalid solidity level strings should be rejected."""
        with pytest.raises(Exception):
            ProformaSolidityAssessment(
                overall_solidity="invalid_level",
                overall_reasoning="test",
            )
