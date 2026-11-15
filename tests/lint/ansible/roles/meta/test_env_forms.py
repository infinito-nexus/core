from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleFilterError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from plugins.filter.dotenv import dotenv_names
from plugins.lookup.form_values import LookupModule as FormValues
from utils.cache import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.reset import _reset_cache_for_tests
from utils.roles.applications.forms import SECRET_SEGMENT, is_secret
from utils.roles.mapping import ROLE_FILE_META_FORMS, ROLE_FILE_META_SERVICES

from . import load_role_meta, role_dirs, role_files
from .test_forms import _credentials

if TYPE_CHECKING:
    from pathlib import Path

ENV_DRIFT = "tasks/utils/forms/env.yml"
ENV_FORM = re.compile(r"^\s*forms_env_form:\s*['\"]?([A-Za-z0-9_-]+)", re.MULTILINE)
PARTNER = re.compile(r"'([a-z0-9-]+)' in group_names")
NEEDS_A_HOST = frozenset({"svc-net-tor"})


def env_forms(roles: list[Path]) -> dict[str, tuple[Path, str]]:
    """Return every form a role's env file carries.

    Args:
        roles: the role directories to scan.

    Returns:
        ``<role>.<form>`` mapped to the role directory and the form, for each
        ``forms_env_form`` a task file next to an include of
        ``tasks/utils/forms/env.yml`` names.
    """
    found = {}
    for role in roles:
        for path in role_files(role):
            if path.relative_to(role).parts[0] != "tasks" or path.suffix != ".yml":
                continue
            text = read_text(str(path))
            if ENV_DRIFT not in text:
                continue
            for form in ENV_FORM.findall(text):
                found[f"{role.name}.{form}"] = (role, form)
    return found


def _fields(role: Path, form: str) -> dict[str, Any]:
    forms = load_role_meta(role / ROLE_FILE_META_FORMS) or {}
    return (forms.get(form) or {}).get("fields") or {}


def secret_findings(roles: list[Path]) -> list[str]:
    """Return every env form field whose key or source is secret-class.

    Args:
        roles: the role directories to scan.

    Returns:
        One ``<role>.<form>.<field>`` line per key or ``env`` name matching
        ``SECRET_SEGMENT`` and per source the fail-closed rule calls secret,
        since the env read takes the managed lines out of a file that also
        holds the secrets.
    """
    errors = []
    for where, (role, form) in sorted(env_forms(roles).items()):
        credentials = _credentials(role)
        for field, spec in _fields(role, form).items():
            if SECRET_SEGMENT.search(field):
                errors.append(f"{where}.{field}: the key is secret-class")
            if SECRET_SEGMENT.search(str(spec.get("env") or "")):
                errors.append(f"{where}.{field}: the env name is secret-class")
            if is_secret(spec.get("source"), credentials):
                errors.append(f"{where}.{field}: the source is secret-class")
    return errors


def name_findings(roles: list[Path]) -> list[str]:
    """Return every env form whose fields name no distinct variables.

    Args:
        roles: the role directories to scan.

    Returns:
        One ``<role>.<form>`` line per form ``dotenv_names`` refuses: a key
        without ``env`` that is not lower snake_case, an ``env`` that is no
        variable name, or two fields that name one variable.
    """
    errors = []
    for where, (role, form) in sorted(env_forms(roles).items()):
        fields = _fields(role, form)
        try:
            dotenv_names(list(fields), fields)
        except AnsibleFilterError as exc:
            errors.append(f"{where}: {exc}")
    return errors


def _scope(names: list[str]) -> dict[str, Any]:
    variables: dict[str, Any] = {}
    loader = DataLoader()
    for path in sorted((PROJECT_ROOT / "group_vars" / "all").glob("*.yml")):
        data = loader.load_from_file(str(path), trusted_as_template=True)
        if isinstance(data, dict):
            variables.update(data)
    variables.update(
        {
            "TLS_ENABLED": True,
            "TLS_MODE": "self_signed",
            "group_names": names,
            "groups": {name: ["localhost"] for name in names},
            "DOMAIN_PRIMARY": "infinito.test",
            "SYSTEM_EMAIL_DOMAIN": "infinito.test",
            "ansible_facts": {"os_family": "Debian"},
            "ansible_connection": "local",
            "inventory_hostname": "localhost",
            "RESOURCE_HOST_CPUS_OVERRIDE": 16,
            "RESOURCE_HOST_MEM_MB_OVERRIDE": 64000,
            "playbook_dir": str(PROJECT_ROOT),
            "DEPLOYMENT_MODE": "compose",
        }
    )
    return variables


def _partners(role: Path) -> list[str]:
    services = read_text(str(role / ROLE_FILE_META_SERVICES))
    return sorted({role.name, *PARTNER.findall(services)} - NEEDS_A_HOST)


def type_findings(roles: list[Path]) -> list[str]:
    """Return every env form field that does not resolve to a string.

    Args:
        roles: the role directories to scan; each is rendered on a probe host
            that also deploys every role its meta/services.yml gates a
            service on, so each ``when`` of a field holds wherever it can;
            ``NEEDS_A_HOST`` lists the partners that refuse to render
            without a real host (svc-net-tor needs its onion node).

    Returns:
        One ``<role>.<form>.<field>`` line per value of ``form_values`` that
        is not a ``str``: the env read gives strings back, so any other type
        reports drift on every run.
    """
    errors = []
    for where, (role, form) in sorted(env_forms(roles).items()):
        _reset_cache_for_tests()
        variables = _scope(_partners(role))
        lookup = FormValues()
        lookup._loader = DataLoader()
        lookup._templar = Templar(loader=lookup._loader)
        settings = lookup.run([role.name, form], variables=dict(variables))[0]
        if not settings:
            errors.append(f"{where}: no field applies on the probe host")
        for field, value in settings.items():
            if not isinstance(value, str):
                errors.append(f"{where}.{field}: resolves to {type(value).__name__}")
    return errors


class TestEnvForms(unittest.TestCase):
    def test_at_least_one_role_carries_an_env_form(self) -> None:
        self.assertTrue(env_forms(role_dirs()))

    def test_no_env_form_field_is_secret_class(self) -> None:
        self.assertEqual([], secret_findings(role_dirs()))

    def test_every_env_form_field_names_its_own_variable(self) -> None:
        self.assertEqual([], name_findings(role_dirs()))

    def test_every_env_form_field_resolves_to_a_string_after_its_map(self) -> None:
        self.assertEqual([], type_findings(role_dirs()))


if __name__ == "__main__":
    unittest.main()
