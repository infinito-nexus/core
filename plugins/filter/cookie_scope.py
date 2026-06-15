def _domain_strings(domains):
    """Flatten the value returned by lookup('domains', app) into a flat list of
    domain strings. The lookup yields a dict ({key: domain}), a list, or a bare
    string depending on the role's server.domains shape, so normalise all three.
    """
    if isinstance(domains, dict):
        candidates = domains.values()
    elif isinstance(domains, str):
        candidates = [domains]
    else:
        candidates = domains or []
    return [str(d).strip() for d in candidates if str(d).strip()]


def common_dns_suffix(domains):
    """
    Return the longest dot-delimited DNS suffix shared by every domain.
    A single-domain input returns that domain unchanged, so single-domain
    apps keep their exact host while a multi-domain app (e.g. filer/master/api
    under one base) collapses to the shared parent that a session cookie can
    span across all of them.
    """
    cleaned = _domain_strings(domains)
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]

    reversed_labels = [d.split(".")[::-1] for d in cleaned]
    common = []
    for group in zip(*reversed_labels, strict=False):
        if len(set(group)) == 1:
            common.append(group[0])
        else:
            break
    return ".".join(reversed(common))


class FilterModule:
    def filters(self):
        return {"common_dns_suffix": common_dns_suffix}
