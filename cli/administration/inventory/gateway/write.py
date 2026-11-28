from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ruamel.yaml.comments import CommentedMap, TaggedScalar

from cli.administration.inventory.ruamel_io import (
    dump_document,
    ensure_map,
    load_document,
    vault_value,
)
from utils.manager.credential_key import CREDENTIALS_KEY, SECRETS_KEY
from utils.manager.value_generator import ValueGenerator

from .plan import APPLICATION_ID, SERVICE_KEY

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .plan import Link

URL_KEY = "gateway_url"
MODEL_KEY = "gateway_model"
HOST_KEY = "gateway_key"
HOST_KEYS = "host_keys"
KEY_ALGORITHM = "sk_prefixed"


def mint_key() -> str:
    """Return a fresh virtual key in the shape LiteLLM accepts for ``key``."""
    return ValueGenerator().generate_value(KEY_ALGORITHM)


def _held(value: Any) -> bool:
    if isinstance(value, TaggedScalar):
        return bool(str(value.value).strip())
    return isinstance(value, str) and bool(value.strip())


def _get(document: CommentedMap, *path: str) -> Any:
    node: Any = document
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _app(document: CommentedMap) -> CommentedMap:
    return ensure_map(ensure_map(document, "applications"), APPLICATION_ID)


def _service(document: CommentedMap) -> CommentedMap:
    return ensure_map(ensure_map(_app(document), "services"), SERVICE_KEY)


def _credentials(document: CommentedMap) -> CommentedMap:
    return ensure_map(ensure_map(_app(document), SECRETS_KEY), CREDENTIALS_KEY)


def _drop(document: CommentedMap, path: tuple[str, ...]) -> bool:
    parent = _get(document, *path[:-1])
    if isinstance(parent, dict) and path[-1] in parent:
        del parent[path[-1]]
        return True
    return False


class HostVars:
    """The host_vars documents of one pass, written only where they changed.

    Args:
        host_vars_dir: directory holding one ``<host>.yml`` per host.
        vault_password_file: password file a value is encrypted with.
        host_vault_password_files: hostname to the password file of a host
            deployed with its own vault password.
    """

    def __init__(
        self,
        host_vars_dir: Path,
        vault_password_file: Path,
        host_vault_password_files: dict[str, Path] | None = None,
    ) -> None:
        self.host_vars_dir = host_vars_dir
        self.vault_password_file = vault_password_file
        self.own_password_files = dict(host_vault_password_files or {})
        self.documents: dict[str, CommentedMap] = {}
        self.changed: set[str] = set()

    def document(self, host: str) -> CommentedMap:
        if host not in self.documents:
            self.documents[host] = load_document(self.host_vars_dir / f"{host}.yml")
        return self.documents[host]

    def vault(self, host: str, plain: str, name: str) -> Any:
        password_file = self.own_password_files.get(host, self.vault_password_file)
        return vault_value(password_file, plain, name)

    def flush(self) -> list[Path]:
        written = []
        for host in sorted(self.changed):
            path = self.host_vars_dir / f"{host}.yml"
            dump_document(path, self.documents[host])
            written.append(path)
        return written


def _link(
    link: Link,
    host_vars: HostVars,
    *,
    model: str,
    rotate: bool,
    mint: Callable[[], str],
) -> None:
    consumer = host_vars.document(link.consumer)
    gateway = host_vars.document(link.gateway)
    secrets = ("applications", APPLICATION_ID, SECRETS_KEY, CREDENTIALS_KEY)
    held_here = _held(_get(consumer, *secrets, HOST_KEY))
    held_there = _held(_get(gateway, *secrets, HOST_KEYS, link.consumer))
    if rotate or not (held_here and held_there):
        key = mint()
        _credentials(consumer)[HOST_KEY] = host_vars.vault(link.consumer, key, HOST_KEY)
        ensure_map(_credentials(gateway), HOST_KEYS)[link.consumer] = host_vars.vault(
            link.gateway, key, link.consumer
        )
        host_vars.changed |= {link.consumer, link.gateway}
    service = _service(consumer)
    for key, value in ((URL_KEY, link.url), (MODEL_KEY, model)):
        if service.get(key) != value:
            service[key] = value
            host_vars.changed.add(link.consumer)


def _unlink(host: str, host_vars: HostVars) -> None:
    document = host_vars.document(host)
    base = ("applications", APPLICATION_ID)
    for path in (
        (*base, "services", SERVICE_KEY, URL_KEY),
        (*base, "services", SERVICE_KEY, MODEL_KEY),
        (*base, SECRETS_KEY, CREDENTIALS_KEY, HOST_KEY),
    ):
        if _drop(document, path):
            host_vars.changed.add(host)


def _prune(host: str, linked: set[str], host_vars: HostVars) -> list[str]:
    path = ("applications", APPLICATION_ID, SECRETS_KEY, CREDENTIALS_KEY, HOST_KEYS)
    held = _get(host_vars.document(host), *path)
    if not isinstance(held, dict):
        return []
    stale = sorted(name for name in held if name not in linked)
    for name in stale:
        del held[name]
    if stale:
        if not held:
            _drop(host_vars.document(host), path)
        host_vars.changed.add(host)
    return stale


def apply_links(
    links: list[Link],
    hosts: list[str],
    host_vars: HostVars,
    *,
    models: dict[str, str],
    rotate: set[str],
    mint: Callable[[], str] = mint_key,
) -> dict[str, list[str]]:
    """Bring every host's gateway values in line with ``links``.

    Args:
        links: the consuming hosts of the deploy, from ``plan_links``.
        hosts: every inventory hostname of the deploy.
        host_vars: the documents to change.
        models: consuming host to the chat model it is configured with.
        rotate: consuming hosts whose key is replaced even when both halves
            are held.
        mint: returns a fresh virtual key.

    Returns:
        Gateway host to the consuming hosts whose key it no longer holds.
    """
    for link in links:
        _link(
            link,
            host_vars,
            model=models[link.consumer],
            rotate=link.consumer in rotate,
            mint=mint,
        )
    consumers = {link.consumer for link in links}
    for host in hosts:
        if host not in consumers:
            _unlink(host, host_vars)
    revoked: dict[str, list[str]] = {}
    for host in hosts:
        linked = {link.consumer for link in links if link.gateway == host}
        stale = _prune(host, linked, host_vars)
        if stale:
            revoked[host] = stale
    return revoked
