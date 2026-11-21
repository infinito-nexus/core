"""The translatable strings core ships, keyed by the ``msgctxt`` of their source."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from utils.annotations.suppress import is_suppressed_for_key
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.i18n.catalog import LOCALE_DIR, read_catalog
from utils.i18n.spans import matches
from utils.roles.custom import is_custom
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_META_RBAC

UNTRANSLATABLE_SUPPRESSION = "untranslatable"
CATEGORIES_FILE = Path("meta") / "categories.yml"
MENU_FILE = Path("roles") / "web-app-dashboard" / "vars" / "menu_categories.yml"
LOGOUT_FILE = Path("roles") / "web-app-keycloak" / "files" / "logout_i18n.yml"
PAUSED_FILE = Path("roles") / "sys-svc-app-control" / "files" / "paused_i18n.yml"
PROFILE_LOCK_FILE = (
    Path("roles") / "sys-front-inj-javascript" / "files" / "profile_lock_i18n.yml"
)
ACCESS_REQUEST_FILE = (
    Path("roles") / "web-svc-access-request" / "files" / "access_request_i18n.yml"
)
DOCS_TOOLING = Path("roles") / "web-app-docs" / "files" / "python"
CATEGORY_FIELDS = ("title", "description")
CONTEXT_FILES = {
    "category": CATEGORIES_FILE,
    "menu": MENU_FILE,
    "logout": LOGOUT_FILE,
    "paused": PAUSED_FILE,
    "profile_lock": PROFILE_LOCK_FILE,
    "access_request": ACCESS_REQUEST_FILE,
}
ROLE_CONTEXT_FILES = {"role": ROLE_FILE_META_MAIN, "rbac": ROLE_FILE_META_RBAC}
_NON_WORD = re.compile(r"\W+")


def _docs_sphinx_identity(root: Path, tooling: Path) -> dict[str, str]:
    """The Sphinx identity the documentation role configures.

    Args:
        root: repository root.
        tooling: directory holding the ``infinito_docs`` package.

    Returns:
        The rendered ``services.docs.sphinx`` mapping, read through the
        package that ships with the role so the values stay in services.yml.
    """
    spec = importlib.util.spec_from_file_location(
        "_infinito_docs_identity", tooling / "infinito_docs" / "identity.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.docs_sphinx_identity(root)


def role_context(role: str) -> str:
    """Return the ``msgctxt`` of the description of ``role``.

    Args:
        role: role directory name.
    """
    return f"role:{role}:description"


def category_context(path: str, field: str) -> str:
    """Return the ``msgctxt`` of a field of the category at ``path``.

    Args:
        path: dotted category path, e.g. ``web.app``.
        field: ``title`` or ``description``.
    """
    return f"category:{path}:{field}"


def menu_context(key: str, field: str) -> str:
    """Return the ``msgctxt`` of a field of the dashboard menu category ``key``.

    Args:
        key: menu category name as written in ``menu_categories.yml``.
        field: ``title`` or ``description``.
    """
    return f"menu:{key}:{field}"


def logout_context(key: str) -> str:
    """Return the ``msgctxt`` of the logout panel string ``key``.

    Args:
        key: key in ``logout_i18n.yml``.
    """
    return f"logout:{key}"


def paused_context(key: str) -> str:
    """Return the ``msgctxt`` of the paused page string ``key``.

    Args:
        key: key in ``paused_i18n.yml``.
    """
    return f"paused:{key}"


def profile_lock_context(key: str) -> str:
    """Return the ``msgctxt`` of the SSO profile lock string ``key``.

    Args:
        key: key in ``profile_lock_i18n.yml``.
    """
    return f"profile_lock:{key}"


def access_request_context(key: str) -> str:
    """Return the ``msgctxt`` of the access-request string ``key``.

    Args:
        key: key in ``access_request_i18n.yml``.
    """
    return f"access_request:{key}"


def rbac_context(application_id: str, role: str) -> str:
    """Return the ``msgctxt`` of the description of an application role.

    Args:
        application_id: the application's role name.
        role: role name in its ``meta/rbac.yml``.
    """
    return f"rbac:{application_id}:{role}:description"


def core_source(context: str) -> Path:
    """Return the file a ``core`` message was extracted from.

    Args:
        context: the ``msgctxt`` one of the context functions above wrote.

    Returns:
        The path relative to the repository root.

    Raises:
        ValueError: no extractor of this module writes that context.
    """
    kind, _, rest = context.partition(":")
    if kind in ROLE_CONTEXT_FILES:
        return Path("roles") / rest.partition(":")[0] / ROLE_CONTEXT_FILES[kind]
    if kind in CONTEXT_FILES:
        return CONTEXT_FILES[kind]
    raise ValueError(f"no extractor writes the context {context!r}")


def _load(path: Path):
    return load_yaml_any(path)


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def role_messages(root: Path) -> list[tuple[str, str]]:
    messages = []
    roles = root / "roles"
    for main in sorted(roles.glob(f"*/{ROLE_FILE_META_MAIN}")):
        role = main.relative_to(roles).parts[0]
        if is_custom(role):
            continue
        galaxy_info = (_load(main) or {}).get("galaxy_info") or {}
        description = _text(galaxy_info.get("description"))
        if description:
            messages.append((role_context(role), description))
    return messages


def category_messages(root: Path) -> list[tuple[str, str]]:
    messages = []

    def walk(node: dict, path: list[str]) -> None:
        for key, value in node.items():
            if not isinstance(value, dict):
                continue
            dotted = ".".join([*path, key])
            for field in CATEGORY_FIELDS:
                text = _text(value.get(field))
                if text:
                    messages.append((category_context(dotted, field), text))
            walk(value, [*path, key])

    walk(_load(root / CATEGORIES_FILE)["roles"], [])
    return messages


def menu_messages(root: Path) -> list[tuple[str, str]]:
    messages = []

    def walk(folders: dict) -> None:
        for key, entry in folders.items():
            messages.append((menu_context(key, "title"), key))
            description = _text(entry.get("description"))
            if description:
                messages.append((menu_context(key, "description"), description))
            walk(entry.get("children") or {})

    walk(_load(root / MENU_FILE)["portfolio_menu_categories"])
    return messages


def logout_messages(root: Path) -> list[tuple[str, str]]:
    return [
        (logout_context(key), _text(text))
        for key, text in _load(root / LOGOUT_FILE).items()
    ]


def paused_messages(root: Path) -> list[tuple[str, str]]:
    return [
        (paused_context(key), _text(text))
        for key, text in _load(root / PAUSED_FILE).items()
    ]


def profile_lock_messages(root: Path) -> list[tuple[str, str]]:
    return [
        (profile_lock_context(key), _text(text))
        for key, text in _load(root / PROFILE_LOCK_FILE).items()
    ]


def access_request_messages(root: Path) -> list[tuple[str, str]]:
    return [
        (access_request_context(key), _text(text))
        for key, text in _load(root / ACCESS_REQUEST_FILE).items()
    ]


def rbac_messages(root: Path) -> list[tuple[str, str]]:
    messages = []
    roles = root / "roles"
    for declaration in sorted(roles.glob(f"*/{ROLE_FILE_META_RBAC}")):
        application_id = declaration.relative_to(roles).parts[0]
        if is_custom(application_id):
            continue
        for role, spec in ((_load(declaration) or {}).get("roles") or {}).items():
            description = _text((spec or {}).get("description"))
            if description:
                messages.append((rbac_context(application_id, role), description))
    return messages


def core_messages(root: Path) -> list[tuple[str, str]]:
    """Return every message of the ``core`` domain.

    Args:
        root: repository root.

    Returns:
        ``(msgctxt, msgid)`` pairs in source order.
    """
    return [
        *role_messages(root),
        *category_messages(root),
        *menu_messages(root),
        *logout_messages(root),
        *paused_messages(root),
        *profile_lock_messages(root),
        *access_request_messages(root),
        *rbac_messages(root),
    ]


def keyed_messages(root: Path, domain: str) -> list[tuple[str, str]]:
    """Return the messages of a domain that lives outside core.

    Args:
        root: directory holding ``locale/``, e.g. a custom role.
        domain: gettext domain; ``locale/<domain>.yml`` maps each key to its
            English text.

    Returns:
        ``(msgctxt, msgid)`` pairs in source order, ``msgctxt`` being
        ``<domain>:<key>``.
    """
    return [
        (f"{domain}:{key}", _text(text))
        for key, text in _load(root / LOCALE_DIR / f"{domain}.yml").items()
    ]


def keyed_translatable(root: Path, domain: str) -> frozenset[str]:
    """Return the contexts a ``# nocheck: untranslatable`` marker keeps.

    The marker sits on a key's line of ``locale/<domain>.yml`` or the line
    above it and keeps that message in the template although
    :func:`utils.i18n.untranslatable.untranslatable` would drop it, e.g. the
    label ``Matrix`` of a view rather than the app. It is read from the raw
    lines because the cached YAML loader drops comments.

    Args:
        root: directory holding ``locale/``.
        domain: gettext domain of ``locale/<domain>.yml``.

    Returns:
        The ``<domain>:<key>`` contexts of the marked keys.
    """
    path = root / LOCALE_DIR / f"{domain}.yml"
    lines = read_text(str(path)).splitlines()
    return frozenset(
        f"{domain}:{key}"
        for key in _load(path)
        if is_suppressed_for_key(lines, key, UNTRANSLATABLE_SUPPRESSION)
    )


def _extraction_sources(root: Path) -> list[str]:
    listing = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [
        relative
        for relative in filter(None, listing.split("\0"))
        if Path(relative).parts[0] != str(LOCALE_DIR) and (root / relative).is_file()
    ]


def _copy_working_tree(root: Path, target: Path) -> None:
    for relative in _extraction_sources(root):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)


def _words(text: str) -> str:
    return f" {_NON_WORD.sub(' ', text.lower()).strip()} "


def _prose_pieces(msgid: str) -> list[str]:
    pieces, position = [], 0
    for start, end in [*matches(msgid), (len(msgid), len(msgid))]:
        piece = _words(msgid[position:start])
        if piece.strip():
            pieces.append(piece)
        position = end
    return pieces


def _carries_in_order(words: str, pieces: list[str]) -> bool:
    position = 0
    for piece in pieces:
        found = words.find(piece, position)
        if found < 0:
            return False
        position = found + len(piece) - 1
    return True


@lru_cache(maxsize=1)
def _source_words(root: Path) -> tuple[tuple[str, str], ...]:
    texts = []
    for relative in _extraction_sources(root):
        try:
            text = read_text(str(root / relative))
        except UnicodeDecodeError:
            continue
        texts.append((relative, _words(text)))
    return tuple(texts)


def docs_sources(root: Path, msgid: str) -> list[str]:
    """Return the extraction sources that carry the words of a ``docs`` message.

    Sphinx extracts this domain with ``gettext_location = False``, so its
    catalogs name no file and stay byte-stable while a page moves. The pages
    it reads are this module's working-tree copy, some of them generated from
    a role's ``meta/main.yml`` or converted from its ``README.md`` on the
    way, which changes their markup but keeps their words in order. A
    generator that also rewrites a link target or renders a template fills
    only protected spans, so a message no file carries whole is looked up by
    its prose between those spans, in order.

    Args:
        root: repository root.
        msgid: the message as the catalog holds it.

    Returns:
        Paths relative to ``root``, sorted; empty when no source carries the
        message any more, which the next extraction drops it for.
    """
    whole = _words(msgid)
    if not whole.strip():
        return []
    sources = _source_words(root)
    found = [relative for relative, words in sources if whole in words]
    if not found:
        pieces = _prose_pieces(msgid)
        found = [
            relative
            for relative, words in sources
            if pieces and _carries_in_order(words, pieces)
        ]
    return sorted(found)


def docs_template(root: Path, jobs: int):
    """Return the template of the ``docs`` domain, built from a copy of the working tree.

    Args:
        root: repository root.
        jobs: parallel Sphinx processes.
    """
    with tempfile.TemporaryDirectory(prefix="infinito-i18n-docs-") as scratch:
        src = Path(scratch) / "src"
        pot = Path(scratch) / "docs.pot"
        _copy_working_tree(root, src)
        tooling = root / DOCS_TOOLING
        env = {
            **os.environ,
            **_docs_sphinx_identity(root, tooling),
            "PYTHONPATH": os.pathsep.join([str(tooling), str(root)]),
        }
        subprocess.run(
            [
                sys.executable,
                "-P",
                "-m",
                "infinito_docs.i18n",
                "--src",
                str(src),
                "--output",
                str(pot),
                "--jobs",
                str(jobs),
            ],
            check=True,
            env=env,
        )
        return read_catalog(pot)
