from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ruamel.yaml.comments import CommentedMap

from utils.manager.inventory import InventoryManager
from utils.openbao_client import REFERENCE_KEY, OpenBaoClient, OpenBaoError

from .emit import ensure_map

FIELD = "value"
_SEGMENT = r"[A-Za-z0-9_@+=,.-]+"
_TARGET = re.compile(
    rf"(?P<mount>[a-z0-9][a-z0-9_-]*)/(?P<prefix>{_SEGMENT}(?:/{_SEGMENT})*)"
)


class ReferenceInventoryManager(InventoryManager):
    def seal(self, plain: str, key: str) -> Any:
        return plain


def parse_target(target: str) -> tuple[str, str]:
    """
    Args:
        target: the ``--openbao`` value, ``<mount>/<prefix>``.

    Returns:
        The KV v2 mount and the prefix every generated secret lies below.
    """
    match = _TARGET.fullmatch(target)
    if match is None or any(part in (".", "..") for part in match["prefix"].split("/")):
        raise OpenBaoError(
            "--openbao reads <mount>/<prefix>, for example tenant/ws-<id>"
        )
    return match["mount"], match["prefix"]


class OpenBaoSink:
    def __init__(self, client: OpenBaoClient, mount: str, prefix: str) -> None:
        """
        Args:
            client: a client holding the login that may create the secrets.
            mount: see ``parse_target``.
            prefix: see ``parse_target``.
        """
        self.client = client
        self.mount = mount
        self.prefix = prefix

    def reference(self, app_id: str, key_path: str, plain: str) -> CommentedMap:
        """
        Args:
            app_id: the application the credential belongs to.
            key_path: the credential's dotted name below ``secrets.credentials``.
            plain: the generated value; it goes to OpenBao and nowhere else.

        Returns:
            The reference the inventory holds instead of the value. An existing
            secret at that path keeps every version: the write is create-only.
        """
        path = f"{self.prefix}/{app_id}/{key_path.replace('.', '/')}"
        self.client.write_create_only(self.mount, path, {FIELD: plain})
        node = CommentedMap()
        node[REFERENCE_KEY] = f"{self.mount}/{path}#{FIELD}"
        return node


def emit_references(
    schema_node: Mapping[str, Any],
    dest_node: CommentedMap,
    *,
    app_id: str,
    key_path: str,
    sink: OpenBaoSink,
) -> list[str]:
    """
    Args:
        schema_node: a ``secrets.credentials`` branch as the schema resolved
            it, with every value it generated in plaintext.
        dest_node: the same branch of the inventory file.
        app_id: the application the branch belongs to.
        key_path: the dotted name of the branch below ``secrets.credentials``.
        sink: where generated values go.

    Returns:
        The dotted names of the credentials written as references; every
        value the inventory already holds stays as it is.
    """
    written: list[str] = []
    for key, value in schema_node.items():
        full_key = f"{key_path}.{key}" if key_path else str(key)
        if isinstance(value, Mapping) and REFERENCE_KEY not in value:
            if key in dest_node and not isinstance(dest_node[key], Mapping):
                continue
            written.extend(
                emit_references(
                    value,
                    ensure_map(dest_node, key),
                    app_id=app_id,
                    key_path=full_key,
                    sink=sink,
                )
            )
            continue
        if key in dest_node or isinstance(value, Mapping):
            continue
        if value is None or value == "":
            dest_node[key] = ""
            continue
        dest_node[key] = sink.reference(app_id, full_key, str(value))
        written.append(full_key)
    return written
