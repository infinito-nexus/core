"""Lint guard: every ``templates/env/<name>.j2`` names a compose service.

``sys-svc-compose`` ``04_files.yml`` renders each ``templates/env/*.j2`` to
``<instance>/.env/<name>.env``, and ``sys-svc-container``'s base.yml.j2 wires
that file into the container whose ``service_name`` equals ``<name>``. The
file name is therefore the whole binding: a name that matches no service is
rendered to disk and loaded by nobody, and the service it was meant for
silently falls back to the role-wide ``templates/env.j2`` -- or to no
environment at all once that file is retired.

A file that does not name a service is only legitimate as a fragment another
env file pulls in::

    {% include 'roles/web-app-zammad/templates/env/railsserver.j2' %}

so shared values stay single-source instead of being copied per service.

That include is also how a per-service file reaches the shared container env
base: it replaces the role-wide ``templates/env.j2`` rather than adding to
it, so a service whose file includes neither the base nor the role env loses
``TZ`` and ``LANG``. The second rule here requires every env file to reach
``roles/sys-svc-container/templates/env.j2`` through some include chain.

Scope: roles that own a compose template. A role without one has no services
to name, and its ``templates/env/`` means something else -- ``sys-svc-rdbms``
writes per-consumer database env files from there.

Service names come from the ``{% set service_name = ... %}`` lines of the
role's compose templates, resolved through ``vars/main.yml`` and
``defaults/main.yml`` when the value is a variable. A name this lint cannot
resolve is reported rather than skipped, because an unresolved name would
make every file in the directory look unmatched.

Suppress a genuine exception with ``# nocheck: env-dir-service-name`` or
``# nocheck: env-dir-base-include`` in the env file.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.lint.ansible.test_env_base_include import BASE_REL
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.networks.reachability import NETWORKS
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
    ROLE_GLOB_TEMPL_COMPOSE_SIBLINGS,
    ROLE_GLOB_TEMPL_COMPOSE_VARIANTS,
)

from . import PROJECT_ROOT

RULE = "env-dir-service-name"
BASE_RULE = "env-dir-base-include"
ENV_DIR = "templates/env"

_SET_SERVICE_RE = re.compile(r"\{%-?\s*set\s+service_name\s*=\s*(?P<expr>.+?)\s*-?%\}")
_LABELLED_RE = re.compile(
    r"^['\"](?P<base>[\w-]+)['\"]\s*\|\s*labelled\([^,]+,\s*['\"](?P<separator>[^'\"]*)['\"]\s*\)$"
)
_INCLUDE_RE = re.compile(r"\{%-?\s*include\s+['\"](?P<path>[^'\"]+)['\"]")
_LITERAL_RE = re.compile(r"^(?P<quote>['\"])(?P<value>[^'\"]*)(?P=quote)$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENTITY_RE = re.compile(r"^(?:entity_name|\{\{\s*entity_name\s*\}\})$")
_NOCHECK_RE = re.compile(rf"#\s*nocheck:\s*{re.escape(RULE)}\b")
_BASE_NOCHECK_RE = re.compile(rf"#\s*nocheck:\s*{re.escape(BASE_RULE)}\b")


def _role_variables(role: Path) -> dict[str, object]:
    """Return the role's merged vars and defaults.

    Args:
        role: the role directory.
    """
    merged: dict[str, object] = {}
    for rel in (ROLE_FILE_DEFAULTS_MAIN, ROLE_FILE_VARS_MAIN):
        loaded = load_yaml_any(str(role / rel), default_if_missing={})
        if isinstance(loaded, dict):
            merged.update(loaded)
    return merged


def _compose_templates(role: Path) -> list[Path]:
    """Return every compose template of *role*.

    Args:
        role: the role directory.
    """
    main = role / ROLE_FILE_TEMPL_COMPOSE
    paths = {main} if main.is_file() else set()
    paths |= set(role.glob(ROLE_GLOB_TEMPL_COMPOSE_SIBLINGS))
    paths |= set(role.glob(ROLE_GLOB_TEMPL_COMPOSE_VARIANTS))
    return sorted(paths)


def _resolve(expr: str, variables: dict[str, object], role: Path) -> set[str]:
    """Return the service names *expr* can stand for, empty when unresolvable.

    A role served on several networks names one service per network through
    ``labelled``, whose label comes from the host's domains rather than from
    the template. Such an expression stands for the unsuffixed name plus one
    per label the network registry defines, so every file the role can need
    is still checked against a name a service really takes.

    Args:
        expr: the right-hand side of a ``set service_name`` statement.
        variables: the role's merged vars and defaults.
        role: the role directory.
    """
    expr = expr.strip()
    labelled = _LABELLED_RE.match(expr)
    if labelled:
        base = labelled.group("base")
        separator = labelled.group("separator")
        return {base} | {
            f"{base}{separator}{network.label}" for network in NETWORKS.values()
        }
    literal = _LITERAL_RE.match(expr)
    if literal:
        expr = literal.group("value").strip()
    elif _IDENTIFIER_RE.match(expr) and not _ENTITY_RE.match(expr):
        value = variables.get(expr)
        if not isinstance(value, str):
            return set()
        expr = value.strip()
    if _ENTITY_RE.match(expr):
        return {entity_name(role.name)}
    return set() if "{{" in expr else {expr}


def _service_names(role: Path) -> tuple[set[str], set[str]]:
    """Return the role's resolved service names and the unresolved expressions.

    Args:
        role: the role directory.
    """
    variables = _role_variables(role)
    resolved: set[str] = set()
    unresolved: set[str] = set()
    for path in _compose_templates(role):
        for match in _SET_SERVICE_RE.finditer(read_text(str(path))):
            expr = match.group("expr")
            names = _resolve(expr, variables, role)
            if names:
                resolved |= names
            else:
                unresolved.add(expr)
    return resolved, unresolved


def _include_targets(path: Path) -> set[Path]:
    """Return the templates *path* includes, resolved to absolute paths.

    Args:
        path: the template to scan.
    """
    role_templates = next(
        (p for p in path.parents if p.name == "templates"), path.parent
    )
    targets: set[Path] = set()
    for match in _INCLUDE_RE.finditer(read_text(str(path))):
        target = match.group("path")
        base = PROJECT_ROOT if target.startswith("roles/") else role_templates
        resolved = (base / target).resolve()
        if resolved != path.resolve():
            targets.add(resolved)
    return targets


def _included_paths(role: Path) -> set[Path]:
    """Return every template of *role* that another template includes.

    Args:
        role: the role directory.
    """
    prefix = f"{(role / 'templates').resolve()}/"
    included: set[Path] = set()
    for found in iter_project_files(extensions=(".j2",)):
        path = Path(found)
        if str(path.resolve()).startswith(prefix):
            included |= _include_targets(path)
    return included


def _reaches_base(path: Path, seen: set[Path]) -> bool:
    """Whether *path* includes the shared container env base, directly or not.

    Args:
        path: the template to scan.
        seen: paths already visited, guarding against an include cycle.
    """
    resolved = path.resolve()
    if resolved == (PROJECT_ROOT / BASE_REL).resolve():
        return True
    if resolved in seen or not path.is_file():
        return False
    seen.add(resolved)
    return any(_reaches_base(target, seen) for target in _include_targets(path))


def _offenders(role: Path) -> list[str]:
    """Return the rule violations of *role*, as repo-relative descriptions.

    Args:
        role: the role directory.
    """
    env_dir = role / ENV_DIR
    if not env_dir.is_dir() or not _compose_templates(role):
        return []

    services, unresolved = _service_names(role)
    included = _included_paths(role)
    found = [
        f"{role.name}: cannot resolve `{expr}` to a service name"
        for expr in sorted(unresolved)
    ]
    for path in sorted(env_dir.glob("*.j2")):
        text = read_text(str(path))
        if _NOCHECK_RE.search(text):
            continue
        if path.stem in services:
            continue
        if path.resolve() in included:
            continue
        found.append(str(path.relative_to(PROJECT_ROOT)))
    return found


def _base_offenders(role: Path) -> list[str]:
    """Return the env files of *role* that never reach the container base.

    Args:
        role: the role directory.
    """
    env_dir = role / ENV_DIR
    if not env_dir.is_dir() or not _compose_templates(role):
        return []
    return [
        str(path.relative_to(PROJECT_ROOT))
        for path in sorted(env_dir.glob("*.j2"))
        if not _BASE_NOCHECK_RE.search(read_text(str(path)))
        and not _reaches_base(path, set())
    ]


class TestEnvDirServiceNames(unittest.TestCase):
    def test_env_dir_files_name_a_service_or_are_included(self) -> None:
        offenders: list[str] = []
        for role in sorted((PROJECT_ROOT / "roles").iterdir()):
            if role.is_dir():
                offenders.extend(_offenders(role))

        report = "\n".join(f"  - {o}" for o in offenders)
        self.assertFalse(
            offenders,
            f"{len(offenders)} file(s) under templates/env/ name no compose "
            "service and are included by no other template:\n"
            f"{report}\n\n"
            "Rename the file to the service it configures, or have the service's "
            "own env file pull it in with "
            "`{% include 'roles/<role>/templates/env/<name>.j2' %}`.\n"
            f"Suppress a genuine exception with `# nocheck: {RULE}`.",
        )

    def test_env_dir_files_reach_the_container_base(self) -> None:
        offenders: list[str] = []
        for role in sorted((PROJECT_ROOT / "roles").iterdir()):
            if role.is_dir():
                offenders.extend(_base_offenders(role))

        report = "\n".join(f"  - {o}" for o in offenders)
        self.assertFalse(
            offenders,
            f"{len(offenders)} file(s) under templates/env/ never reach "
            f"{BASE_REL}, so their container loses TZ and LANG:\n"
            f"{report}\n\n"
            f"Add `{{% include '{BASE_REL}' %}}`, or include a template that "
            "already does, such as the role's own env.j2.\n"
            f"Suppress a genuine exception with `# nocheck: {BASE_RULE}`.",
        )


class TestServiceNameResolution(unittest.TestCase):
    def test_a_quoted_literal_resolves(self) -> None:
        role = PROJECT_ROOT / "roles/web-app-zammad"

        self.assertEqual({"nginx"}, _resolve("'nginx'", {}, role))

    def test_a_variable_holding_the_entity_name_resolves(self) -> None:
        role = PROJECT_ROOT / "roles/web-app-nextcloud"

        self.assertEqual(
            {"nextcloud"}, _resolve("NEXTCLOUD_SERVICE", _role_variables(role), role)
        )

    def test_an_unknown_variable_stays_unresolved(self) -> None:
        role = PROJECT_ROOT / "roles/web-app-zammad"

        self.assertEqual(set(), _resolve("NO_SUCH_SERVICE", {}, role))

    def test_a_labelled_name_covers_the_base_and_every_network_label(self) -> None:
        role = PROJECT_ROOT / "roles/web-svc-logout"

        names = _resolve("'logout' | labelled(logout_instance.label, '-')", {}, role)

        self.assertEqual({"logout", "logout-clearnet", "logout-onion"}, names)

    def test_the_base_is_reached_through_a_chain_of_includes(self) -> None:
        init = PROJECT_ROOT / "roles/web-app-zammad/templates/env/init.j2"

        self.assertEqual(set(), _include_targets(init) & {PROJECT_ROOT / BASE_REL})
        self.assertTrue(_reaches_base(init, set()))

    def test_zammad_resolves_every_service_through_its_vars(self) -> None:
        services, unresolved = _service_names(PROJECT_ROOT / "roles/web-app-zammad")

        self.assertEqual(set(), unresolved)
        self.assertIn("elasticsearch", services)

    def test_the_rule_catches_a_name_that_matches_no_service(self) -> None:
        role = PROJECT_ROOT / "roles/web-app-zammad"
        services, _ = _service_names(role)

        self.assertNotIn(
            "search",
            services,
            "the zammad search service is named elasticsearch; a file named "
            "search.j2 must stay a violation",
        )


if __name__ == "__main__":
    unittest.main()
