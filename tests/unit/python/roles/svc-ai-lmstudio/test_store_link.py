from __future__ import annotations

import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-lmstudio"
FILES = {
    "core": ROLE / "tasks" / "00_core.yml",
    "node": ROLE / "tasks" / "utils" / "preload" / "node.yml",
    "vars": ROLE / ROLE_FILE_VARS_MAIN,
    "compose": ROLE / ROLE_FILE_TEMPL_COMPOSE,
}
REQUIRE = "utils/require.yml"
START = "network/routine.yml"
DOWNLOADS = ("lms get", "get_url_retry", "preseed.yml", "pull.yml")


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
    found.extend(
        f"the preload still downloads through {needle}"
        for needle in DOWNLOADS
        if needle in texts["core"] + texts["node"]
    )
    if (
        "ln -sfn" not in texts["node"]
        or "AI_MODELS_STORE_PATH, model.sha256" not in texts["node"]
    ):
        found.append(
            "the preload does not link <models>/<repo>/<file> to the store file"
        )
    if "extra_volumes=[LMSTUDIO_STORE_MOUNT]" not in texts["compose"]:
        found.append("the compose file does not mount the store")
    mount = load_yaml_str(texts["vars"]).get("LMSTUDIO_STORE_MOUNT", "")
    if not str(mount).endswith(":ro"):
        found.append("the store mount is not read-only")
    return found


class TestLmStudioStoreLink(unittest.TestCase):
    def test_lm_studio_links_its_models_to_the_store(self) -> None:
        self.assertEqual(_findings(_texts()), [])

    def test_the_guard_reports_a_download_and_a_writable_mount(self) -> None:
        texts = _texts()
        texts["node"] += "\n- shell: lms get --yes --gguf x@q4\n"
        texts["vars"] = texts["vars"].replace(':ro"', '"')
        self.assertEqual(len(_findings(texts)), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
