from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: {self.snippet}"


def _iter_target_files(repo_root: Path) -> Iterable[Path]:
    prefix = repo_root / "cli" / "deploy"
    paths = [
        Path(p)
        for p in iter_project_files(extensions=(".py",))
        if Path(p).is_relative_to(prefix)
    ]
    return sorted(paths)


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _iter_assigned_names(target: ast.AST) -> Iterable[str]:
    if isinstance(target, ast.Name):
        yield target.id
        return
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _iter_assigned_names(elt)


def _expr_contains_pipefail(node: ast.AST, pipefail_vars: set[str]) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return "pipefail" in node.value

    if isinstance(node, ast.Name):
        return node.id in pipefail_vars

    if isinstance(node, ast.JoinedStr):
        return any(_expr_contains_pipefail(v, pipefail_vars) for v in node.values)

    if isinstance(node, ast.FormattedValue):
        return _expr_contains_pipefail(node.value, pipefail_vars)

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _expr_contains_pipefail(
            node.left, pipefail_vars
        ) or _expr_contains_pipefail(node.right, pipefail_vars)

    if isinstance(node, (ast.List, ast.Tuple)):
        return any(_expr_contains_pipefail(v, pipefail_vars) for v in node.elts)

    return False


def _collect_pipefail_vars(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _expr_contains_pipefail(
                node.value, names
            ):
                for t in node.targets:
                    for name in _iter_assigned_names(t):
                        if name not in names:
                            names.add(name)
                            changed = True
            if (
                isinstance(node, ast.AnnAssign) and node.value is not None
            ) and _expr_contains_pipefail(node.value, names):
                for name in _iter_assigned_names(node.target):
                    if name not in names:
                        names.add(name)
                        changed = True
    return names


def _is_sh_lc_command(node: ast.AST) -> bool:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return False
    if len(node.elts) < 3:
        return False
    return _const_str(node.elts[0]) == "sh" and _const_str(node.elts[1]) == "-lc"


def _scan_file(path: Path) -> list[Finding]:
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return []
    tree = ast.parse(text, filename=path.as_posix())
    lines = text.splitlines()
    pipefail_vars = _collect_pipefail_vars(tree)

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not _is_sh_lc_command(node):
            continue
        # type narrowing above ensures list/tuple with at least 3 elts
        cmd_expr = node.elts[2]  # type: ignore[attr-defined]
        if not _expr_contains_pipefail(cmd_expr, pipefail_vars):
            continue

        lineno = getattr(node, "lineno", 0) or 0
        snippet = lines[lineno - 1].strip() if 1 <= lineno <= len(lines) else ""
        findings.append(Finding(file=path, line=lineno, snippet=snippet))

    return findings


class TestNoShLcPipefail(unittest.TestCase):
    def test_no_sh_lc_invocation_uses_pipefail(self) -> None:
        """
        `pipefail` requires bash. Using it via `sh -lc` is not portable and breaks
        on Debian/Ubuntu (dash) with: `set: Illegal option -o pipefail`.
        """
        repo_root = PROJECT_ROOT
        findings: list[Finding] = []
        for py_file in _iter_target_files(repo_root):
            findings.extend(_scan_file(py_file))

        if findings:
            formatted = "\n".join(f.format(repo_root) for f in findings)
            self.fail(
                "Found forbidden pattern: `sh -lc` invoked with command content that uses "
                "`pipefail`.\nUse `bash -lc` or remove `pipefail` for POSIX `sh`.\n"
                f"{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
