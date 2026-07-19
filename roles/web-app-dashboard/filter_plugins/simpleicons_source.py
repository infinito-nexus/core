import re
import unicodedata

from ansible.errors import AnsibleFilterError


def slugify(name):
    """Convert a display name to a simple-icons slug format.

    Simple Icons slugs are ASCII-only; a title carrying a non-ASCII character
    (e.g. U+2011 NON-BREAKING HYPHEN) otherwise produces a non-ASCII slug that
    crashes the uri probe when it ASCII-encodes the request URL.
    """
    folded = unicodedata.normalize("NFKD", name.strip().lower())
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", "", ascii_only)


def normalize_domain(value):
    """Extract a usable domain string from string/list/dict domain mappings."""
    if isinstance(value, str):
        return value.strip()

    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""

    if isinstance(value, dict):
        for item in value.values():
            normalized = normalize_domain(item)
            if normalized:
                return normalized
        return ""

    return ""


def resolve_simpleicons_base(simpleicons_value, web_protocol="https"):
    """Resolve either a fully rendered base URL or a domain/domain mapping."""
    candidate = (
        simpleicons_value.get("web-svc-simpleicons")
        if isinstance(simpleicons_value, dict)
        and "web-svc-simpleicons" in simpleicons_value
        else simpleicons_value
    )
    normalized = normalize_domain(candidate)
    if not normalized:
        raise AnsibleFilterError("Simple Icons base URL or domain is required")

    if "{{" in normalized or "}}" in normalized or "{%" in normalized:
        raise AnsibleFilterError(
            "Simple Icons base URL/domain must be fully rendered before add_simpleicon_source runs"
        )

    if normalized.startswith(("http://", "https://")):
        return normalized.rstrip("/")

    return f"{web_protocol}://{normalized}"


def simpleicon_slugs(cards):
    """
    Return the ordered, de-duplicated list of Simple Icons slugs for cards that
    carry a title. The probe step (which runs on the stack host, where the
    in-cluster Simple Icons URL is actually routable) loops over this list.

    :param cards: List of card dictionaries (portfolio_cards)
    :return: List of slugs derived from card titles
    """
    slugs = []
    for card in cards:
        title = card.get("title", "")
        if not title:
            continue
        slug = slugify(title)
        if slug not in slugs:
            slugs.append(slug)
    return slugs


def add_simpleicon_source(
    cards,
    reachable_slugs,
    rewrite_value,
    web_protocol="https",
):
    """
    Set `icon.source` on each card whose slug is in `reachable_slugs`.

    Reachability is determined upstream by a stack-host-delegated HTTP probe
    against the in-cluster sync URL. Jinja filters run on the Ansible
    controller, which in swarm has no route to a node's published port, so the
    probe must not happen here. This filter is pure string assembly.

    :param cards: List of card dictionaries (portfolio_cards)
    :param reachable_slugs: Iterable of slugs that returned 200 from the probe
    :param rewrite_value: Fully rendered URL/domain written into icon.source
    :param web_protocol: Protocol to use (https or http) when resolving a bare domain
    :return: New list of cards with icon.source set when the slug is reachable
    """
    rewrite_base = resolve_simpleicons_base(rewrite_value, web_protocol)
    reachable = set(reachable_slugs or [])

    enhanced = []
    for card in cards:
        title = card.get("title", "")
        if not title:
            enhanced.append(card)
            continue
        slug = slugify(title)
        if slug in reachable:
            card.setdefault("icon", {})["source"] = f"{rewrite_base}/{slug}.svg"
        enhanced.append(card)
    return enhanced


class FilterModule:
    """Ansible filter plugin to add simpleicons source URLs to portfolio cards"""

    def filters(self):
        return {
            "add_simpleicon_source": add_simpleicon_source,
            "simpleicon_slugs": simpleicon_slugs,
        }
