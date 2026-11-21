from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-ollama"
FILES = {
    "core": ROLE / "tasks" / "00_core.yml",
    "manager": ROLE / "tasks" / "01_manager_ops.yml",
    "create": ROLE / "tasks" / "03_create.yml",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "compose": ROLE / ROLE_FILE_TEMPL_COMPOSE,
}
REQUIRE = "utils/require.yml"
START = "network/routine.yml"


def _texts() -> dict[str, str]:
    return {key: read_text(str(path)) for key, path in FILES.items()}


def _first(tasks: list[dict], needle: str) -> int:
    return next(
        (index for index, task in enumerate(tasks) if needle in dump_yaml_str(task)),
        len(tasks),
    )


def _findings(texts: dict[str, str]) -> list[str]:
    tasks = load_yaml_str(texts["core"])
    found = []
    if _first(tasks, REQUIRE) >= _first(tasks, START):
        found.append("00_core does not run the store's require.yml before the start")
    if "get_url_retry" in texts["create"]:
        found.append("03_create still downloads its own copy")
    if "ln -sfn" not in texts["create"] or "ollama_blob" not in texts["create"]:
        found.append("03_create does not link the store file as the blob")
    if "AI_MODELS_STORE_PATH, ollama_file.sha256" not in texts["manager"]:
        found.append("the Modelfile source is not the store file")
    if "'sha256-' ~ ollama_file.sha256" not in texts["manager"]:
        found.append("the blob is not named sha256-<digest>")
    if "extra_volumes=[OLLAMA_STORE_MOUNT]" not in texts["compose"]:
        found.append("the compose file does not mount the store")
    mount = load_yaml_str(texts["vars"]).get("OLLAMA_STORE_MOUNT", "")
    if not str(mount).endswith(":ro"):
        found.append("the store mount is not read-only")
    return found


class TestOllamaStoreLink(unittest.TestCase):
    def test_ollama_takes_its_models_from_the_store_without_a_copy(self) -> None:
        self.assertEqual(_findings(_texts()), [])

    def test_the_guard_reports_a_download_and_a_late_require(self) -> None:
        texts = _texts()
        tasks = load_yaml_str(texts["core"])
        moved = [task for task in tasks if REQUIRE not in dump_yaml_str(task)]
        moved.extend(task for task in tasks if REQUIRE in dump_yaml_str(task))
        texts["core"] = dump_yaml_str(moved)
        texts["create"] += "\n- get_url_retry: {}\n"
        texts["vars"] = texts["vars"].replace(':ro"', '"')
        self.assertEqual(len(_findings(texts)), 3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
