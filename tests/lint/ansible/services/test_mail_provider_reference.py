from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.mail.provider import (
    MAIL_SERVICE_KEY,
    MAIL_WRAPPER,
    PROVIDER_KEY,
    provider_roles,
)
from utils.roles.applications.services.registry import is_explicit_truth
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_META_VARIANTS

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
GROUP_VARS_DIR = PROJECT_ROOT / "group_vars" / "all"
RULE = "mail-provider-reference"
_YAML_DIRS = ("meta", "tasks", "handlers", "vars", "defaults")
_TEMPLATES = "templates"
_FLAGS = ("enabled", "shared")


def _id_pattern(ids: list[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])({alternatives})(?![\w-])")


def line_references(
    text: str, ids: list[str], *, template: bool
) -> list[tuple[int, str]]:
    """Every non-comment line naming one of *ids*.

    Args:
        text: the file content.
        ids: the concrete provider role ids.
        template: ``True`` for a Jinja template, ``False`` for YAML.

    Returns:
        ``(1-based line, provider id)`` per match.
    """
    pattern = _id_pattern(ids)
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(("#", "{#")):
            continue
        code = line if template else line.split(" #", 1)[0]
        found.extend((number, match.group(1)) for match in pattern.finditer(code))
    return found


def offences(
    consumer: str, path: Path, text: str, ids: list[str], *, template: bool
) -> list[str]:
    """Findings for one consumer file.

    Args:
        consumer: the role id owning the file, or ``group_vars/all``.
        path: the file, for the report.
        text: its content.
        ids: the concrete provider role ids.
        template: ``True`` for a Jinja template, ``False`` for YAML.

    Returns:
        One message per unsuppressed reference.
    """
    lines = text.splitlines()
    return [
        f"{consumer}: {path}:{number} names the concrete mail provider "
        f"'{provider}'; reference '{MAIL_WRAPPER}' instead, or mark the line "
        f"'# nocheck: {RULE}'"
        for number, provider in line_references(text, ids, template=template)
        if not is_suppressed_at(lines, number, RULE)
    ]


def _scan_kind(role_dir: Path, path: Path) -> str | None:
    parts = path.relative_to(role_dir).parts
    if len(parts) > 1 and parts[0] in _YAML_DIRS and path.suffix == ".yml":
        return "yaml"
    if len(parts) > 1 and parts[0] == _TEMPLATES and path.suffix == ".j2":
        return "template"
    return None


def repository_offences(ids: list[str], exempt: set[str]) -> list[str]:
    """Findings across every role and ``group_vars/all``.

    Args:
        ids: the concrete provider role ids.
        exempt: role ids allowed to name them.

    Returns:
        One message per unsuppressed reference.
    """
    found: list[str] = []
    for raw in sorted(iter_project_files(extensions=(".yml", ".j2"))):
        path = Path(raw)
        if path.is_relative_to(GROUP_VARS_DIR) and path.suffix == ".yml":
            consumer, kind = "group_vars/all", "yaml"
        elif path.is_relative_to(ROLES_DIR):
            consumer = path.relative_to(ROLES_DIR).parts[0]
            kind = _scan_kind(ROLES_DIR / consumer, path)
        else:
            continue
        if kind is None or consumer in exempt:
            continue
        text = read_text(str(path))
        if not any(i in text for i in ids):
            continue
        found.extend(
            offences(
                consumer,
                path.relative_to(PROJECT_ROOT),
                text,
                ids,
                template=kind == "template",
            )
        )
    return found


def wrapper_problems(
    services: dict[str, Any], variants: list[Any], providers: list[str]
) -> list[str]:
    """Disagreements inside the wrapper's own meta files.

    Args:
        services: the wrapper's ``meta/services.yml``.
        variants: the wrapper's ``meta/variants.yml``.
        providers: :func:`provider_roles`, default provider first.

    Returns:
        One message per disagreement.
    """
    primary = services.get(MAIL_SERVICE_KEY) or {}
    provider = str(primary.get(PROVIDER_KEY) or "").strip()
    problems: list[str] = []
    if primary.get("run_after") != [provider]:
        problems.append(
            f"services.{MAIL_SERVICE_KEY}.run_after must be exactly [{provider}]"
        )
    block = services.get(entity_name(provider)) or {}
    if not all(is_explicit_truth(block.get(flag)) for flag in _FLAGS):
        problems.append(
            f"services.{entity_name(provider)} must pull '{provider}' in with "
            "dynamic enabled and shared flags"
        )
    alternatives = {entity_name(role) for role in providers if role != provider}
    if not variants:
        problems.append("meta/variants.yml must declare the wrapper's variants")
    for index, variant in enumerate(variants):
        pins = (variant or {}).get("services") or {}
        own = pins.get(entity_name(provider)) or {}
        if own.get("enabled") is not True or own.get("shared") is not True:
            problems.append(f"variant {index} must keep '{provider}' on")
        override = (pins.get(MAIL_SERVICE_KEY) or {}).get(PROVIDER_KEY, provider)
        if override != provider:
            problems.append(f"variant {index} selects '{override}'")
        problems.extend(
            f"variant {index} pins the alternative provider key '{key}'"
            for key in sorted(alternatives & set(pins))
        )
    return problems


def _load(path: Path, empty: Any) -> Any:
    data = load_yaml_any(str(path), default_if_missing=empty)
    return data if isinstance(data, type(empty)) else empty


class TestMailProviderReference(unittest.TestCase):
    def test_no_role_names_a_concrete_mail_provider(self) -> None:
        providers = provider_roles(ROLES_DIR)
        found = repository_offences(providers, {MAIL_WRAPPER, *providers})
        self.assertEqual(
            [],
            found,
            f"{len(found)} reference(s) name a concrete mail provider; roles "
            f"depend on '{MAIL_WRAPPER}', which dispatches to "
            f"{providers[0]}:\n  " + "\n  ".join(found),
        )

    def test_the_wrapper_agrees_with_its_provider(self) -> None:
        wrapper = ROLES_DIR / MAIL_WRAPPER
        problems = wrapper_problems(
            _load(wrapper / ROLE_FILE_META_SERVICES, {}),
            _load(wrapper / ROLE_FILE_META_VARIANTS, []),
            provider_roles(ROLES_DIR),
        )
        self.assertEqual(
            [],
            problems,
            f"{MAIL_WRAPPER} disagrees with itself:\n  " + "\n  ".join(problems),
        )

    def test_the_scan_knows_more_than_one_provider(self) -> None:
        self.assertGreater(len(provider_roles(ROLES_DIR)), 1)


_IDS = ["web-app-old", "web-app-new"]
_PATH = Path("roles") / "web-app-x" / ROLE_FILE_META_SERVICES
_SERVICES = {
    MAIL_SERVICE_KEY: {PROVIDER_KEY: "web-app-new", "run_after": ["web-app-new"]},
    "new": {
        "enabled": "{{ 'web-app-new' in group_names }}",
        "shared": "{{ 'web-app-new' in group_names }}",
    },
}
_KEEP = {"services": {"new": {"enabled": True, "shared": True}}}


class TestNegativeControls(unittest.TestCase):
    def _found(self, text: str, *, template: bool = False) -> list[str]:
        return offences("web-app-x", _PATH, text, _IDS, template=template)

    def test_a_run_after_entry_is_found(self) -> None:
        found = self._found("x:\n  run_after:\n    - web-app-new\n")
        self.assertEqual(1, len(found))
        self.assertIn(MAIL_WRAPPER, found[0])

    def test_a_flow_list_and_a_gate_are_found(self) -> None:
        text = (
            "x:\n  required_by:\n    roles: [web-app-old]\n"
            "email:\n  enabled: \"{{ 'web-app-new' in group_names }}\"\n"
        )
        self.assertEqual(2, len(self._found(text)))

    def test_a_template_lookup_is_found_and_a_jinja_comment_is_not(self) -> None:
        text = "{# web-app-old #}\n{{ lookup('config', 'web-app-old', 'x') }}\n"
        found = self._found(text, template=True)
        self.assertEqual(1, len(found))
        self.assertIn(":2 ", found[0])

    def test_comments_and_longer_ids_are_not_references(self) -> None:
        text = "# web-app-old\nx: web-app-new-ui # web-app-new\n"
        self.assertEqual([], self._found(text))

    def test_the_marker_suppresses(self) -> None:
        text = f"x:\n  # nocheck: {RULE}\n  roles: [web-app-old]\n"
        self.assertEqual([], self._found(text))

    def test_a_consistent_wrapper_passes(self) -> None:
        self.assertEqual(
            [],
            wrapper_problems(_SERVICES, [_KEEP, _KEEP], ["web-app-new", "web-app-old"]),
        )

    def test_a_variant_switching_the_provider_off_is_found(self) -> None:
        off = {"services": {"new": {"enabled": False, "shared": False}}}
        problems = wrapper_problems(_SERVICES, [_KEEP, off], _IDS[::-1])
        self.assertEqual(["variant 1 must keep 'web-app-new' on"], problems)

    def test_a_variant_selecting_the_alternative_is_found(self) -> None:
        swap = {
            "services": {
                "new": {"enabled": True, "shared": True},
                "old": {"enabled": True, "shared": True},
                MAIL_SERVICE_KEY: {PROVIDER_KEY: "web-app-old"},
            }
        }
        problems = wrapper_problems(_SERVICES, [swap], _IDS[::-1])
        self.assertEqual(2, len(problems))

    def test_a_run_after_drifting_from_the_provider_is_found(self) -> None:
        drift = {
            **_SERVICES,
            MAIL_SERVICE_KEY: {
                PROVIDER_KEY: "web-app-new",
                "run_after": ["web-app-old"],
            },
        }
        problems = wrapper_problems(drift, [_KEEP], _IDS[::-1])
        self.assertEqual(1, len(problems))
        self.assertIn("run_after", problems[0])


if __name__ == "__main__":
    unittest.main()
