from __future__ import annotations

import functools
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.filter.litellm.local_model import (
    declared_local_models,
    local_model_refusal,
)
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.env.handlers.infinito.cache.paths import BASE_KEY
from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY
from utils.inventory.tools_vars import RENDERED, TEMPLATE, render
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS
from utils.templating.ansible import _trust_as_template

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

_KEY = "preload_models"
_SOURCES = frozenset({"group_vars", "roles", "inventories"})
_TAG_PULL = re.compile(r"\bollama\s+(?:pull|run)\b|/api/pull\b")
_SCANNED = frozenset({".yml", ".yaml", ".j2", ".sh", ".py", ".js"})


def _lists(node: Any) -> Iterator[Any]:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == _KEY:
                yield value
            else:
                yield from _lists(value)
    elif isinstance(node, list):
        for item in node:
            yield from _lists(item)


def _rendered_tools(root: Path) -> Any:
    with tempfile.TemporaryDirectory() as scratch:
        (Path(scratch) / TEMPLATE).parent.mkdir(parents=True)
        shutil.copy(root / TEMPLATE, Path(scratch) / TEMPLATE)
        lane = {BASE_KEY: "/srv/cache", MODELS_KEY: "/srv/cache/models"}
        return load_yaml_any(str(render(Path(scratch), ["en"], lane)))


def _rendered(templar: Templar, value: Any) -> Any:
    if isinstance(value, str):
        return templar.template(_trust_as_template(value))
    return value


def _files(directory: Path, extensions: tuple[str, ...] | None) -> list[Path]:
    """
    Args:
        directory: a directory of the project tree.
        extensions: the suffixes to keep, None for every file.

    Returns:
        The project files below ``directory``.
    """
    prefix = f"{directory}{os.sep}"
    return [
        Path(path)
        for path in iter_project_files(extensions=extensions)
        if path.startswith(prefix)
    ]


@functools.cache
def _declared(root: Path) -> list[tuple[str, Any]]:
    models = declared_local_models(load_yaml(root / "group_vars" / "all" / "16_ai.yml"))
    templar = Templar(loader=DataLoader(), variables={"AI_LOCAL_MODELS": models})
    found: list[tuple[str, Any]] = [("group_vars/all/16_ai.yml", models)]
    files = [
        *sorted(root.glob(f"roles/*/{ROLE_FILE_META_SERVICES}")),
        *sorted(root.glob(f"roles/*/{ROLE_FILE_META_VARIANTS}")),
        *sorted(
            path
            for path in _files(root / "inventories", (".yml",))
            if path.name != RENDERED.name
        ),
    ]
    for path in files:
        found.extend(
            (path.relative_to(root).as_posix(), _rendered(templar, value))
            for value in _lists(load_yaml_any(path))
        )
    found.extend(
        (TEMPLATE.as_posix(), value) for value in _lists(_rendered_tools(root))
    )
    return [
        (origin, entry)
        for origin, value in found
        for entry in (value if isinstance(value, list) else [value])
    ]


def _refusals(root: Path) -> list[str]:
    return [
        f"{origin}: {entry.get('alias') if isinstance(entry, dict) else entry!r}: {refusal}"
        for origin, entry in _declared(root)
        for refusal in [local_model_refusal(entry)]
        if refusal
    ]


def _tag_pulls(root: Path) -> list[str]:
    return [
        f"{path.relative_to(root).as_posix()}:{number}"
        for path in sorted(_files(root / "roles", None))
        if path.suffix in _SCANNED or path.name.startswith("Dockerfile")
        for number, line in enumerate(read_text(str(path)).splitlines(), 1)
        if _TAG_PULL.search(line)
    ]


class TestLocalModelsPinned(unittest.TestCase):
    def test_every_preload_entry_is_pinned_to_one_file(self) -> None:
        refusals = _refusals(PROJECT_ROOT)
        self.assertFalse(
            refusals,
            "these preload entries name no file fixed to one commit with its "
            "sha256 and bytes, so a deploy would fetch whatever the source "
            "serves at that moment:\n  " + "\n  ".join(refusals),
        )

    def test_the_scan_reaches_every_source(self) -> None:
        reached = {origin.split("/", 1)[0] for origin, _ in _declared(PROJECT_ROOT)}
        self.assertEqual(_SOURCES, reached)

    def test_no_role_fetches_a_model_by_tag(self) -> None:
        pulls = _tag_pulls(PROJECT_ROOT)
        self.assertFalse(
            pulls,
            "these lines fetch a model by tag from the Ollama library, and a tag "
            "fixes no content; create the model from a pinned AI_LOCAL_MODELS "
            "file instead:\n  " + "\n  ".join(pulls),
        )


if __name__ == "__main__":
    unittest.main()
