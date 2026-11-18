"""Cross-cutting helpers for the `utils.cache.*` package.

Holds primitives that the domain modules (`users`, `applications`,
`domains`) all need but no domain owns: filesystem constants, YAML
loaders, deep-merge, cache-key + content-fingerprint signatures,
templar-render machinery, and the cross-domain re-entry guard.

Stays import-cheap so that `utils.cache.applications` (consumed on
GitHub Actions runner hosts that ship without ansible — see CI runs
24934007615 / 24935979190) can pull this module without dragging
ansible in. The single ansible-coupled symbol exposed from here is
`_render_with_templar`, which lazy-imports `utils.templating.ansible`
only when actually invoked.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import os
import re
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from utils.cache.errors import is_unresolvable
from utils.paths import FILE_TOKENS

from . import ROLES_DIR

_TOKENS_DIGESTS: dict[tuple, str] = {}

try:
    from ansible.parsing.vault import EncryptedString as _AnsibleEncryptedString
except Exception:
    _AnsibleEncryptedString = None


def _decrypt_ansible_encrypted_strings(value: Any) -> Any:
    """Recursively convert Ansible EncryptedString values to plaintext str.

    Ansible 2.19+ refuses to store EncryptedString as an intermediate variable
    during task arg finalization, so decrypt at the lookup boundary.
    """
    if _AnsibleEncryptedString is not None and isinstance(
        value, _AnsibleEncryptedString
    ):
        try:
            return str(value)
        except Exception:
            return value
    if isinstance(value, Mapping):
        return {k: _decrypt_ansible_encrypted_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decrypt_ansible_encrypted_strings(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_decrypt_ansible_encrypted_strings(v) for v in value)
    return value


DEFAULT_TOKENS_FILE = FILE_TOKENS


_RENDER_GUARD = threading.local()


def _cache_key(roles_dir: Path) -> str:
    return str(roles_dir.resolve())


def _fingerprint_mapping(obj: Any) -> str:
    """Cheap-ish content fingerprint for cache keying.

    Ansible 2.19+ composes a fresh `variables` mapping per task via
    VariableManager.get_vars() and — empirically — often reconstructs the
    inventory-level `applications`/`users` dicts too, so keying on `id(obj)`
    misses the cache across tasks. A content fingerprint hits across tasks
    whenever the inventory payload is unchanged.

    repr-based MD5 over the mapping's sorted items.

    Exception: memoising the digest under ``id(obj)`` is unsound and MUST NOT
    be reintroduced. The memo would hold no reference to *obj*, so CPython
    recycles the address of a freed mapping and serves its digest for an
    unrelated live one — measured at 398/400 wrong digests for short-lived
    mappings, which silently defeats every cache keyed on this function.
    `_scoped_fingerprint` is the sound reuse: it holds the mapping itself.
    """
    if obj is None:
        return "0"
    try:
        data = repr(sorted(obj.items())) if isinstance(obj, Mapping) else repr(obj)
        return hashlib.md5(
            data.encode("utf-8", errors="replace"),
            usedforsecurity=False,
        ).hexdigest()
    except Exception:
        return "unhashable"


class ScopedFingerprintMutatedError(RuntimeError):
    pass


@contextlib.contextmanager
def _fingerprint_scope() -> Iterator[None]:
    """Let `_scoped_fingerprint` reuse digests until the outermost scope exits.

    Raises:
        ScopedFingerprintMutatedError: a render that finished normally reused
            a mapping that no longer matches the digest it was served under.
            A render that raised keeps its own error unchecked.
    """
    if getattr(_RENDER_GUARD, "fingerprints", None) is not None:
        yield
        return
    memo: dict[int, list[Any]] = {}
    _RENDER_GUARD.fingerprints = memo
    try:
        yield
        stale = sum(
            1
            for held, digest, hits in memo.values()
            if hits and _fingerprint_mapping(held) != digest
        )
    finally:
        _RENDER_GUARD.fingerprints = None
        memo.clear()
    if stale:
        raise ScopedFingerprintMutatedError(
            f"{stale} mapping(s) changed in place during one render, "
            "after their fingerprint keyed the applications/users caches"
        )


def _scoped_fingerprint(obj: Any) -> str:
    """Return `_fingerprint_mapping(obj)`, once per mapping and open scope.

    Args:
        obj: the ``applications`` or ``users`` value of a variables scope.
    """
    memo = getattr(_RENDER_GUARD, "fingerprints", None)
    if memo is None or obj is None:
        return _fingerprint_mapping(obj)
    entry = memo.get(id(obj))
    if entry is not None and entry[0] is obj:
        entry[2] += 1
        return entry[1]
    digest = _fingerprint_mapping(obj)
    memo[id(obj)] = [obj, digest, 0]
    return digest


def _stable_variables_signature(variables: Mapping[str, Any] | None) -> tuple:
    """Build a content-based cache signature from the subset of `variables`
    that influences the merged applications/users payload.

    `group_names` belongs in the key because a service flag may be written as
    `{{ '<role>' in group_names }}`, so two hosts of one play render different
    payloads from identical host_vars. Ansible forks its workers, so a payload
    rendered in the strategy's main process for one host is inherited by every
    later worker; without this component that payload answers for hosts whose
    groups say otherwise.

    See `_fingerprint_mapping` for why id()-only keys don't work reliably.
    """
    if not variables:
        return ("0", "0", "", "", "")
    groups = variables.get("group_names")
    return (
        _scoped_fingerprint(variables.get("applications")),
        _scoped_fingerprint(variables.get("users")),
        str(variables.get("DOMAIN_PRIMARY") or ""),
        str(variables.get("SYSTEM_EMAIL_DOMAIN") or ""),
        ",".join(sorted(str(group) for group in groups)) if groups else "",
    )


def _stat_identity(st: os.stat_result) -> tuple:
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _tokens_file_signature(path: Path) -> tuple:
    """Return ``(path, sha256 of the content)`` for the tokens file.

    Args:
        path: the tokens file.

    Returns:
        ``(str(path), "")`` when the file cannot be read.
    """
    try:
        identity = (str(path), *_stat_identity(path.stat()))
    except OSError:
        return (str(path), "")
    digest = _TOKENS_DIGESTS.get(identity)
    if digest is None:
        try:
            with path.open("rb") as handle:
                identity = (str(path), *_stat_identity(os.fstat(handle.fileno())))
                digest = hashlib.sha256(handle.read()).hexdigest()
        except OSError:
            return (str(path), "")
        _TOKENS_DIGESTS[identity] = digest
    return (str(path), digest)


def _revalidate_tokens_file(path: Path) -> None:
    """Open and close the tokens file so an NFS client refreshes its attributes.

    Args:
        path: the tokens file.
    """
    try:
        with path.open("rb"):
            pass
    except OSError:
        return


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, Mapping) and isinstance(override, Mapping):
        merged = {k: copy.deepcopy(v) for k, v in base.items()}
        for key, value in override.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(override)


def _resolve_roles_dir(*, roles_dir: str | os.PathLike[str] | None = None) -> Path:
    return Path(roles_dir).resolve() if roles_dir else ROLES_DIR.resolve()


def _resolve_override_mapping(
    variables: Mapping[str, Any] | None,
    key: str,
    templar: Any = None,
) -> dict[str, Any]:
    """Return runtime override mappings defensively.

    Nested `lookup('template', ...)` renders sometimes expose top-level lookup
    inputs like `applications`/`users` as non-mapping placeholder values instead
    of the original inventory overrides. Try to coerce via templar before
    falling back to aggregated defaults.
    """

    variables = variables or {}
    value = variables.get(key, {})
    if value is None:
        value = {}
    if not isinstance(value, Mapping) and templar is not None:
        try:
            rendered = templar.template(value, fail_on_undefined=False)
        except TypeError:
            try:
                rendered = templar.template(value)
            except Exception:
                rendered = value
        except Exception:
            rendered = value
        if isinstance(rendered, Mapping):
            value = rendered
    if not isinstance(value, Mapping):
        raw_key = {
            "applications": "_INFINITO_APPLICATIONS_RAW",
            "users": "_INFINITO_USERS_RAW",
        }.get(key)
        if raw_key:
            raw = variables.get(raw_key)
            if isinstance(raw, Mapping):
                value = raw
    if isinstance(value, Mapping):
        return dict(value)
    return {}


_GROUP_MEMBERSHIP = re.compile(
    r"\{\{\s*'[\w.-]+'\s+in\s+group_names"
    r"(?:\s+or\s+'[\w.-]+'\s+in\s+group_names)*\s*\}\}"
)
_GROUP_MEMBERSHIP_NAME = re.compile(r"'([\w.-]+)'")


def _group_membership(text: str, variables: Mapping[str, Any]) -> bool | None:
    """
    Args:
        text: the scalar being rendered, unstripped, so a padded template
            keeps the string the templar returns for it.
        variables: the scope the templar would render it in.

    Returns:
        The membership result, or ``None`` when *text* is not such a
        disjunction or ``group_names`` is not a list of strings.
    """
    if not _GROUP_MEMBERSHIP.fullmatch(text):
        return None
    groups = variables.get("group_names")
    if type(groups) not in (list, tuple) or not all(
        type(group) is str for group in groups
    ):
        return None
    return any(name in groups for name in _GROUP_MEMBERSHIP_NAME.findall(text))


def _render_with_templar(
    value: Any,
    *,
    templar: Any,
    variables: dict[str, Any] | None,
    raw_applications: dict[str, Any] | None = None,
    raw_users: dict[str, Any] | None = None,
    max_rounds: int = 4,
) -> Any:
    if templar is None:
        return value

    from utils.templating.ansible import _templar_render_best_effort

    prev_templar_avail = getattr(templar, "available_variables", None)
    base_variables: dict[str, Any] = (
        dict(prev_templar_avail) if prev_templar_avail else {}
    )
    if variables:
        base_variables.update(variables)
    if raw_applications is not None:
        base_variables["_INFINITO_APPLICATIONS_RAW"] = raw_applications
    if raw_users is not None:
        base_variables["_INFINITO_USERS_RAW"] = raw_users

    def _render_scalar(raw: Any) -> Any:
        if isinstance(raw, str) and "{{" not in raw and "{%" not in raw:
            return raw
        data = copy.deepcopy(raw)
        if isinstance(data, str):
            stripped = data.strip()
            member = _group_membership(data, base_variables)
            if member is not None:
                return member
            if (
                stripped.startswith("{{")
                and stripped.endswith("}}")
                and "{{" not in stripped[2:]
                and "{%" not in stripped
            ):
                from utils.templating.ansible import _templar_render_preserve_type

                try:
                    rendered = _templar_render_preserve_type(
                        templar, data, base_variables
                    )
                except Exception as exc:
                    if is_unresolvable(exc):
                        raise
                    rendered = None
                if rendered is not None and not isinstance(rendered, str):
                    return _render_deep(rendered)
            for _ in range(max_rounds):
                try:
                    rendered = _templar_render_best_effort(
                        templar, data, base_variables
                    )
                except Exception as exc:
                    if is_unresolvable(exc):
                        raise
                    return data
                if rendered == data:
                    break
                data = rendered
            return data

        for _ in range(max_rounds):
            try:
                rendered = templar.template(data, fail_on_undefined=False)
            except TypeError:
                rendered = templar.template(data)
            except Exception as exc:
                if is_unresolvable(exc):
                    raise
                return data
            if rendered == data:
                break
            data = rendered
        return data

    def _render_deep(raw: Any) -> Any:
        if isinstance(raw, Mapping):
            return {key: _render_deep(item) for key, item in raw.items()}
        if isinstance(raw, list):
            return [_render_deep(item) for item in raw]
        if isinstance(raw, tuple):
            return tuple(_render_deep(item) for item in raw)
        return _render_scalar(raw)

    with _fingerprint_scope():
        try:
            if hasattr(templar, "available_variables"):
                templar.available_variables = base_variables
            data = _render_deep(value)
        finally:
            if hasattr(templar, "available_variables"):
                templar.available_variables = prev_templar_avail

    return _decrypt_ansible_encrypted_strings(data)


def _reset() -> None:
    """Clear the tokens-file digest memo."""
    _TOKENS_DIGESTS.clear()
