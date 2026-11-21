from collections.abc import Mapping

from ansible.errors import AnsibleFilterError


def register_snippet(current, vhost, directive, snippet):
    """Register an inline snippet for the CSP header of one vhost.

    Args:
        current: ``webserver_csp_hashes_extra_by_vhost``, the snippets per
            directive of every vhost an injection pass opened.
        vhost: the vhost domain the snippet is rendered into.
        directive: the CSP directive the snippet's hash belongs to.
        snippet: the inline code exactly as that vhost serves it.

    Returns:
        A copy of ``current`` with ``snippet`` appended once to
        ``<vhost>.<directive>``.

    Raises:
        AnsibleFilterError: no injection pass opened ``vhost``.
    """
    if not isinstance(current, Mapping) or vhost not in current:
        raise AnsibleFilterError(
            f"add_csp_hash: no injection pass opened vhost '{vhost}', so no CSP header reads this snippet"
        )
    try:
        result = dict(current)
        vhost_entry = dict(result[vhost])
        existing = list(vhost_entry.get(directive, []))
        if snippet not in existing:
            existing.append(snippet)
        vhost_entry[directive] = existing
        result[vhost] = vhost_entry
    except Exception as exc:
        raise AnsibleFilterError(f"add_csp_hash failed: {exc}") from exc
    return result


def vhost_snippets(hashes_by_vhost, vhost):
    """Inline snippets registered for the CSP header of one vhost.

    Args:
        hashes_by_vhost: ``webserver_csp_hashes_extra_by_vhost``, the snippets
            per directive of every vhost an injection pass opened; ``None``
            registers none.
        vhost: the vhost the header is rendered for.

    Returns:
        The snippets per directive that the injection pass of ``vhost``
        registered; none when no injection pass opened ``vhost``.
    """
    if hashes_by_vhost is None or vhost not in hashes_by_vhost:
        return {}
    return hashes_by_vhost[vhost]
