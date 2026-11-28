"""Lint: every sign-in method of an application follows the login-method table.

A role whose own sign-in page sits behind native OIDC or SAML declares
``<entity>.login.method.<method>.enabled`` in ``meta/services.yml`` for every
method the page can offer, and each default is the ``login_method`` lookup of
that role and method. The lookup holds the one table that decides which methods
a mode turns on (``utils.roles.applications.login``), so a role cannot drift
from it; an inventory still overrides a single flag. A role in
``NATIVE_BESIDE_SSO`` defaults ``native`` to ``true`` instead, because its SSO
entry needs the native form. The ``2fa`` method also declares ``enforced``,
whose default is ``true``, or ``false`` for a role in
``OFFERED_ONLY`` whose enforcement would lock out the deploy's own accounts;
every variant of the role with SSO off sets it to ``false``, so its automated
logins skip enrollment, unless the variant exists to prove the enforced
enrollment and marks its ``enforced`` key.

Every declared flag is read by deploy code: a template, task, meta or file of a
role reads it, directly or through the ``vars/main.yml`` variables built on it.
A read only by a Playwright file or a README switches nothing. ``UNSWITCHED``
lists the methods whose application has no switch, each with its reason.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: login-methods`` plus a reason, on or directly above the role's
  ``sso:`` key, for a role whose sign-in offers one method only.
* The same marker on or directly above the
  ``services.<entity>.login.method.2fa.enforced`` key of an SSO-off variant in
  ``meta/variants.yml``, for the one variant per role that keeps the enforcement
  on so its Playwright spec proves the enrollment; a marker on a second variant
  of the role, on a variant that has SSO on or on an enforcement switched off is
  a finding.
"""

from __future__ import annotations

import os
import re
import unittest
from collections.abc import Iterable, Mapping
from pathlib import PurePath

import yaml

from utils.annotations.suppress import has_rule_with_reason
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.meta.scan import ROLES_DIR, iter_role_dirs
from utils.roles.applications.login import METHODS
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_VARIANTS,
    ROLE_FILE_VARS_MAIN,
)

RULE = "login-methods"
NATIVE_SSO_FLAVORS = frozenset({"oidc", "saml"})
SECOND_FACTOR = "2fa"
FALSE_WORDS = frozenset({"false", "no", "off", "0"})
OFFERED_ONLY = {
    "web-app-gitea": "TWO_FACTOR_AUTH=enforced takes repository access from every "
    "individual account without a second factor, token requests included, so the "
    "MCP account the deploy provisions would lose it",
}
NATIVE_BESIDE_SSO = {
    "web-app-mattermost": "Team Edition drops the GitLab button that carries the "
    "Keycloak entry from its client config without an OpenID license, so the SSO "
    "link templates/javascript.js.j2 injects needs the native form to sit on",
}
UNSWITCHED = {
    (
        "web-app-minio",
        "native",
    ): "the Console form of the root account has no MinIO switch, also serves "
    "LDAP accounts and is the break-glass path",
    (
        "web-app-litellm",
        "native",
    ): "LiteLLM has no switch that removes the UI_USERNAME and UI_PASSWORD form, "
    "and /fallback/login keeps it as the break-glass path",
    (
        "web-app-openpost",
        "native",
    ): "OpenPost has no switch that removes its email and password form, and "
    "tasks/03_breakglass.yml signs the break-glass admin in with that password",
}


def expected(application_id: str, method: str) -> str:
    return f"{{{{ lookup('login_method', '{application_id}', '{method}') }}}}"


def keeps_native(application_id: str, method: str) -> bool:
    return method == "native" and application_id in NATIVE_BESIDE_SSO


def enabled_default(application_id: str, method: str) -> object:
    if keeps_native(application_id, method):
        return True
    return expected(application_id, method)


def enforced_default(application_id: str) -> bool:
    return application_id not in OFFERED_ONLY


def keys(method: str) -> frozenset[str]:
    if method == SECOND_FACTOR:
        return frozenset({"enabled", "enforced"})
    return frozenset({"enabled"})


def _normalized(value: object) -> str:
    return " ".join(str(value).split())


def _key_list(method: str) -> str:
    return " and ".join(f"`{key}`" for key in sorted(keys(method)))


def _services(role_dir) -> tuple[Mapping, list[str]] | None:
    path = role_dir / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return None
    data = load_yaml_any(str(path))
    if not isinstance(data, Mapping):
        return None
    return data, read_text(str(path)).splitlines()


def _sso_line(lines: list[str]) -> int | None:
    return next((n for n, line in enumerate(lines, 1) if line.startswith("sso:")), None)


def method_findings(application_id: str, login: object) -> list[str]:
    """Findings for one ``<entity>.login`` block.

    Args:
        application_id: the role that declares the block.
        login: the block's parsed value.
    """
    methods = login.get("method") if isinstance(login, Mapping) else None
    if not isinstance(methods, Mapping) or not methods:
        return ["login.method is not a non-empty mapping"]
    findings = []
    for method, spec in methods.items():
        if method not in METHODS:
            findings.append(f"login.method.{method} is not one of {', '.join(METHODS)}")
            continue
        if not isinstance(spec, Mapping) or set(spec) != keys(method):
            findings.append(
                f"login.method.{method} must hold exactly {_key_list(method)}"
            )
            continue
        default = enabled_default(application_id, method)
        if _normalized(spec["enabled"]) != _normalized(default):
            findings.append(
                f"login.method.{method}.enabled is {spec['enabled']!r}, expected {default!r}"
            )
        enforced = enforced_default(application_id)
        if "enforced" in spec and spec["enforced"] is not enforced:
            findings.append(
                f"login.method.{method}.enforced is {spec['enforced']!r}, "
                f"expected {enforced!r}"
            )
    return findings


def default_findings(application_id: str, services: object) -> list[str]:
    """Findings for every ``<entity>.login`` block of one ``meta/services.yml``.

    Args:
        application_id: the role the file belongs to.
        services: the file's parsed content.
    """
    if not isinstance(services, Mapping):
        return []
    return [
        f"{application_id}/{entity}: {finding}"
        for entity, config in services.items()
        if isinstance(config, Mapping) and "login" in config
        for finding in method_findings(application_id, config["login"])
    ]


def second_factor_entities(services: object) -> list[str]:
    """The entities of one ``meta/services.yml`` whose login declares ``2fa``.

    Args:
        services: the file's parsed content.
    """
    if not isinstance(services, Mapping):
        return []
    return [
        str(entity)
        for entity, config in services.items()
        if isinstance(config, Mapping)
        and isinstance(config.get("login"), Mapping)
        and isinstance(config["login"].get("method"), Mapping)
        and SECOND_FACTOR in config["login"]["method"]
    ]


def _dig(node: object, *path: str) -> object:
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    return node


def is_false(value: object) -> bool:
    """Whether a variant value turns a flag off once the role reads it with ``| bool``.

    Args:
        value: a literal, a string such as ``"false"`` or ``"no"``, or a Jinja
            expression of a false constant such as ``"{{ false }}"``.
    """
    if value is False:
        return True
    if value is None or value is True:
        return False
    text = "".join(str(value).split()).lower()
    if text.startswith("{{") and text.endswith("}}"):
        text = text[2:-2].strip("'\"")
    return text in FALSE_WORDS


def _key_line(node: object, path: tuple[str, ...]) -> int | None:
    line = None
    for key in path:
        pairs = node.value if isinstance(node, yaml.MappingNode) else []
        found = next((pair for pair in pairs if pair[0].value == key), None)
        if found is None:
            return None
        line, node = found[0].start_mark.line + 1, found[1]
    return line


def enforcement_kept(text: str, entity: str) -> frozenset[int]:
    """
    Args:
        text: the raw ``meta/variants.yml``.
        entity: the entity whose ``login.method`` declares ``2fa``.

    Returns:
        The indices of the variants whose ``enforced`` key carries the rule's
        marker with a reason.
    """
    root = yaml.compose(text)
    entries = root.value if isinstance(root, yaml.SequenceNode) else []
    lines = text.splitlines()
    path = ("services", entity, "login", "method", SECOND_FACTOR, "enforced")
    return frozenset(
        index
        for index, entry in enumerate(entries)
        if (line := _key_line(entry, path)) is not None
        and has_rule_with_reason(lines, line, RULE)
    )


def variant_findings(
    role: str, entity: str, variants: object, kept: frozenset[int] = frozenset()
) -> list[str]:
    """Findings for the variants of one role whose entity declares ``2fa``.

    Args:
        role: the role the variants belong to.
        entity: the entity whose ``login.method`` declares ``2fa``.
        variants: the parsed ``meta/variants.yml``.
        kept: the ``enforcement_kept`` indices of the same file.
    """
    if not isinstance(variants, list):
        return []
    findings = []
    for index, entry in enumerate(variants):
        services = _dig(entry, "services")
        sso_off = is_false(_dig(services, "sso", "enabled"))
        enforced = _dig(services, entity, "login", "method", SECOND_FACTOR, "enforced")
        if index in kept:
            if not sso_off or is_false(enforced):
                findings.append(
                    f"{role} variant {index}: its `nocheck: {RULE}` marker "
                    "keeps no enforcement on, so drop it"
                )
            continue
        if sso_off and not is_false(enforced):
            findings.append(
                f"{role} variant {index}: SSO is off, so it sets "
                f"services.{entity}.login.method.{SECOND_FACTOR}.enforced: false"
            )
    if len(kept) > 1:
        findings.append(
            f"{role} variants {', '.join(str(index) for index in sorted(kept))}: "
            f"only one variant per role keeps the enforcement on under `nocheck: {RULE}`"
        )
    return findings


def lacks_block(application_id: str, services: object, lines: list[str]) -> bool:
    """Whether a role with a native SSO sign-in declares no ``login.method`` block.

    Args:
        application_id: the role the file belongs to.
        services: the file's parsed content.
        lines: the file's lines, searched for the marker on the ``sso:`` key.
    """
    if not isinstance(services, Mapping):
        return False
    sso = services.get("sso")
    if not isinstance(sso, Mapping) or sso.get("flavor") not in NATIVE_SSO_FLAVORS:
        return False
    entity = services.get(entity_name(application_id))
    if isinstance(entity, Mapping) and "login" in entity:
        return False
    line = _sso_line(lines)
    return line is None or not has_rule_with_reason(lines, line, RULE)


def flag_key(entity: str, method: str) -> str:
    return f"services.{entity}.login.method.{method}.enabled"


def is_switch_artefact(relative: str) -> bool:
    """Whether a role file can carry a switch.

    Args:
        relative: the file's path below its role directory.
    """
    path = PurePath(relative)
    return path.suffix != ".md" and not any("playwright" in part for part in path.parts)


def reaches_switch(
    key: str, variables: Mapping[str, object], artefacts: Iterable[str]
) -> bool:
    """Whether deploy code of one role reads *key*.

    Args:
        key: the flag's ``flag_key``.
        variables: the role's ``vars/main.yml``.
        artefacts: the text of every other switch artefact of the role.
    """
    texts = list(artefacts)
    if any(key in text for text in texts):
        return True
    raw = {str(name): str(value) for name, value in variables.items()}
    frontier = [name for name, value in raw.items() if key in value]
    seen = set(frontier)
    while frontier:
        pattern = re.compile(rf"\b{re.escape(frontier.pop())}\b")
        if any(pattern.search(text) for text in texts):
            return True
        for name, value in raw.items():
            if name not in seen and pattern.search(value):
                seen.add(name)
                frontier.append(name)
    return False


def role_artefacts() -> dict[str, dict[str, str]]:
    """The text of every switch artefact, by role and path below the role."""
    prefix = f"{ROLES_DIR}{os.sep}"
    index: dict[str, dict[str, str]] = {}
    for path in iter_project_files():
        if not path.startswith(prefix):
            continue
        role, _, relative = path[len(prefix) :].partition(os.sep)
        relative = PurePath(relative).as_posix()
        if relative == ROLE_FILE_VARS_MAIN or not is_switch_artefact(relative):
            continue
        try:
            index.setdefault(role, {})[relative] = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
    return index


def role_variables(role: str) -> Mapping[str, object]:
    variables = load_yaml_any(
        str(ROLES_DIR / role / ROLE_FILE_VARS_MAIN), default_if_missing={}
    )
    return variables if isinstance(variables, Mapping) else {}


def declared_flags() -> list[tuple[str, str, str]]:
    """Every declared ``(role, entity, method)``."""
    flags = []
    for role_dir in iter_role_dirs():
        loaded = _services(role_dir)
        if loaded is None:
            continue
        for entity, config in loaded[0].items():
            login = config.get("login") if isinstance(config, Mapping) else None
            methods = login.get("method") if isinstance(login, Mapping) else None
            if isinstance(methods, Mapping):
                flags.extend((role_dir.name, str(entity), str(m)) for m in methods)
    return flags


def switch_finding(role: str, entity: str, method: str, reached: bool) -> str | None:
    """The finding for one declared flag, or ``None``.

    Args:
        role: the role that declares the flag.
        entity: the entity it is declared under.
        method: the method.
        reached: whether ``reaches_switch`` holds in any role that reads it.
    """
    key = flag_key(entity, method)
    exempt = (role, method) in UNSWITCHED
    if reached and exempt:
        return f"{role}: deploy code reads {key}, so drop it from UNSWITCHED"
    if not reached and not exempt:
        return f"{role}: no template, task, meta or file reads {key}"
    return None


class TestLoginMethods(unittest.TestCase):
    def test_declared_methods_default_through_the_lookup(self):
        violations = []
        for role_dir in iter_role_dirs():
            loaded = _services(role_dir)
            if loaded is not None:
                violations.extend(default_findings(role_dir.name, loaded[0]))
        self.assertEqual(violations, [], "\n".join(violations))

    def test_variants_without_sso_switch_the_enforcement_off(self):
        violations = []
        for role_dir in iter_role_dirs():
            loaded = _services(role_dir)
            variants_path = role_dir / ROLE_FILE_META_VARIANTS
            if loaded is None or not variants_path.is_file():
                continue
            variants = load_yaml_any(str(variants_path))
            text = read_text(str(variants_path))
            for entity in second_factor_entities(loaded[0]):
                kept = enforcement_kept(text, entity)
                violations.extend(
                    variant_findings(role_dir.name, entity, variants, kept)
                )
        self.assertEqual(violations, [], "\n".join(violations))

    def test_native_sso_roles_declare_their_methods(self):
        missing = []
        for role_dir in iter_role_dirs():
            loaded = _services(role_dir)
            if loaded is not None and lacks_block(role_dir.name, *loaded):
                missing.append(role_dir.name)
        self.assertEqual(
            missing,
            [],
            "roles with a native SSO sign-in but no "
            "<entity>.login.method block (declare it, or mark a one-method "
            f"sign-in with `# nocheck: {RULE}` and a reason on its sso: key):\n"
            + "\n".join(missing),
        )

    def test_declared_methods_reach_a_switch(self):
        artefacts = role_artefacts()
        sources = {
            role: "\n".join([*texts.values(), str(role_variables(role))])
            for role, texts in artefacts.items()
        }
        declared = declared_flags()
        findings = []
        for role, entity, method in declared:
            key = flag_key(entity, method)
            readers = {role} | {other for other, text in sources.items() if key in text}
            reached = any(
                reaches_switch(
                    key, role_variables(reader), artefacts.get(reader, {}).values()
                )
                for reader in sorted(readers)
            )
            finding = switch_finding(role, entity, method, reached)
            if finding is not None:
                findings.append(finding)
        declared_methods = {(role, method) for role, _, method in declared}
        findings.extend(
            f"{role}: UNSWITCHED names {method}, which the role does not declare"
            for role, method in sorted(set(UNSWITCHED) - declared_methods)
        )
        self.assertEqual(findings, [], "\n".join(findings))


if __name__ == "__main__":
    unittest.main()
