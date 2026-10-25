#!/usr/bin/env python3
"""
analyze_repo.py — Repository Analyzer with MCP Layer

Analyzes a local repository: extracts file structure, dependencies, MCP tools,
and optionally compares against a reference project to generate adoptable
improvements.

Usage:
    python analyze_repo.py /path/to/repo
    python analyze_repo.py /path/to/repo --mcp
    python analyze_repo.py /path/to/repo --reference /path/to/our/project
    python analyze_repo.py /path/to/repo --reference /path/to/project --mcp --score --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _find_git() -> str:
    """Find git executable, checking common Windows paths if not in PATH."""
    if shutil.which("git"):
        return "git"
    # Fixed well-known install locations (no environment lookups).
    candidates = [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Programs", "Git", "cmd", "git.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return "git"  # fallback, let OS raise FileNotFoundError


# =============================================================================
# CONSTANTS
# =============================================================================

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build",
    ".next", "coverage", ".tox", ".mypy_cache", ".pytest_cache", "egg-info",
    ".eggs", ".ruff_cache",
}

EXT_TO_LANG = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".json": "JSON",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".html": "HTML",
    ".css": "CSS",
    ".sh": "Shell",
    ".sql": "SQL",
    ".rs": "Rust",
    ".go": "Go",
    ".java": "Java",
    ".rb": "Ruby",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C/C++ Header",
}

# Regex patterns for JS MCP tool extraction
JS_NAME_RE = re.compile(r'name\s*:\s*["\'](\w+)["\']')
JS_DESC_RE = re.compile(r'description\s*:\s*["\']([^"\']+)["\']')
JS_DESC_MULTILINE_RE = re.compile(
    r'description\s*:\s*\n?\s*["\']([^"\']+)["\']', re.DOTALL
)
JS_ANNOTATIONS_RE = re.compile(r'annotations\s*:\s*\{([^}]+)\}')
JS_ANNOTATION_FIELD_RE = re.compile(r'(\w+Hint)\s*:\s*(true|false)')
JS_REQUIRED_RE = re.compile(r'required\s*:\s*\[([^\]]*)\]')

# Regex patterns for Python MCP tool extraction
PY_TOOL_DECORATOR_RE = re.compile(r'@\w+\.tool\s*\(')
PY_NAME_RE = re.compile(r'name\s*=\s*["\']([^"\']+)["\']')
PY_DESC_RE = re.compile(r'description\s*=\s*\(\s*(["\'])', re.DOTALL)
PY_ANNOTATIONS_RE = re.compile(r'annotations\s*=\s*\{([^}]+)\}', re.DOTALL)
PY_ANNOTATION_FIELD_RE = re.compile(r'["\'](\w+Hint)["\']:\s*(True|False)')
PY_ASYNC_DEF_RE = re.compile(r'async\s+def\s+(\w+)\s*\(')


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class RepoMetadata:
    path: str = ""
    name: str = ""
    readme_title: str = ""
    readme_description: str = ""
    git_exists: bool = False
    total_commits: int = 0
    contributors: int = 0
    latest_commit_date: str = ""
    first_commit_date: str = ""


@dataclass
class FileStats:
    total_files: int = 0
    total_dirs: int = 0
    files_by_extension: Dict[str, int] = field(default_factory=dict)
    loc_by_language: Dict[str, int] = field(default_factory=dict)
    largest_files: List[Tuple[str, int]] = field(default_factory=list)


@dataclass
class DependencyInfo:
    package_json: Optional[Dict[str, Any]] = None
    requirements_txt: Optional[List[str]] = None
    pyproject_toml: Optional[Dict[str, Any]] = None
    setup_py_exists: bool = False
    detected_framework: Optional[str] = None


@dataclass
class MCPToolDef:
    name: str = ""
    description: str = ""
    source_file: str = ""
    source_line: int = 0
    params: List[Dict[str, Any]] = field(default_factory=list)
    annotations: Dict[str, bool] = field(default_factory=dict)


@dataclass
class MCPAnalysis:
    framework: str = ""
    tool_count: int = 0
    annotation_coverage: float = 0.0
    tools: List[MCPToolDef] = field(default_factory=list)
    has_resources: bool = False
    has_prompts: bool = False
    transport: str = "unknown"


@dataclass
class ComparisonResult:
    tools_only_in_target: List[str] = field(default_factory=list)
    tools_only_in_reference: List[str] = field(default_factory=list)
    tools_in_both: List[str] = field(default_factory=list)
    annotation_gaps: List[Dict[str, Any]] = field(default_factory=list)
    feature_gaps: List[Dict[str, Any]] = field(default_factory=list)
    adoptable_improvements: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class AnalysisReport:
    repo: RepoMetadata = field(default_factory=RepoMetadata)
    files: FileStats = field(default_factory=FileStats)
    deps: DependencyInfo = field(default_factory=DependencyInfo)
    mcp: Optional[MCPAnalysis] = None
    comparison: Optional[ComparisonResult] = None
    originality: Optional[Dict[str, Any]] = None


# =============================================================================
# LAYER 1: GENERIC ANALYSIS
# =============================================================================

def analyze_file_tree(repo_path: str) -> FileStats:
    """Walk the repo and collect file/LOC statistics."""
    stats = FileStats()
    ext_counts: Dict[str, int] = {}
    loc_counts: Dict[str, int] = {}
    file_sizes: List[Tuple[str, int]] = []

    for root, dirs, files in os.walk(repo_path):
        # Filter out skipped directories in-place
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS
                   and not d.endswith(".egg-info")]
        stats.total_dirs += len(dirs)

        for fname in files:
            filepath = os.path.join(root, fname)
            stats.total_files += 1
            ext = os.path.splitext(fname)[1].lower()
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

            lang = EXT_TO_LANG.get(ext)
            if lang:
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        lines = sum(1 for _ in f)
                    loc_counts[lang] = loc_counts.get(lang, 0) + lines
                    rel = os.path.relpath(filepath, repo_path)
                    file_sizes.append((rel, lines))
                except (OSError, UnicodeDecodeError):
                    pass

    stats.files_by_extension = dict(
        sorted(ext_counts.items(), key=lambda x: -x[1])
    )
    stats.loc_by_language = dict(
        sorted(loc_counts.items(), key=lambda x: -x[1])
    )
    file_sizes.sort(key=lambda x: -x[1])
    stats.largest_files = file_sizes[:5]
    return stats


def analyze_dependencies(repo_path: str) -> DependencyInfo:
    """Detect dependency files and MCP framework."""
    info = DependencyInfo()

    # package.json — check root and immediate subdirectories
    pkg_candidates = [os.path.join(repo_path, "package.json")]
    try:
        for entry in os.scandir(repo_path):
            if entry.is_dir() and entry.name not in SKIP_DIRS:
                candidate = os.path.join(entry.path, "package.json")
                if os.path.isfile(candidate):
                    pkg_candidates.append(candidate)
    except OSError:
        pass

    for pkg_path in pkg_candidates:
        if os.path.isfile(pkg_path):
            try:
                with open(pkg_path, "r", encoding="utf-8") as f:
                    pkg_data = json.load(f)
                # Prefer the one with actual dependencies
                if info.package_json is None or pkg_data.get("dependencies"):
                    info.package_json = pkg_data
                all_deps = {}
                all_deps.update(pkg_data.get("dependencies", {}))
                all_deps.update(pkg_data.get("devDependencies", {}))
                if "@modelcontextprotocol/sdk" in all_deps:
                    info.detected_framework = "js-sdk"
            except (json.JSONDecodeError, OSError):
                pass

    # requirements.txt
    req_path = os.path.join(repo_path, "requirements.txt")
    if os.path.isfile(req_path):
        try:
            with open(req_path, "r", encoding="utf-8") as f:
                lines = [
                    line.strip() for line in f
                    if line.strip() and not line.startswith("#")
                ]
            info.requirements_txt = lines
            for line in lines:
                pkg = line.split("==")[0].split(">=")[0].split("[")[0].strip().lower()
                if pkg in ("mcp", "fastmcp"):
                    info.detected_framework = info.detected_framework or "python-fastmcp"
        except OSError:
            pass

    # pyproject.toml
    pyproject_path = os.path.join(repo_path, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        try:
            # Python 3.11+
            import tomllib
            with open(pyproject_path, "rb") as f:
                info.pyproject_toml = tomllib.load(f)
            # Check dependencies
            deps = info.pyproject_toml.get("project", {}).get("dependencies", [])
            for dep in deps:
                dep_name = dep.split(">=")[0].split("==")[0].split("[")[0].strip().lower()
                if dep_name in ("mcp", "fastmcp"):
                    info.detected_framework = info.detected_framework or "python-fastmcp"
        except ImportError:
            # Python < 3.11 fallback: just note the file exists
            info.pyproject_toml = {"_note": "tomllib not available, file exists"}
        except (OSError, Exception):
            pass

    # setup.py
    info.setup_py_exists = os.path.isfile(os.path.join(repo_path, "setup.py"))

    return info


def analyze_readme(repo_path: str) -> Tuple[str, str]:
    """Extract title and description from README."""
    for name in ("README.md", "README.rst", "README", "readme.md"):
        readme_path = os.path.join(repo_path, name)
        if os.path.isfile(readme_path):
            try:
                with open(readme_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            title = ""
            description = ""
            lines = content.split("\n")

            # Find title: first # heading
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("#") and not stripped.startswith("##"):
                    title = stripped.lstrip("#").strip()
                    break

            # Find description: first paragraph after title, skip badges
            in_desc = False
            desc_lines = []
            for line in lines:
                stripped = line.strip()
                if title and stripped.lstrip("#").strip() == title:
                    in_desc = True
                    continue
                if in_desc:
                    # Skip badge lines
                    if stripped.startswith("[![") or stripped.startswith("!["):
                        continue
                    if not stripped:
                        if desc_lines:
                            break
                        continue
                    desc_lines.append(stripped)

            description = " ".join(desc_lines)[:500]
            return title, description

    return "", ""


def analyze_git(repo_path: str) -> RepoMetadata:
    """Extract git metadata."""
    meta = RepoMetadata()
    meta.path = os.path.abspath(repo_path)
    meta.name = os.path.basename(os.path.abspath(repo_path))

    git_dir = os.path.join(repo_path, ".git")
    meta.git_exists = os.path.isdir(git_dir)
    if not meta.git_exists:
        return meta

    def _git(cmd: List[str]) -> str:
        try:
            git_cmd = _find_git()
            result = subprocess.run(
                [git_cmd, "-C", repo_path] + cmd,
                capture_output=True, text=True, timeout=15,
            )
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    # Total commits
    count_str = _git(["rev-list", "--count", "HEAD"])
    meta.total_commits = int(count_str) if count_str.isdigit() else 0

    # Contributors
    authors = _git(["log", "--format=%aN"])
    if authors:
        meta.contributors = len(set(authors.split("\n")))

    # Latest commit date
    meta.latest_commit_date = _git(["log", "-1", "--format=%ad", "--date=short"])

    # First commit date
    first = _git(["log", "--reverse", "--format=%ad", "--date=short"])
    if first:
        meta.first_commit_date = first.split("\n")[0]

    return meta


# =============================================================================
# LAYER 2: MCP ANALYSIS
# =============================================================================

def detect_mcp_framework(repo_path: str, deps: DependencyInfo) -> str:
    """Detect which MCP framework/SDK the repo uses."""
    # Priority 1: Already detected from deps
    if deps.detected_framework:
        return deps.detected_framework

    # Priority 2: Scan source files
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            filepath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()

            if ext == ".py":
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(10000)  # first 10KB
                    if "from mcp.server.fastmcp import FastMCP" in content:
                        return "python-fastmcp"
                    if "from mcp.server import Server" in content:
                        return "python-sdk"
                except OSError:
                    pass

            elif ext in (".js", ".ts"):
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(10000)
                    if "@modelcontextprotocol/sdk" in content:
                        return "ts-sdk" if ext == ".ts" else "js-sdk"
                except OSError:
                    pass

    return "unknown"


def _extract_js_tool_objects(content: str) -> List[Tuple[str, int]]:
    """Extract individual tool object blocks from a JS ListTools handler.

    Returns list of (block_text, line_number) tuples.
    """
    # Find the ListToolsRequestSchema handler
    handler_match = re.search(
        r'setRequestHandler\s*\(\s*ListToolsRequestSchema', content
    )
    if not handler_match:
        return []

    start = handler_match.start()
    # Count lines up to handler for line offset
    line_offset = content[:start].count("\n")

    # Find the tools array
    tools_match = re.search(r'tools\s*:\s*\[', content[start:])
    if not tools_match:
        return []

    arr_start = start + tools_match.end()
    results = []
    pos = arr_start

    while pos < len(content):
        # Skip whitespace
        while pos < len(content) and content[pos] in " \t\n\r,":
            pos += 1
        if pos >= len(content) or content[pos] == "]":
            break
        if content[pos] != "{":
            pos += 1
            continue

        # Brace-balanced extraction
        depth = 0
        obj_start = pos
        while pos < len(content):
            if content[pos] == "{":
                depth += 1
            elif content[pos] == "}":
                depth -= 1
                if depth == 0:
                    pos += 1
                    block = content[obj_start:pos]
                    block_line = line_offset + content[:obj_start].count("\n") + 1
                    results.append((block, block_line))
                    break
            pos += 1
        else:
            break

    return results


def extract_tools_js(filepath: str) -> List[MCPToolDef]:
    """Extract MCP tool definitions from a JavaScript/TypeScript file."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return []

    rel_path = filepath  # will be relativized later
    tool_blocks = _extract_js_tool_objects(content)
    tools = []

    for block, line_num in tool_blocks:
        tool = MCPToolDef(source_file=rel_path, source_line=line_num)

        # Name
        m = JS_NAME_RE.search(block)
        if m:
            tool.name = m.group(1)
        else:
            continue  # skip blocks without a name

        # Description (single-line or next-line)
        m = JS_DESC_RE.search(block)
        if not m:
            m = JS_DESC_MULTILINE_RE.search(block)
        if m:
            tool.description = m.group(1).strip()

        # Annotations
        m = JS_ANNOTATIONS_RE.search(block)
        if m:
            for am in JS_ANNOTATION_FIELD_RE.finditer(m.group(1)):
                tool.annotations[am.group(1)] = am.group(2) == "true"

        # Parameters from inputSchema.properties
        props_match = re.search(r'properties\s*:\s*\{', block)
        if props_match:
            # Extract required list first
            required_names = set()
            req_m = JS_REQUIRED_RE.search(block)
            if req_m:
                required_names = {
                    n.strip().strip("\"'")
                    for n in req_m.group(1).split(",")
                    if n.strip()
                }

            # Extract individual property blocks
            pstart = props_match.end()
            depth = 1
            pend = pstart
            while pend < len(block) and depth > 0:
                if block[pend] == "{":
                    depth += 1
                elif block[pend] == "}":
                    depth -= 1
                pend += 1
            props_str = block[pstart:pend - 1]

            # Parse each property
            for pm in re.finditer(r'(\w+)\s*:\s*\{([^}]+)\}', props_str):
                param_name = pm.group(1)
                param_body = pm.group(2)
                param: Dict[str, Any] = {"name": param_name}

                type_m = re.search(r'type\s*:\s*["\'](\w+)["\']', param_body)
                if type_m:
                    param["type"] = type_m.group(1)

                desc_m = re.search(r'description\s*:\s*["\']([^"\']+)["\']', param_body)
                if not desc_m:
                    desc_m = re.search(
                        r'description\s*:\s*\n?\s*["\']([^"\']+)["\']',
                        param_body, re.DOTALL,
                    )
                if desc_m:
                    param["description"] = desc_m.group(1).strip()

                param["required"] = param_name in required_names
                tool.params.append(param)

        tools.append(tool)

    return tools


def _extract_py_decorator_block(content: str, match_start: int) -> str:
    """Extract the full decorator argument block, handling nested parens."""
    pos = content.index("(", match_start)
    depth = 0
    start = pos
    while pos < len(content):
        if content[pos] == "(":
            depth += 1
        elif content[pos] == ")":
            depth -= 1
            if depth == 0:
                return content[start + 1:pos]
        pos += 1
    return content[start + 1:]


def extract_tools_python(filepath: str) -> List[MCPToolDef]:
    """Extract MCP tool definitions from a Python file using @mcp.tool() decorators."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return []

    tools = []
    for m in PY_TOOL_DECORATOR_RE.finditer(content):
        line_num = content[:m.start()].count("\n") + 1
        tool = MCPToolDef(source_file=filepath, source_line=line_num)

        # Extract the decorator arguments
        dec_block = _extract_py_decorator_block(content, m.start())

        # Name
        nm = PY_NAME_RE.search(dec_block)
        if nm:
            tool.name = nm.group(1)

        # Description — multi-line concatenated strings
        desc_parts = []
        # Find all string literals in the description=(...) block
        desc_match = re.search(r'description\s*=\s*\(?\s*', dec_block)
        if desc_match:
            desc_area = dec_block[desc_match.end():]
            # Collect consecutive string literals
            for sm in re.finditer(r'["\']([^"\']*)["\']', desc_area):
                desc_parts.append(sm.group(1))
                # Stop if we hit a non-string-continuation
                rest = desc_area[sm.end():].lstrip()
                if not rest or (not rest.startswith('"') and not rest.startswith("'")):
                    break
            tool.description = " ".join(desc_parts).strip()[:300]

        # Annotations
        ann_m = PY_ANNOTATIONS_RE.search(dec_block)
        if ann_m:
            for am in PY_ANNOTATION_FIELD_RE.finditer(ann_m.group(1)):
                tool.annotations[am.group(1)] = am.group(2) == "True"

        # Find the async def following the decorator
        after_dec = content[m.end():]
        func_m = PY_ASYNC_DEF_RE.search(after_dec)
        if func_m and not tool.name:
            tool.name = func_m.group(1)

        if tool.name:
            tools.append(tool)

    return tools


def detect_mcp_extras(repo_path: str, framework: str) -> Tuple[bool, bool, str]:
    """Detect resources, prompts, and transport type."""
    has_resources = False
    has_prompts = False
    transport = "unknown"

    resource_patterns = ["@mcp.resource", "ListResourcesRequestSchema",
                         "@server.resource", ".resource("]
    prompt_patterns = ["@mcp.prompt", "ListPromptsRequestSchema",
                       "@server.prompt", ".prompt("]
    transport_map = {
        "streamable-http": "streamable-http",
        "StreamableHTTPServerTransport": "streamable-http",
        "stdio": "stdio",
        "StdioServerTransport": "stdio",
        "SSEServerTransport": "sse",
        "sse": "sse",
    }

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in (".py", ".js", ".ts", ".tsx"):
                continue
            filepath = os.path.join(root, fname)
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue

            for pat in resource_patterns:
                if pat in content:
                    has_resources = True
            for pat in prompt_patterns:
                if pat in content:
                    has_prompts = True
            for pat, tname in transport_map.items():
                if pat in content:
                    transport = tname

    return has_resources, has_prompts, transport


def analyze_mcp(repo_path: str, deps: DependencyInfo) -> MCPAnalysis:
    """Full MCP analysis: framework, tools, extras."""
    analysis = MCPAnalysis()
    analysis.framework = detect_mcp_framework(repo_path, deps)

    if analysis.framework == "unknown":
        return analysis

    # Extract tools from all relevant source files
    all_tools: List[MCPToolDef] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in files:
            filepath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lower()

            if ext in (".js", ".ts", ".tsx") and analysis.framework in (
                "js-sdk", "ts-sdk"
            ):
                tools = extract_tools_js(filepath)
                # Relativize paths
                for t in tools:
                    t.source_file = os.path.relpath(filepath, repo_path)
                all_tools.extend(tools)

            elif ext == ".py" and analysis.framework in (
                "python-fastmcp", "python-sdk"
            ):
                tools = extract_tools_python(filepath)
                for t in tools:
                    t.source_file = os.path.relpath(filepath, repo_path)
                all_tools.extend(tools)

    analysis.tools = all_tools
    analysis.tool_count = len(all_tools)

    # Annotation coverage
    if all_tools:
        annotated = sum(1 for t in all_tools if t.annotations)
        analysis.annotation_coverage = round(annotated / len(all_tools) * 100, 1)

    # Extras
    has_res, has_prompts, transport = detect_mcp_extras(repo_path, analysis.framework)
    analysis.has_resources = has_res
    analysis.has_prompts = has_prompts
    analysis.transport = transport

    return analysis


# =============================================================================
# LAYER 3: COMPARISON / GAP ANALYSIS
# =============================================================================

def compare_tool_lists(
    target: MCPAnalysis, reference: MCPAnalysis,
    target_name: str = "target", reference_name: str = "reference",
) -> ComparisonResult:
    """Compare MCP tools between target and reference repos."""
    result = ComparisonResult()

    target_names = {t.name for t in target.tools}
    ref_names = {t.name for t in reference.tools}

    result.tools_only_in_target = sorted(target_names - ref_names)
    result.tools_only_in_reference = sorted(ref_names - target_names)
    result.tools_in_both = sorted(target_names & ref_names)

    # Build lookup dicts
    target_by_name = {t.name: t for t in target.tools}
    ref_by_name = {t.name: t for t in reference.tools}

    # Annotation gaps: tools in both where one has annotations and other doesn't
    for name in result.tools_in_both:
        t_tool = target_by_name[name]
        r_tool = ref_by_name[name]
        if t_tool.annotations and not r_tool.annotations:
            result.annotation_gaps.append({
                "tool": name,
                "has_annotations": target_name,
                "missing_annotations": reference_name,
                "annotations": t_tool.annotations,
            })
        elif r_tool.annotations and not t_tool.annotations:
            result.annotation_gaps.append({
                "tool": name,
                "has_annotations": reference_name,
                "missing_annotations": target_name,
                "annotations": r_tool.annotations,
            })

    # Feature gaps: unique tools in target
    for name in result.tools_only_in_target:
        tool = target_by_name[name]
        result.feature_gaps.append({
            "tool": name,
            "description": tool.description,
            "source": target_name,
        })

    # Adoptable improvements
    improvements = []

    # HIGH: annotation coverage gap
    if target.annotation_coverage - reference.annotation_coverage > 20:
        improvements.append({
            "area": "annotations",
            "description": (
                f"Annotation coverage: {target_name} has "
                f"{target.annotation_coverage:.0f}% vs {reference_name} "
                f"{reference.annotation_coverage:.0f}%"
            ),
            "priority": "HIGH",
        })

    # HIGH: unique tools in target
    if result.tools_only_in_target:
        improvements.append({
            "area": "tools",
            "description": (
                f"{len(result.tools_only_in_target)} tools in {target_name} "
                f"missing from {reference_name}"
            ),
            "priority": "HIGH",
            "tools": result.tools_only_in_target,
        })

    # MEDIUM: individual feature highlights
    for gap in result.feature_gaps[:10]:
        improvements.append({
            "area": "feature",
            "description": f"{gap['tool']}: {gap['description'][:100]}",
            "priority": "MEDIUM",
        })

    # MEDIUM: resources/prompts gap
    if target.has_resources and not reference.has_resources:
        improvements.append({
            "area": "resources",
            "description": f"{target_name} has MCP resources, {reference_name} doesn't",
            "priority": "MEDIUM",
        })
    if target.has_prompts and not reference.has_prompts:
        improvements.append({
            "area": "prompts",
            "description": f"{target_name} has MCP prompts, {reference_name} doesn't",
            "priority": "MEDIUM",
        })

    # LOW: transport differences
    if target.transport != reference.transport and target.transport != "unknown":
        improvements.append({
            "area": "transport",
            "description": (
                f"Transport: {target_name} uses {target.transport}, "
                f"{reference_name} uses {reference.transport}"
            ),
            "priority": "LOW",
        })

    # Semantic similarity for mismatched tool names (Jaccard fallback only)
    similar = _find_similar_tools(target, reference)
    if similar:
        improvements.append({
            "area": "similar_tools",
            "description": (
                f"{len(similar)} tools with similar functionality but different names"
            ),
            "priority": "LOW",
            "details": similar,
        })

    result.adoptable_improvements = improvements
    return result


def _find_similar_tools(
    target: MCPAnalysis, reference: MCPAnalysis, threshold: float = 0.3,
) -> List[Dict[str, Any]]:
    """Find tools with similar descriptions but different names (Jaccard)."""
    target_unique = {t.name: t for t in target.tools}
    ref_unique = {t.name: t for t in reference.tools}

    # Only compare tools unique to each side
    target_only = {
        n: t for n, t in target_unique.items()
        if n not in ref_unique
    }
    ref_only = {
        n: t for n, t in ref_unique.items()
        if n not in target_unique
    }

    similar = []
    for t_name, t_tool in target_only.items():
        if not t_tool.description:
            continue
        t_words = set(t_tool.description.lower().split())
        for r_name, r_tool in ref_only.items():
            if not r_tool.description:
                continue
            r_words = set(r_tool.description.lower().split())
            if not t_words or not r_words:
                continue
            jaccard = len(t_words & r_words) / len(t_words | r_words)
            if jaccard >= threshold:
                similar.append({
                    "target_tool": t_name,
                    "reference_tool": r_name,
                    "similarity": round(jaccard, 2),
                })

    similar.sort(key=lambda x: -x["similarity"])
    return similar[:10]


# =============================================================================
# LAYER 4: ORIGINALITY SCORING (--score)
# =============================================================================

def map_repo_to_commit_data(
    repo: RepoMetadata, files: FileStats,
    deps: DependencyInfo, mcp: Optional[MCPAnalysis],
) -> Dict[str, Any]:
    """Map extracted repo metadata to the format expected by OriginalityEvaluator."""
    # Infer domain from README or deps
    domain = "software-engineering"
    desc_lower = (repo.readme_description or "").lower()
    if any(w in desc_lower for w in ("whatsapp", "messaging", "chat")):
        domain = "communication-tools"
    elif any(w in desc_lower for w in ("research", "academic", "science")):
        domain = "research-tools"
    elif any(w in desc_lower for w in ("ai", "machine learning", "ml", "llm")):
        domain = "artificial-intelligence"

    # Code languages
    code_langs = list(files.loc_by_language.keys())

    # Demo types
    demo_types = []
    if code_langs:
        demo_types.append("code")
    exts = set(files.files_by_extension.keys())
    if exts & {".csv", ".sql", ".sqlite", ".parquet"}:
        demo_types.append("data")
    if exts & {".tex", ".bib"}:
        demo_types.append("math")

    # Overall solidity
    overall_solidity = "functional" if repo.total_commits > 20 else "speculative"

    # Adhoc connections from deps
    adhoc = []
    if deps.package_json:
        all_pkg_deps = list(deps.package_json.get("dependencies", {}).keys())
        all_pkg_deps += list(deps.package_json.get("devDependencies", {}).keys())
        # Cross-domain deps hint at interdisciplinary connections
        for d in all_pkg_deps:
            if any(kw in d for kw in ("openai", "anthropic", "google", "aws")):
                adhoc.append(f"API integration: {d}")
    if deps.requirements_txt:
        for line in deps.requirements_txt:
            pkg = line.split("==")[0].split(">=")[0].strip().lower()
            if any(kw in pkg for kw in ("openai", "anthropic", "transformers", "torch")):
                adhoc.append(f"ML integration: {pkg}")

    return {
        "domain": domain,
        "subdomain": repo.name,
        "problem": repo.readme_description or f"Repository: {repo.name}",
        "hypothesis": repo.readme_title,
        "theoretical_framework": "",
        "demonstrations_summary": f"{files.total_files} files, {sum(files.loc_by_language.values())} LOC",
        "demo_types": json.dumps(demo_types),
        "code_languages": json.dumps(code_langs),
        "adhoc_summary": repo.readme_description or "",
        "adhoc_connections": json.dumps(adhoc),
        "cherry_picking": "[]",
        "overall_solidity": overall_solidity,
        "solidity_levels": {},
    }


def score_originality(commit_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Score repo originality using OriginalityEvaluator from ResearchMatch."""
    import sqlite3 as _sqlite3

    try:
        # Add the src directory to path
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)

        from research_match_server import OriginalityEvaluator, EmbeddingEngine, init_database
    except ImportError as e:
        return {"error": f"Could not import OriginalityEvaluator: {e}"}

    # In-memory DB with schema
    try:
        import asyncio as _asyncio
        try:
            from research_match_server import OpenAlexClient
            _literature = OpenAlexClient()
        except Exception:
            _literature = None
        db = init_database(":memory:")
        embeddings = EmbeddingEngine()
        evaluator = OriginalityEvaluator(db, embeddings, literature=_literature)
        # evaluate_commit is async — run it to completion (it was previously left as an
        # un-awaited coroutine, which silently produced a broken report).
        result = _asyncio.run(evaluator.evaluate_commit(commit_data, user_id="analyzer"))
        db.close()
        return result
    except Exception as e:
        return {"error": f"Scoring failed: {e}"}


# =============================================================================
# LAYER 5: OUTPUT FORMATTING
# =============================================================================

def _bar(value: float, max_val: float, width: int = 20) -> str:
    """Render a simple text bar chart segment."""
    if max_val <= 0:
        return ""
    filled = int(value / max_val * width)
    return "\u2588" * filled


def format_text(report: AnalysisReport) -> str:
    """Format the analysis report as human-readable text."""
    lines = []
    sep = "=" * 60

    # Header
    display_name = report.repo.readme_title or report.repo.name
    lines.append(sep)
    lines.append(f"REPO ANALYSIS: {display_name}")
    lines.append(sep)

    # Repository overview
    lines.append("")
    lines.append("--- Repository Overview ---")
    lines.append(f"Path:         {report.repo.path}")
    if report.repo.readme_title:
        lines.append(f"README:       {report.repo.readme_title}")
    if report.repo.readme_description:
        desc = report.repo.readme_description[:120]
        lines.append(f"Description:  {desc}")
    if report.repo.git_exists:
        parts = [f"Commits: {report.repo.total_commits}"]
        parts.append(f"Contributors: {report.repo.contributors}")
        if report.repo.first_commit_date:
            parts.append(f"Since: {report.repo.first_commit_date}")
        lines.append(" | ".join(parts))

    # File structure
    lines.append("")
    lines.append("--- File Structure ---")
    lines.append(f"Files: {report.files.total_files} | Dirs: {report.files.total_dirs}")

    total_loc = sum(report.files.loc_by_language.values()) or 1
    max_loc = max(report.files.loc_by_language.values()) if report.files.loc_by_language else 1
    for lang, loc in report.files.loc_by_language.items():
        pct = loc / total_loc * 100
        bar = _bar(loc, max_loc)
        lines.append(f"  {lang:<12} {loc:>6,} LOC  {bar} {pct:.0f}%")

    if report.files.largest_files:
        lines.append("Largest files:")
        for fname, loc in report.files.largest_files:
            lines.append(f"  {loc:>6,} LOC  {fname}")

    # Dependencies
    lines.append("")
    lines.append("--- Dependencies ---")
    if report.deps.package_json:
        pkg = report.deps.package_json
        pkg_deps = pkg.get("dependencies", {})
        lines.append(f"package.json: {pkg.get('name', '?')} v{pkg.get('version', '?')} ({len(pkg_deps)} deps)")
    if report.deps.requirements_txt:
        lines.append(f"requirements.txt: {len(report.deps.requirements_txt)} packages")
    if report.deps.pyproject_toml:
        lines.append("pyproject.toml: present")
    if report.deps.setup_py_exists:
        lines.append("setup.py: present")
    if report.deps.detected_framework:
        lines.append(f"Detected framework: {report.deps.detected_framework}")

    # MCP Analysis
    if report.mcp:
        lines.append("")
        lines.append("--- MCP Analysis ---")
        lines.append(f"Framework:    {report.mcp.framework}")
        tool_bar = "\u2588" * min(report.mcp.tool_count, 50)
        lines.append(f"Tools ({report.mcp.tool_count}):   {tool_bar}")
        annotated = sum(1 for t in report.mcp.tools if t.annotations)
        lines.append(
            f"Annotations:  {report.mcp.annotation_coverage:.0f}% "
            f"({annotated}/{report.mcp.tool_count})"
        )
        lines.append(f"Transport:    {report.mcp.transport}")
        if report.mcp.has_resources:
            lines.append("Resources:    yes")
        if report.mcp.has_prompts:
            lines.append("Prompts:      yes")

        lines.append("")
        lines.append("Tools list:")
        for t in report.mcp.tools:
            ann_str = ""
            if t.annotations:
                flags = [f"{k}={v}" for k, v in t.annotations.items()]
                ann_str = f"  [{', '.join(flags)}]"
            lines.append(f"  {t.name:<35} {t.source_file}:{t.source_line}{ann_str}")
            if t.description:
                lines.append(f"    {t.description[:100]}")

    # Comparison
    if report.comparison:
        lines.append("")
        lines.append("--- Comparison ---")
        c = report.comparison
        if c.tools_only_in_target:
            target_list = ", ".join(c.tools_only_in_target[:8])
            if len(c.tools_only_in_target) > 8:
                target_list += "..."
            lines.append(
                f"Target has ({len(c.tools_only_in_target)} unique):  {target_list}"
            )
        if c.tools_only_in_reference:
            ref_list = ", ".join(c.tools_only_in_reference[:8])
            if len(c.tools_only_in_reference) > 8:
                ref_list += "..."
            lines.append(
                f"Reference has ({len(c.tools_only_in_reference)} unique): {ref_list}"
            )
        if c.tools_in_both:
            lines.append(f"Shared: {len(c.tools_in_both)} tools")

        if c.annotation_gaps:
            lines.append(f"Annotation gaps: {len(c.annotation_gaps)}")

        if c.adoptable_improvements:
            lines.append("")
            lines.append("ADOPTABLE IMPROVEMENTS:")
            for imp in c.adoptable_improvements:
                lines.append(f"  [{imp['priority']:<6}] {imp['description']}")

    # Originality
    if report.originality:
        lines.append("")
        lines.append("--- Originality Score ---")
        if "error" in report.originality:
            lines.append(f"Error: {report.originality['error']}")
        else:
            lines.append(f"OT Score:  {report.originality.get('ot_score', 0):.1f}%")
            lines.append(f"OFC Score: {report.originality.get('ofc_score', 0):.1f}%")
            si = report.originality.get("solidity_impact", {})
            if si:
                lines.append(f"Solidity:  {si.get('overall_solidity', '?')}")

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


def format_json(report: AnalysisReport) -> str:
    """Format the analysis report as JSON."""
    data = asdict(report)
    return json.dumps(data, indent=2, default=str)


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze a repository: structure, dependencies, MCP tools, and more.",
    )
    parser.add_argument(
        "repo_path",
        help="Path to the repository to analyze",
    )
    parser.add_argument(
        "--reference", "-r",
        help="Path to the reference project for comparison",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Force MCP analysis (auto-detected if not passed)",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="Run OriginalityEvaluator on the repo",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output as JSON instead of text",
    )
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo_path)
    if not os.path.isdir(repo_path):
        print(f"Error: {repo_path} is not a directory", file=sys.stderr)
        sys.exit(1)

    report = AnalysisReport()

    # Layer 1: Generic analysis
    report.repo = analyze_git(repo_path)
    title, desc = analyze_readme(repo_path)
    report.repo.readme_title = title
    report.repo.readme_description = desc
    report.files = analyze_file_tree(repo_path)
    report.deps = analyze_dependencies(repo_path)

    # Layer 2: MCP analysis (auto-detect or forced)
    do_mcp = args.mcp or report.deps.detected_framework is not None
    if do_mcp:
        report.mcp = analyze_mcp(repo_path, report.deps)

    # Layer 3: Comparison
    if args.reference:
        ref_path = os.path.abspath(args.reference)
        if not os.path.isdir(ref_path):
            print(f"Error: reference {ref_path} is not a directory", file=sys.stderr)
            sys.exit(1)

        ref_deps = analyze_dependencies(ref_path)
        ref_mcp = analyze_mcp(ref_path, ref_deps)

        if report.mcp is None:
            report.mcp = analyze_mcp(repo_path, report.deps)

        target_name = report.repo.name
        ref_name = os.path.basename(ref_path)
        report.comparison = compare_tool_lists(
            report.mcp, ref_mcp, target_name, ref_name,
        )

    # Layer 4: Originality scoring
    if args.score:
        commit_data = map_repo_to_commit_data(
            report.repo, report.files, report.deps, report.mcp,
        )
        report.originality = score_originality(commit_data)

    # Layer 5: Output
    if args.json_output:
        print(format_json(report))
    else:
        print(format_text(report))


if __name__ == "__main__":
    main()
