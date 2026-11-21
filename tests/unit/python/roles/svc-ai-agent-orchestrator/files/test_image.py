"""Unit test: the files the deploy stages into the orchestrator's build context
are enough to load every routine of the deployed revision and every module
the server imports, and the image installs LangGraph from a pinned
requirements file."""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-agent-orchestrator"
VARS = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
SERVER = ROLE / "files" / "python" / "server.py"
PROBE = """
import importlib, sys
sys.meta_path[:] = [f for f in sys.meta_path if not getattr(f, "__module__", "").startswith("__editable__")]
sys.path.insert(0, ".")
from agents.routines import discover, load
names = discover()
for name in names:
    load(name)
for module in sys.argv[1:]:
    importlib.import_module(module)
print(len(names))
"""


def _server_imports() -> list[str]:
    modules = []
    for node in ast.walk(ast.parse(read_text(str(SERVER)))):
        if isinstance(node, ast.ImportFrom) and node.module.split(".")[0] in (
            "utils",
            "agents",
        ):
            modules.extend(
                f"{node.module}.{alias.name}"
                if (
                    PROJECT_ROOT / node.module.replace(".", "/") / f"{alias.name}.py"
                ).is_file()
                else node.module
                for alias in node.names
            )
    return sorted(set(modules))


def _stage(build: Path) -> None:
    for relative in VARS["AGENT_ORCHESTRATOR_LIBS"]:
        target = build / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / relative, target)
    routines = VARS["AGENT_ORCHESTRATOR_ROUTINES_DIR"]
    shutil.copytree(
        PROJECT_ROOT / routines,
        build / routines,
        ignore=shutil.ignore_patterns("__pycache__"),
    )


class TestImageContents(unittest.TestCase):
    def test_the_staged_files_load_every_routine_and_server_import(self) -> None:
        modules = _server_imports()
        self.assertIn("utils.orchestrator.scheduler", modules)
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            _stage(build)
            result = subprocess.run(
                [sys.executable, "-I", "-c", PROBE, *modules],
                cwd=build,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertGreater(int(result.stdout.strip()), 0)

    def test_the_image_installs_pinned_langgraph_and_copies_the_routines(self) -> None:
        requirements = read_text(str(ROLE / "files" / "requirements.txt")).split()
        self.assertTrue(any(line.startswith("langgraph==") for line in requirements))
        dockerfile = read_text(str(ROLE / "files" / "Dockerfile"))
        self.assertIn("pip install --no-cache-dir -r", dockerfile)
        self.assertIn("COPY agents /opt/orchestrator/agents", dockerfile)


if __name__ == "__main__":
    unittest.main()
