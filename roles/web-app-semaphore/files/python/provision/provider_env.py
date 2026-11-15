from __future__ import annotations

import os
import re
import string

from provision import inputs

HOST = re.compile(r"^(?!.*\.\.)[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
WORKSPACE_SECRETS = "workspace_secrets"
FORMATTER = string.Formatter()


def private_file(path, text):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    previous = os.umask(0o077)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    finally:
        os.umask(previous)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


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
            customer's secret lacks a field or holds it empty.
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
    return spec[WORKSPACE_SECRETS]


def provider_environment(bao, spec, context, task, source):
    directory = task / "credentials"
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
        for relative in files:
            private_file(directory / relative, values[relative])
    return environment | {
        name: value.format(**context, credentials=directory)
        for name, value in spec["env"].items()
    }
