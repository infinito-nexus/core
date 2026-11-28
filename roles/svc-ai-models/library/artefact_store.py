#!/usr/bin/python

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
import zipfile
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from ansible.module_utils.basic import AnsibleModule

if TYPE_CHECKING:
    from collections.abc import Callable

DOCUMENTATION = r"""
---
module: artefact_store
short_description: Hold every pinned artefact once in a content-addressed store
description:
  - Fetches each digest of the given artefacts once into <path>/<sha256>,
    verifies its sha256 and size, and fails naming every artefact that is
    missing or does not match. A digest the store already holds is not
    fetched or hashed again. An artefact with an unpack path is unpacked once into it,
    read-only, and refused when its archive lists other than its declared
    unpacked_bytes.
options:
  path:
    description:
      - The store directory on the target host.
    required: true
    type: path
  artefacts:
    description:
      - The records of the cache_artefacts lookup, each with name, url, sha256
        and bytes.
    required: true
    type: list
    elements: dict
  fetch:
    description:
      - When false, nothing is fetched and a missing or broken artefact fails
        the task, so a consumer refuses to start without its artefacts.
    type: bool
    default: true
  timeout:
    description:
      - Seconds a fetch may stall before it fails.
    type: int
    default: 600
  verify:
    description:
      - C(presence) hashes only what this run fetches; a held entry passes on
        its presence, size and read-only mode and an unpacked package on its
        completed directory, since only verified content enters the store.
        C(full) re-hashes every held file and re-sums every unpacked package.
    type: str
    choices: [presence, full]
    default: presence
author:
  - Kevin Veen-Birkenbach
"""

EXAMPLES = r"""
- name: Prefetch the artefacts of the deployed roles
  artefact_store:
    path: /var/cache/infinito/core/cache/models
    artefacts: "{{ lookup('cache_artefacts', base=MODELS_ARTEFACT_BASE).values() | list }}"
"""

RETURN = r"""
fetched:
  description: Names of the artefacts this run fetched.
  type: list
  returned: success
held:
  description: Names of the artefacts the store already held intact.
  type: list
  returned: success
linked:
  description: Names of the artefacts whose tree link this run created.
  type: list
  returned: success
unpacked:
  description: Names of the artefacts this run unpacked.
  type: list
  returned: success
"""

CHUNK = 1 << 20
MODE = 0o444
DIR_MODE = 0o555
WRITABLE = 0o222
FULL = "full"
PRESENCE = "presence"
PART_SUFFIX = ".part"
PACKAGE_METADATA = "metadata.json"
USER_AGENT = "infinito-nexus-artefact-store"


class ArtefactError(Exception):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def mismatch(path: Path, sha256: str, size: int, *, full: bool) -> str:
    """
    Args:
        path: the file to check.
        sha256: the declared digest.
        size: the declared size in bytes.
        full: hash the file; otherwise a read-only file of the declared size
            passes, since only a verified file is renamed into the store.

    Returns:
        Why *path* is not the declared file; empty when it is.
    """
    if not path.is_file():
        return f"{path} is missing"
    stats = path.stat()
    if stats.st_size != size:
        return f"{path} holds {stats.st_size} bytes, not the declared {size}"
    if full:
        found = _sha256(path)
        if found != sha256:
            return f"{path} hashes to {found}, not the declared {sha256}"
    elif stats.st_mode & WRITABLE:
        return f"{path} is writable, so it is no verified store entry"
    return ""


def _by_digest(artefacts: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for artefact in artefacts:
        grouped.setdefault(str(artefact["sha256"]), []).append(artefact)
    return grouped


def download(url: str, dest: Path, timeout: int) -> None:
    """
    Args:
        url: the artefact url, through the cache base when one is set.
        dest: the file the response body is written to.
        timeout: seconds a read may stall.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 https or cache-base url the manifest contract already checked
    with (
        urllib.request.urlopen(request, timeout=timeout) as response,  # noqa: S310 https or cache-base url the manifest contract already checked
        dest.open("wb") as handle,
    ):
        for block in iter(lambda: response.read(CHUNK), b""):
            handle.write(block)


def _fetched(
    root: Path, sha256: str, group: list[dict], fetch: Callable[[str, Path], None]
) -> str:
    part = root / f".{sha256}{PART_SUFFIX}"
    url = str(group[0]["url"])
    try:
        fetch(url, part)
    except OSError as exc:
        part.unlink(missing_ok=True)
        return f"fetching {url} failed: {exc}"
    problem = mismatch(part, sha256, int(group[0]["bytes"]), full=True)
    if problem:
        part.unlink(missing_ok=True)
        return problem
    part.chmod(MODE)
    part.replace(root / sha256)
    return ""


def store(
    root: Path,
    artefacts: list[dict],
    fetch: Callable[[str, Path], None] | None,
    *,
    full: bool = False,
) -> dict[str, list[str]]:
    """
    Args:
        root: the store directory; it must exist.
        artefacts: records with ``name``, ``url``, ``sha256`` and ``bytes``,
            optionally ``tree`` and ``unpack`` paths below *root*, the latter
            with ``unpacked_bytes``.
        fetch: writes a url's body to a path; None only verifies.
        full: re-hash every held file and re-sum every unpacked directory;
            otherwise a held entry passes on its presence, size and read-only
            mode, and an unpacked directory on its completed presence.

    Returns:
        ``fetched``, ``held``, ``linked`` and ``unpacked``, the artefact names
        per outcome; ``linked`` names every ``tree`` link and ``unpacked``
        every ``unpack`` directory this run created.

    Raises:
        ArtefactError: an artefact is missing, could not be fetched, does not
            match its digest or size, lacks its ``tree`` link or unpacked
            directory while only verifying, or lists other than its
            ``unpacked_bytes``; every such artefact is named.
    """
    outcome: dict[str, list[str]] = {
        "fetched": [],
        "held": [],
        "linked": [],
        "unpacked": [],
    }
    problems: list[str] = []
    for sha256, group in sorted(_by_digest(artefacts).items()):
        names = sorted(str(item["name"]) for item in group)
        reason = mismatch(root / sha256, sha256, int(group[0]["bytes"]), full=full)
        if not reason:
            outcome["held"].extend(names)
        else:
            problem = reason if fetch is None else _fetched(root, sha256, group, fetch)
            if problem:
                problems.append(f"artefact {', '.join(names)}: {problem}")
                continue
            outcome["fetched"].extend(names)
        for item in group:
            problem = _tree(
                root, item, create=fetch is not None, linked=outcome["linked"]
            ) or _unpack(
                root,
                item,
                create=fetch is not None,
                full=full,
                unpacked=outcome["unpacked"],
            )
            if problem:
                problems.append(f"artefact {item['name']}: {problem}")
    if problems:
        raise ArtefactError("; ".join(problems))
    return outcome


def _tree(root: Path, artefact: dict, *, create: bool, linked: list[str]) -> str:
    tree = str(artefact.get("tree") or "")
    if not tree:
        return ""
    link, target = root / tree, root / str(artefact["sha256"])
    if link.is_symlink() and link.readlink() == target:
        return ""
    if not create:
        return f"{link} does not link to {target}"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    link.symlink_to(target)
    linked.append(str(artefact["name"]))
    return ""


def _read_only(tree: Path) -> None:
    for parent, _, files in os.walk(tree):
        Path(parent).chmod(DIR_MODE)
        for name in files:
            (Path(parent) / name).chmod(MODE)


def _held_bytes(tree: Path) -> int:
    return sum(
        (Path(parent) / name).stat().st_size
        for parent, _, files in os.walk(tree)
        for name in files
    )


def _unpack(
    root: Path, artefact: dict, *, create: bool, full: bool, unpacked: list[str]
) -> str:
    unpack = str(artefact.get("unpack") or "")
    if not unpack:
        return ""
    dest, archive = root / unpack, root / str(artefact["sha256"])
    declared = int(artefact["unpacked_bytes"])
    if (dest / PACKAGE_METADATA).is_file():
        held = _held_bytes(dest) if full else declared
        if held != declared:
            return (
                f"{dest} holds {held} bytes, not the declared unpacked_bytes {declared}"
            )
        if create:
            _read_only(dest)
        return ""
    if not create:
        return f"{dest} holds no unpacked package"
    stage = dest.parent / f".{dest.name}{PART_SUFFIX}"
    shutil.rmtree(stage, ignore_errors=True)
    try:
        with zipfile.ZipFile(archive) as packed:
            listed = sum(info.file_size for info in packed.infolist())
            if listed != declared:
                return (
                    f"{archive} lists {listed} unpacked bytes, not the declared "
                    f"unpacked_bytes {declared}"
                )
            packed.extractall(stage)
    except zipfile.BadZipFile as exc:
        return f"{archive} is no zip archive: {exc}"
    tops = list(stage.iterdir()) if stage.is_dir() else []
    if len(tops) != 1 or not (tops[0] / PACKAGE_METADATA).is_file():
        shutil.rmtree(stage, ignore_errors=True)
        return f"{archive} holds no single package directory with {PACKAGE_METADATA}"
    tops[0].rename(dest)
    stage.rmdir()
    _read_only(dest)
    unpacked.append(str(artefact["name"]))
    return ""


def run_module() -> None:
    module = AnsibleModule(
        argument_spec={
            "path": {"type": "path", "required": True},
            "artefacts": {"type": "list", "elements": "dict", "required": True},
            "fetch": {"type": "bool", "default": True},
            "timeout": {"type": "int", "default": 600},
            "verify": {
                "type": "str",
                "choices": [PRESENCE, FULL],
                "default": PRESENCE,
            },
        },
        supports_check_mode=False,
    )
    root = Path(module.params["path"])
    fetch = None
    if module.params["fetch"]:
        root.mkdir(parents=True, exist_ok=True)
        fetch = partial(download, timeout=module.params["timeout"])
    try:
        outcome = store(
            root,
            module.params["artefacts"],
            fetch,
            full=module.params["verify"] == FULL,
        )
    except ArtefactError as exc:
        module.fail_json(msg=str(exc))
    module.exit_json(
        changed=bool(outcome["fetched"] or outcome["linked"] or outcome["unpacked"]),
        **outcome,
    )


def main() -> None:
    run_module()


if __name__ == "__main__":
    main()
