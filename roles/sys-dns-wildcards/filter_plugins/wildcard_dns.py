import ipaddress

from ansible.errors import AnsibleFilterError


def _validate(d: str) -> None:
    if (
        not isinstance(d, str)
        or not d.strip()
        or d.startswith(".")
        or d.endswith(".")
        or ".." in d  # nocheck: project-root-import  substring check, not a path build
    ):
        raise AnsibleFilterError(f"Invalid domain: {d!r}")


def _depth(domain: str, apex: str) -> int:
    dl, al = domain.split("."), apex.split(".")
    if not domain.endswith(apex) or len(dl) <= len(al):
        return 0
    return len(dl) - len(al)


def _parent_of_child(domain: str, apex: str) -> str | None:
    """
    For a child like a.b.example.com return b.example.com; else None (needs depth >= 2).
    """
    if not domain.endswith(apex):
        return None
    parts = domain.split(".")
    apex_len = len(apex.split("."))
    if len(parts) <= apex_len + 1:
        return None
    return ".".join(parts[1:])  # drop exactly the left-most label


def _flatten_domains_any_structure(domains_like) -> list[str]:
    """
    Accept CURRENT_PLAY_DOMAINS*_like structures:
      - dict values: str | list/tuple/set[str] | dict (one level deeper)
    Returns unique, sorted host list.
    """
    hosts: list[str] = []

    def _add_any(x):
        if x is None:
            return
        if isinstance(x, str):
            hosts.append(x)
            return
        if isinstance(x, (list, tuple, set)):
            for i in x:
                if not isinstance(i, str):
                    raise AnsibleFilterError(f"Non-string hostname in list: {i!r}")
                hosts.append(i)
            return
        if isinstance(x, dict):
            for v in x.values():
                _add_any(v)
            return
        raise AnsibleFilterError(f"Unsupported value type: {type(x).__name__}")

    if not isinstance(domains_like, dict):
        raise AnsibleFilterError("Expected a dict for CURRENT_PLAY_DOMAINS_ALL")
    for v in domains_like.values():
        _add_any(v)
    return sorted(set(hosts))


def _parents_from(domains: list[str], apex: str, *, min_child_depth: int) -> list[str]:
    _validate(apex)
    parents = set()
    for d in domains:
        _validate(d)
        if not d.endswith(apex):
            continue
        if _depth(d, apex) >= min_child_depth:
            p = _parent_of_child(d, apex)
            if p:
                parents.add(p)
    return sorted(parents)


def _is_global(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except Exception:
        return False


def _build_wildcard_records(
    parents: list[str],
    apex: str,
    *,
    ip4: str,
    ip6: str | None,
    proxied: bool,
    ipv6_enabled: bool,
) -> list[dict]:
    if not isinstance(parents, list):
        raise AnsibleFilterError("parents must be list[str]")
    _validate(apex)
    if not ip4:
        raise AnsibleFilterError("ip4 required")

    records: list[dict] = []

    def _add(name: str, rtype: str, content: str):
        records.append(
            {
                "zone": apex,
                "type": rtype,
                "name": name,  # For apex wildcard, name "*" means "*.apex" in Cloudflare
                "content": content,
                "proxied": bool(proxied),
                "ttl": 1,
            }
        )

    for p in sorted(set(parents)):
        # Create wildcard at apex as well (name="*")
        if p == apex:
            wc = "*"
        else:
            # relative part (drop ".apex"); empty rel is a safety guard
            # — shouldn't happen because p==apex handled above.
            rel = p[: -len(apex) - 1]
            wc = "*" if not rel else f"*.{rel}"
        _add(wc, "A", str(ip4))
        if ipv6_enabled and ip6 and _is_global(str(ip6)):
            _add(wc, "AAAA", str(ip6))
    return records


def wildcard_records(
    current_play_domains_all,  # dict expected when explicit_domains is None
    apex: str,
    ip4: str,
    ip6: str | None = None,
    proxied: bool = False,
    explicit_domains: list[str] | None = None,
    min_child_depth: int = 2,
    ipv6_enabled: bool = True,
) -> list[dict]:
    """
    Build wildcard records:
      - for each parent 'parent.apex' -> create '*.parent' A/AAAA
      - ALWAYS also create '*.apex' (apex wildcard), modeled as name="*"
    Sources:
      - If 'explicit_domains' is provided and non-empty, use it (expects list[str]).
      - Else flatten 'current_play_domains_all' (expects dict).
    """
    # Source domains
    if explicit_domains and len(explicit_domains) > 0:
        if not isinstance(explicit_domains, list) or not all(
            isinstance(x, str) for x in explicit_domains
        ):
            raise AnsibleFilterError("explicit_domains must be list[str]")
        domains = sorted(set(explicit_domains))
    else:
        domains = _flatten_domains_any_structure(current_play_domains_all)

    # Determine parents and ALWAYS include apex for apex wildcard
    parents = _parents_from(domains, apex, min_child_depth=min_child_depth)
    parents = list(set(parents) | {apex})

    return _build_wildcard_records(
        parents,
        apex,
        ip4=ip4,
        ip6=ip6,
        proxied=proxied,
        ipv6_enabled=ipv6_enabled,
    )


class FilterModule:
    def filters(self):
        return {
            "wildcard_records": wildcard_records,
        }
