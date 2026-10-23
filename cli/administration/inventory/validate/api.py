"""API credential validation: moved credential names and a missing Cloudflare token."""

from __future__ import annotations

from pathlib import Path

from utils.cache.api import declared_api

from .loaders import load_yaml_file


def legacy_api_keys(declared: set[str]) -> dict[str, str]:
    """Map the flat names older inventories gave API credentials to their ``API`` path.

    Args:
        declared: the variables core reads, see ``read_variables()``.

    Returns:
        ``<PROVIDER>_<KEY>`` in upper case to ``API.<provider>.<key>``, without
        the names core still reads as a variable of their own.
    """
    legacy = {
        f"{provider}_{key}".upper(): f"API.{provider}.{key}"
        for provider, keys in declared_api().items()
        for key in keys
    }
    return {name: path for name, path in legacy.items() if name not in declared}


def _cloudflare_token(data: dict) -> str:
    api = data.get("API")
    provider = api.get("cloudflare") if isinstance(api, dict) else None
    token = provider.get("api_token") if isinstance(provider, dict) else None
    return str(token or "").strip()


def _merged(paths: list[Path]) -> dict:
    merged: dict = {}
    for path in paths:
        data = load_yaml_file(path)
        if isinstance(data, dict):
            merged.update(data)
    return merged


def validate_api_keys(inv_dir) -> list[str]:
    """Report hosts that select Cloudflare DNS without a Cloudflare token.

    Args:
        inv_dir: the inventory directory.

    Returns:
        One message per host whose variables select ``DNS_PROVIDER: cloudflare``
        without ``API.cloudflare.api_token``.
    """
    root = Path(inv_dir)
    group_all = _merged(
        sorted(root.glob("group_vars/all.yml"))
        + sorted(root.glob("group_vars/all/*.yml"))
    )
    hosts = [(path, [path]) for path in sorted(root.glob("host_vars/*.yml"))]
    hosts += [
        (path, sorted(path.glob("*.yml")))
        for path in sorted(root.glob("host_vars/*"))
        if path.is_dir()
    ]
    errs: list[str] = []
    for path, files in hosts or [(root / "group_vars", [])]:
        effective = {**group_all, **_merged(files)}
        if effective.get("DNS_PROVIDER") == "cloudflare" and not _cloudflare_token(
            effective
        ):
            errs.append(
                f"{path}: DNS_PROVIDER is cloudflare, but API.cloudflare.api_token is empty"
            )
    return errs
