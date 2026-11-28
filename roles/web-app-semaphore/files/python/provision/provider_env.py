from __future__ import annotations

import datetime as dt
import re
import string
from pathlib import Path

from provision import inputs, keystone, sandbox

HOST = re.compile(r"^(?!.*\.\.)[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
CREDENTIALS_DIRECTORY = "credentials"
WORKSPACE_SECRETS = "workspace_secrets"
CATALOG = "catalog"
KEYSTONE = "keystone"
RUN_BUDGET = dt.timedelta(hours=2)
TOFU_GRACE = dt.timedelta(minutes=5)
FORMATTER = string.Formatter()


def record_fields(template):
    """Args:
        template: a record field, or a text of ``{field}`` parts such as
            ``{token_id}={secret}``.

    Returns:
        The record fields the template reads.
    """
    return [name for _, name, _, _ in FORMATTER.parse(template) if name] or [template]


def mapping_fields(mapping):
    return {field for template in mapping.values() for field in record_fields(template)}


def _composed(template, values):
    if record_fields(template) == [template]:
        return values[template]
    return template.format_map(values)


def mapped(bao, path, mapping):
    values = bao.read(path, sorted(mapping_fields(mapping)))
    return {name: _composed(template, values) for name, template in mapping.items()}


def catalog_fields(spec, secret):
    """Args:
        spec: ``credentials.json`` of the provider.
        secret: an entry of its ``workspace_secrets``.

    Returns:
        The fields the provider's platform records hold for the variables
        *secret* takes from the catalog region, e.g. ``auth_url``; a
        customer's record that carries one is refused.
    """
    names = set(secret.get(CATALOG, {}))
    return {
        field
        for platform in spec["secrets"]
        for name, template in platform.get("env", {}).items()
        if name in names
        for field in record_fields(template)
    }


def catalog_values(secret, region):
    """Args:
        secret: an entry of ``secrets`` or ``workspace_secrets``.
        region: the catalog region of the order line.

    Returns:
        ``{variable: value}`` the entry takes from the region; a missing or
        empty value refuses the run.
    """
    values = {}
    for name, key in secret.get(CATALOG, {}).items():
        value = region.get(key)
        if not isinstance(value, str) or not value:
            raise inputs.RefusedError(f"the catalog region names no {key}")
        values[name] = value
    return values


def provider_secrets(bao, spec, context, source):
    """Args:
        bao: the logged-in OpenBao client of the task.
        spec: ``credentials.json`` of the provider.
        context: the values the secret paths are formatted with.
        source: ``PROVIDER_TOKEN``, ``platform`` or ``workspace``.

    Returns:
        The secrets of the provider the source names; neither source falls
        back to the other.

    Raises:
        RefusedError: the provider takes no customer token, or the
            customer's secret lacks a field, holds it empty or carries a
            field of :func:`catalog_fields`.
    """
    if source == "platform":
        return spec["secrets"]
    if WORKSPACE_SECRETS not in spec:
        raise inputs.RefusedError(
            f"PROVIDER_TOKEN workspace: the provider {context['provider']} takes no "
            f"customer token"
        )
    for secret in spec[WORKSPACE_SECRETS]:
        path = secret["path"].format(**context)
        record = bao.record(path) or {}
        empty = sorted(
            field for field in mapping_fields(secret["env"]) if not record.get(field)
        )
        if empty:
            raise inputs.RefusedError(
                f"PROVIDER_TOKEN workspace: {path} holds no {', '.join(empty)}"
            )
        foreign = sorted(catalog_fields(spec, secret) & set(record))
        if foreign:
            raise inputs.RefusedError(
                f"PROVIDER_TOKEN workspace: {path} carries {', '.join(foreign)}, "
                f"which only the catalog region sets"
            )
    return spec[WORKSPACE_SECRETS]


def provider_environment(bao, spec, context, task, source, region):
    """Args:
        bao: the logged-in OpenBao client of the task.
        spec: ``credentials.json`` of the provider.
        context: the values the secret paths are formatted with.
        task: the task directory; credential files go below ``credentials``.
        source: ``PROVIDER_TOKEN``, ``platform`` or ``workspace``.
        region: the catalog region of the order line.

    Returns:
        The variables OpenTofu reads the provider's credential from, after
        every secret with a ``keystone`` list, the variables of its Keystone
        endpoint, credential id and secret in that order, passed
        :func:`keystone.keystone_contract` for :data:`RUN_BUDGET` plus
        :data:`TOFU_GRACE`, the longest OpenTofu runs with it.
    """
    directory = task / CREDENTIALS_DIRECTORY
    secrets = provider_secrets(bao, spec, context, source)
    if any("{host}" in secret["path"] for secret in secrets) and not (
        HOST.match(context["host"])
    ):
        raise inputs.RefusedError("the catalog region names no valid host")
    environment = {}
    for secret in secrets:
        names = secret.get("env", {})
        files = {
            relative.format(**context): field
            for relative, field in secret.get("files", {}).items()
        }
        values = mapped(bao, secret["path"].format(**context), names | files)
        environment |= {name: values[name] for name in names}
        environment |= catalog_values(secret, region)
        if KEYSTONE in secret:
            auth_url, credential_id, secret_value = (
                environment[name] for name in secret[KEYSTONE]
            )
            keystone.keystone_contract(
                auth_url,
                credential_id,
                secret_value,
                dt.datetime.now(dt.UTC) + RUN_BUDGET + TOFU_GRACE,
            )
        for relative in files:
            sandbox.task_write(
                task, Path(CREDENTIALS_DIRECTORY) / relative, values[relative]
            )
    return environment | {
        name: value.format(**context, credentials=directory)
        for name, value in spec["env"].items()
    }
