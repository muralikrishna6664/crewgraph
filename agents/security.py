"""Static security checks for generated project files."""

import ast
import re
from pathlib import Path

from falkordb.graph import Graph

from agents.runner import Agent
from agents.worker import _workspace_path
from app import queries

SECRET_PATTERN = re.compile(
    r"""(?i)\b[\w]*(?:api[_-]?key|secret|password|access[_-]?token)[\w]*\s*[:=]\s*['"][^'"]{4,}['"]"""
)
WILDCARD_CORS_PATTERN = re.compile(
    r"""(?i)allow_origins\s*=\s*\[[^\]]*['"]\*['"]"""
)
DANGEROUS_PATTERN = re.compile(
    r"(?i)\b(?:eval|exec)\s*\(|\b(?:pickle|cPickle)\s*\.|\bimport\s+(?:pickle|cPickle)\b"
)


class SecurityAgent(Agent):
    """Scan the generated project without using an LLM verdict."""

    def __init__(self) -> None:
        super().__init__(
            name="security",
            role="Scan generated files for common security weaknesses",
            skills=["security"],
            system_prompt="Perform deterministic static checks on generated files.",
        )

    def scan_task(
        self, graph: Graph, task: dict[str, object]
    ) -> list[dict[str, object]]:
        """Scan generated files, record linked security bugs, and set task status."""
        task_id = task.get("id")
        if not isinstance(task_id, str):
            raise ValueError("Security task must have a string id")

        project_root = _workspace_path(graph.name, "sentinel").parent
        findings: list[dict[str, object]] = []
        seen_paths: set[str] = set()
        for file_path in sorted(project_root.rglob("*")):
            if not file_path.is_file() or file_path.suffix.lower() not in {
                ".py",
                ".html",
                ".js",
                ".json",
            }:
                continue
            relative_path = file_path.relative_to(project_root).as_posix()
            if relative_path in seen_paths:
                continue
            seen_paths.add(relative_path)
            source = file_path.read_text(encoding="utf-8")
            for finding in self._scan_file(relative_path, source):
                artifact = queries.artifact_for_path(graph, relative_path)
                if artifact is None:
                    raise ValueError(f"No Artifact recorded for scanned file: {relative_path}")
                finding.update(
                    {
                        "path": relative_path,
                        "artifact_id": artifact.properties["id"],
                    }
                )
                bug_id = (
                    f"security:{relative_path}:{finding['line']}:"
                    f"{finding['check']}"
                )
                queries.record_bug(
                    graph,
                    bug_id,
                    finding["title"],
                    finding["severity"],
                    artifact.properties["id"],
                    status="open",
                    kind="security",
                    line=finding["line"],
                    fix_suggestion=finding["fix_suggestion"],
                )
                finding["bug_id"] = bug_id
                findings.append(finding)

        if findings:
            queries.fail_task(
                graph,
                task_id,
                "; ".join(
                    f"{finding['path']}:{finding['line']} {finding['title']}"
                    for finding in findings
                ),
            )
        elif queries.complete_task(graph, task_id) is None:
            raise ValueError(f"Could not complete security task: {task_id}")
        return findings

    @staticmethod
    def _scan_file(path: str, source: str) -> list[dict[str, object]]:
        """Return security findings with line numbers and concise remediation."""
        findings: list[dict[str, object]] = []

        def add(
            check: str, line: int, title: str, severity: str, suggestion: str
        ) -> None:
            findings.append(
                {
                    "check": check,
                    "line": line,
                    "title": title,
                    "severity": severity,
                    "fix_suggestion": suggestion,
                }
            )

        lines = source.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if SECRET_PATTERN.search(line):
                add(
                    "hardcoded-secret",
                    line_number,
                    "Hardcoded secret or API key",
                    "critical",
                    "Remove the credential and load secrets from a protected environment variable.",
                )
            if WILDCARD_CORS_PATTERN.search(line):
                add(
                    "wildcard-cors",
                    line_number,
                    "CORS allows every origin",
                    "high",
                    "Restrict allow_origins to the specific trusted application origins.",
                )
            if re.search(r"(?i)\bdebug\s*=\s*True\b", line):
                add(
                    "debug-enabled",
                    line_number,
                    "Debug mode is enabled",
                    "medium",
                    "Disable debug mode outside local development.",
                )
            if DANGEROUS_PATTERN.search(line):
                add(
                    "unsafe-execution",
                    line_number,
                    "Unsafe dynamic execution or pickle use",
                    "high",
                    "Remove eval/exec/pickle and use safe parsing and serialization.",
                )

        if path.endswith(".py"):
            try:
                tree = ast.parse(source)
            except SyntaxError:
                tree = None
            if tree is not None:
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    is_post = any(
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr.lower() == "post"
                        for decorator in node.decorator_list
                    )
                    if not is_post:
                        continue
                    body = ast.get_source_segment(source, node) or ""
                    has_validation = bool(
                        re.search(
                            r"\.strip\s*\(|min_length\s*=|constr\s*\(|"
                            r"field_validator|HTTPException",
                            body,
                        )
                    )
                    if not has_validation:
                        add(
                            "post-input-validation",
                            node.lineno,
                            f"POST endpoint {node.name} lacks input validation",
                            "medium",
                            "Validate required fields and reject empty or malformed input.",
                        )
        return findings
