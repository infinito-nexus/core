"""Lint: no role references a retired role, no production role one beyond production.

Suppression: ``# nocheck: lifecycle-reference`` together with a ``Reason:`` on
the construct's line or in the comment block directly above it.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from utils.annotations.suppress import rule_and_reason
from utils.cache.files import iter_project_files, read_text
from utils.roles import lifecycle
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_DIR_META_ADDONS,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_TASKS_MAIN,
    ROLE_FILE_VARS_MAIN,
)
from utils.roles.meta_lookup import get_role_lifecycle

from . import PROJECT_ROOT, role_dirs
from .test_eol_dependency_requires_eol_consumer import (
    _addon_bridges,
    _addon_enabled,
    _addon_gate_re,
    _alias_keys,
    _block_field_line,
    _load_yaml,
    _provided_keys,
    _variant_field_line,
    _variant_section_span,
    _variant_spans,
    eol_service_keys,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

GROUP_VARS = "group_vars/all"
_RULE = "lifecycle-reference"
_YAML_DIRS = ("meta", "tasks", "handlers", "vars", "defaults")
_TEMPLATES = "templates"
_FLAG = "enabled"
_GATE_AFTER = re.compile(r"^\s+in\s+group_names\b")
_LOOKUP_BEFORE = re.compile(r"\b(?:lookup|query)\(\s*['\"][^'\"]+['\"]\s*,\s*$")


@dataclass(frozen=True)
class Reference:
    """One place a consumer names a target role.

    Attributes:
        consumer: the referencing role id, or ``group_vars/all``.
        target: the referenced role id.
        path: the file the reference sits in.
        line: its 1-based line.
        kind: what the reference is.
    """

    consumer: str
    target: str
    path: Path
    line: int
    kind: str


def quoted_ids(ids: set[str]) -> re.Pattern[str]:
    """A pattern matching any of *ids* in single or double quotes."""
    alternatives = "|".join(re.escape(i) for i in sorted(ids, key=len, reverse=True))
    return re.compile(rf"(['\"])({alternatives})\1")


def _quoted_kind(text: str, match: re.Match[str]) -> str:
    if _GATE_AFTER.match(text[match.end() :]):
        return "group_names presence gate on"
    if _LOOKUP_BEFORE.search(text[: match.start()]):
        return "lookup naming"
    return "quoted role id"


def _line_of(lines: list[str], first: int, last: int, needle: str) -> int:
    for index in range(first, min(last, len(lines) - 1) + 1):
        if needle in lines[index]:
            return index + 1
    return first + 1


def _scalars(node: Any, parent: str) -> Iterator[tuple[yaml.ScalarNode, str]]:
    if isinstance(node, yaml.ScalarNode):
        yield node, parent
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _scalars(item, parent)
    elif isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            yield from _scalars(key, parent)
            label = key.value if isinstance(key, yaml.ScalarNode) else parent
            yield from _scalars(value, str(label))


def yaml_references(
    consumer: str, path: Path, text: str, ids: set[str]
) -> list[Reference]:
    """Every reference to one of *ids* in one YAML file.

    Args:
        consumer: the role the file belongs to.
        path: the file.
        text: its content.
        ids: the role ids worth reporting.
    """
    pattern = quoted_ids(ids)
    try:
        documents = list(yaml.compose_all(text, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    lines = text.splitlines()
    found: list[Reference] = []
    for document in documents:
        for node, parent in _scalars(document, "document"):
            value = str(node.value)
            first, last = node.start_mark.line, node.end_mark.line
            if value.strip() in ids:
                found.append(
                    Reference(
                        consumer, value.strip(), path, first + 1, f"'{parent}' value"
                    )
                )
                continue
            found.extend(
                Reference(
                    consumer,
                    match.group(2),
                    path,
                    _line_of(lines, first, last, match.group(0)),
                    _quoted_kind(value, match),
                )
                for match in pattern.finditer(value)
            )
    return found


def template_references(
    consumer: str, path: Path, text: str, ids: set[str]
) -> list[Reference]:
    """Every quoted reference to one of *ids* on a non-comment template line.

    Args:
        consumer: the role the template belongs to.
        path: the template.
        text: its content.
        ids: the role ids worth reporting.
    """
    pattern = quoted_ids(ids)
    return [
        Reference(consumer, match.group(2), path, number, _quoted_kind(line, match))
        for number, line in enumerate(text.splitlines(), start=1)
        if not line.lstrip().startswith(("#", "{#"))
        for match in pattern.finditer(line)
    ]


def _switched_on(block: Any) -> bool:
    return isinstance(block, dict) and _FLAG in block and block[_FLAG] is not False


def service_key_references(role_dir: Path, keys: dict[str, str]) -> list[Reference]:
    """Blocks and variant pins of *role_dir* that switch on a key in *keys*.

    Args:
        role_dir: the consumer role directory.
        keys: service key to the target role providing it.
    """
    services_path = role_dir / ROLE_FILE_META_SERVICES
    services = _load_yaml(services_path)
    services = services if isinstance(services, dict) else {}
    lines = (
        read_text(str(services_path)).splitlines() if services_path.is_file() else []
    )
    found = [
        Reference(
            role_dir.name,
            target,
            services_path,
            _block_field_line(lines, key, _FLAG),
            f"services.{key}.{_FLAG} switches on",
        )
        for key, target in sorted(keys.items())
        if _switched_on(services.get(key))
    ]
    variants_path = role_dir / ROLE_FILE_META_VARIANTS
    variants = _load_yaml(variants_path)
    if not isinstance(variants, list):
        return found
    variant_lines = read_text(str(variants_path)).splitlines()
    spans = _variant_spans(variant_lines)
    for index, variant in enumerate(variants):
        pins = variant.get("services") if isinstance(variant, dict) else None
        span = spans[index] if index < len(spans) else (0, len(variant_lines))
        section = _variant_section_span(variant_lines, span, "services")
        found.extend(
            Reference(
                role_dir.name,
                target,
                variants_path,
                _variant_field_line(variant_lines, section, key, _FLAG),
                f"variant {index} pins services.{key}.{_FLAG} on",
            )
            for key, target in sorted(keys.items())
            if isinstance(pins, dict) and _switched_on(pins.get(key))
        )
    return found


def provider_keys(roles: dict[str, Path], targets: set[str]) -> dict[str, str]:
    """Service key to target role, for every key one of *targets* provides.

    Args:
        roles: role id to its directory.
        targets: the role ids whose keys to collect.
    """
    keys: dict[str, str] = {}
    for name in sorted(targets):
        entity = entity_name(name)
        services = _load_yaml(roles[name] / ROLE_FILE_META_SERVICES)
        if not entity or not isinstance(services, dict):
            continue
        provided = {
            entity,
            *_alias_keys(services, entity),
            *_provided_keys(services, entity),
        }
        keys.update(dict.fromkeys(provided, name))
    return keys


def contained_addon(role_dir: Path, path: Path, retired_keys: dict[str, str]) -> bool:
    """Whether an addon bridges a retired key behind a gate held unbindable.

    Args:
        role_dir: the role owning the addon.
        path: the addon file.
        retired_keys: the output of ``eol_service_keys``.
    """
    spec = _load_yaml(path)
    bridged = [k for k in _addon_bridges(role_dir, path.stem) if k in retired_keys]
    if not isinstance(spec, dict) or not bridged:
        return False
    enabled = _addon_enabled(spec)
    if enabled is False:
        return True
    return isinstance(enabled, str) and any(
        _addon_gate_re(role_dir.name, key).fullmatch(enabled.strip()) for key in bridged
    )


def _kind(role_dir: Path, path: Path) -> str | None:
    parts = path.relative_to(role_dir).parts
    if len(parts) > 1 and parts[0] in _YAML_DIRS and path.suffix == ".yml":
        return "yaml"
    if len(parts) > 1 and parts[0] == _TEMPLATES and path.suffix == ".j2":
        return "template"
    return None


def project_role_files(roles: list[Path]) -> dict[str, list[Path]]:
    """Role id to its ``.yml`` and ``.j2`` files.

    Args:
        roles: the role directories under ``roles/`` to index.
    """
    index: dict[str, list[Path]] = {role.name: [] for role in roles}
    roles_root = PROJECT_ROOT / "roles"
    for raw in iter_project_files(extensions=(".yml", ".j2")):
        path = Path(raw)
        if path.is_relative_to(roles_root):
            name = path.relative_to(roles_root).parts[0]
            if name in index:
                index[name].append(path)
    return index


def collect(
    roles: list[Path],
    ids: set[str],
    keys: dict[str, str],
    files: dict[str, list[Path]],
) -> list[Reference]:
    """Every reference the covered kinds find under *roles*.

    Args:
        roles: the role directories to scan as consumers.
        ids: role ids whose references are worth reporting.
        keys: service key to target role.
        files: role id to its files, as :func:`project_role_files` builds it.
    """
    retired_keys = eol_service_keys()
    found: list[Reference] = []
    for role_dir in roles:
        for path in sorted(files[role_dir.name]):
            kind = _kind(role_dir, path)
            if kind is None:
                continue
            text = read_text(str(path))
            if not any(i in text for i in ids):
                continue
            rel = path.relative_to(role_dir).as_posix()
            if rel.startswith(ROLE_DIR_META_ADDONS) and contained_addon(
                role_dir, path, retired_keys
            ):
                continue
            scan = yaml_references if kind == "yaml" else template_references
            found.extend(scan(role_dir.name, path, text, ids))
        if keys:
            found.extend(service_key_references(role_dir, keys))
    return found


def group_vars_references(ids: set[str]) -> list[Reference]:
    """Every reference to one of *ids* in ``group_vars/all``.

    Args:
        ids: role ids whose references are worth reporting.
    """
    found: list[Reference] = []
    for path in sorted((PROJECT_ROOT / GROUP_VARS).glob("*.yml")):
        text = read_text(str(path))
        if any(i in text for i in ids):
            found.extend(yaml_references(GROUP_VARS, path, text, ids))
    return found


def offences(
    references: list[Reference],
    status_of: dict[str, str | None],
    spot: lifecycle.Lifecycle,
) -> list[str]:
    """The references the rule forbids and no exemption or marker covers.

    Args:
        references: the output of :func:`collect`.
        status_of: role id to its lifecycle status.
        spot: the loaded ``meta/lifecycle.yml``.
    """
    found: list[str] = []
    for ref in references:
        migrated = spot.migrations.get(ref.consumer, {})
        if ref.consumer == ref.target or ref.target in migrated:
            continue
        why = spot.forbidden(status_of.get(ref.consumer), status_of.get(ref.target))
        if why is None:
            continue
        lines = read_text(str(ref.path)).splitlines() if ref.path.is_file() else []
        has_rule, has_reason = rule_and_reason(lines, ref.line, _RULE)
        if has_rule and has_reason:
            continue
        note = f"; its '# nocheck: {_RULE}' names no Reason:" if has_rule else ""
        where = (
            ref.path.relative_to(PROJECT_ROOT)
            if ref.path.is_relative_to(PROJECT_ROOT)
            else ref.path
        )
        found.append(
            f"{ref.consumer}: {where}:{ref.line} {ref.kind} "
            f"'{ref.target}', but {why}{note}"
        )
    return found


def judged_targets(
    status_of: dict[str, str | None], spot: lifecycle.Lifecycle
) -> tuple[set[str], set[str]]:
    """The role ids the rule can forbid, and the subset judged by service key.

    Args:
        status_of: role id to its lifecycle status.
        spot: the loaded ``meta/lifecycle.yml``.
    """
    retired = spot.with_flag(lifecycle.RETIRED)
    judged = retired | spot.beyond_production()
    targets = {name for name, status in status_of.items() if status in judged}
    return targets, {t for t in targets if status_of[t] not in retired}


def _tree() -> tuple[list[Path], dict[str, str | None], lifecycle.Lifecycle]:
    roles = role_dirs()
    return roles, {r.name: get_role_lifecycle(r) for r in roles}, lifecycle.load()


class TestLifecycleReferences(unittest.TestCase):
    def test_no_role_references_a_forbidden_lifecycle(self) -> None:
        roles, status_of, spot = _tree()
        targets, key_targets = judged_targets(status_of, spot)
        keys = provider_keys({r.name: r for r in roles}, key_targets)
        references = collect(
            roles, targets, keys, project_role_files(roles)
        ) + group_vars_references(targets)
        found = offences(references, status_of, spot)
        self.assertEqual(
            found,
            [],
            f"{lifecycle.FILE_META_LIFECYCLE} forbids these references: no role "
            "may name a retired role, and a production role may name no role "
            "beyond production. Drop the reference, record a migration pair in "
            f"{lifecycle.FILE_META_LIFECYCLE}, or mark it with '# nocheck: "
            f"{_RULE}' and a 'Reason:':\n  " + "\n  ".join(found),
        )

    def test_every_migration_pair_is_needed_and_live(self) -> None:
        roles, status_of, spot = _tree()
        by_name = {r.name: r for r in roles}
        files = project_role_files(roles)
        problems: list[str] = []
        for consumer, targets in sorted(spot.migrations.items()):
            for target in sorted(targets):
                if consumer not in by_name or target not in by_name:
                    problems.append(f"{consumer} -> {target}: no such role")
                elif spot.forbidden(status_of[consumer], status_of[target]) is None:
                    problems.append(f"{consumer} -> {target}: allowed anyway")
                elif not any(
                    ref.target == target
                    for ref in collect([by_name[consumer]], {target}, {}, files)
                ):
                    problems.append(f"{consumer} -> {target}: no reference left")
        self.assertEqual(
            problems,
            [],
            f"Every migrations pair in {lifecycle.FILE_META_LIFECYCLE} must name "
            "two roles, cover a reference the rule forbids, and still be "
            "used; drop the pairs that are not:\n  " + "\n  ".join(problems),
        )


_OLD = "web-app-old"
_DEP = "web-app-dep"
_STATUS = {
    "web-app-new": "beta",
    "web-app-young": "alpha",
    _OLD: "eol",
    _DEP: "deprecated",
}


class TestReferenceKinds(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _role(self, name: str, files: dict[str, str]) -> Path:
        role_dir = self.root / name
        for rel, text in files.items():
            path = role_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return role_dir

    def _offences(
        self,
        files: dict[str, str],
        consumer: str = "web-app-new",
        spot: lifecycle.Lifecycle | None = None,
        keys: dict[str, str] | None = None,
    ) -> list[str]:
        role_dir = self._role(consumer, files)
        index = {consumer: [role_dir / rel for rel in files]}
        references = collect([role_dir], {_OLD, _DEP}, keys or {}, index)
        return offences(references, _STATUS, spot or lifecycle.load())

    def test_a_presence_gate_on_a_retired_role_is_found(self) -> None:
        gate = f"email:\n  enabled: \"{{{{ '{_OLD}' in group_names }}}}\"\n"
        found = self._offences({ROLE_FILE_META_SERVICES: gate})
        self.assertEqual(1, len(found))
        self.assertIn("presence gate", found[0])

    def test_a_meta_main_dependency_is_found(self) -> None:
        found = self._offences(
            {ROLE_FILE_META_MAIN: f"dependencies:\n  - role: {_OLD}\n  - {_OLD}\n"}
        )
        self.assertEqual(2, len(found))

    def test_include_role_and_import_role_are_found(self) -> None:
        tasks = (
            f"- include_role:\n    name: {_OLD}\n"
            f"- ansible.builtin.import_role:\n    name: {_OLD}\n"
        )
        self.assertEqual(2, len(self._offences({ROLE_FILE_TASKS_MAIN: tasks})))

    def test_a_lookup_naming_the_role_is_found(self) -> None:
        found = self._offences(
            {ROLE_FILE_VARS_MAIN: f"X: \"{{{{ lookup('config', '{_OLD}', 'a') }}}}\"\n"}
        )
        self.assertEqual(1, len(found))
        self.assertIn("lookup naming", found[0])

    def test_a_run_after_entry_is_found(self) -> None:
        services = f"new:\n  run_after:\n    - {_OLD}\n  lifecycle: beta\n"
        found = self._offences({ROLE_FILE_META_SERVICES: services})
        self.assertEqual(1, len(found))
        self.assertIn(":3 ", found[0])

    def test_a_template_gate_is_found_and_a_comment_is_not(self) -> None:
        template = (
            f"# '{_OLD}' in group_names stays prose\n"
            f"{{% if '{_OLD}' in group_names %}}x{{% endif %}}\n"
        )
        found = self._offences({"templates/env.j2": template})
        self.assertEqual(1, len(found))
        self.assertIn(":2 ", found[0])

    def test_a_production_role_may_not_reference_a_deprecated_one(self) -> None:
        services = f"x:\n  run_after:\n    - {_DEP}\n"
        found = self._offences({ROLE_FILE_META_SERVICES: services})
        self.assertEqual(1, len(found))
        self.assertIn("beyond", found[0])

    def test_an_alpha_role_may_reference_a_deprecated_one(self) -> None:
        files = {ROLE_FILE_META_SERVICES: f"x:\n  run_after:\n    - {_DEP}\n"}
        self.assertEqual([], self._offences(files, consumer="web-app-young"))

    def test_a_service_block_switching_on_a_deprecated_key_is_found(self) -> None:
        files = {
            ROLE_FILE_META_SERVICES: "dep:\n  enabled: true\nother:\n  enabled: false\n",
            ROLE_FILE_META_VARIANTS: "- services:\n    dep:\n      enabled: true\n",
        }
        found = self._offences(files, keys={"dep": _DEP, "other": _DEP})
        self.assertEqual(2, len(found))

    def test_a_role_may_reference_itself(self) -> None:
        files = {ROLE_FILE_VARS_MAIN: f"application_id: {_OLD}\n"}
        self.assertEqual([], self._offences(files, consumer=_OLD))

    def test_a_migration_pair_is_exempt(self) -> None:
        spot = lifecycle.load()
        migrating = lifecycle.Lifecycle(
            spot.order,
            spot.statuses,
            spot.contexts,
            {"web-app-new": {_OLD: "imports its data"}},
        )
        files = {ROLE_FILE_TASKS_MAIN: f"- include_role:\n    name: {_OLD}\n"}
        self.assertEqual([], self._offences(files, spot=migrating))

    def test_a_marker_with_a_reason_suppresses_and_a_bare_one_does_not(self) -> None:
        reasoned = (
            "x:\n  # nocheck: lifecycle-reference  Reason: keeps the import path\n"
            f"  run_after: [{_OLD}]\n"
        )
        bare = f"x:\n  # nocheck: lifecycle-reference\n  run_after: [{_OLD}]\n"
        self.assertEqual([], self._offences({ROLE_FILE_META_SERVICES: reasoned}))
        found = self._offences(
            {ROLE_FILE_META_SERVICES: bare}, consumer="web-app-young"
        )
        self.assertEqual(1, len(found))
        self.assertIn("names no Reason", found[0])

    def test_a_contained_addon_is_skipped_and_a_live_one_is_not(self) -> None:
        gate = "{{ lookup('config', 'web-app-new', 'services.jira.enabled') | bool }}"
        body = f"bridges:\n  - jira\nurl: \"{{{{ lookup('tls', '{_OLD}', 'u') }}}}\"\n"
        addon = f"{ROLE_DIR_META_ADDONS}/a.yml"
        contained = {addon: f'enabled: "{gate}"\n{body}'}
        live = {addon: f'enabled: "{{{{ true }}}}"\n{body}'}
        self.assertEqual([], self._offences(contained))
        self.assertEqual(1, len(self._offences(live, consumer="web-app-young")))
