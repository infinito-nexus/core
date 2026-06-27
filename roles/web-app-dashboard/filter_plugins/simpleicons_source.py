import os
import re
from pathlib import Path

import certifi
import requests
from ansible.errors import AnsibleFilterError


def get_requests_verify():
    """Return a CA bundle path for outbound HTTPS verification."""
    for env_var in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CA_TRUST_CERT_HOST"):
        candidate = os.environ.get(env_var, "").strip()
        if candidate and Path(candidate).is_file():
            return candidate
    return certifi.where()


def slugify(name):
    """Convert a display name to a simple-icons slug format."""
    # Replace spaces and uppercase letters
    return re.sub(r"\s+", "", name.strip().lower())


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


def add_simpleicon_source(
    cards,
    simpleicons_value,
    web_protocol="https",
    public_url_base=None,
):
    """
    For each card in portfolio_cards, check if an icon exists in the simpleicons server.
    Reachability is probed against `simpleicons_value` (typically the in-cluster
    sync URL — plain HTTP, no redirect, no TLS). The browser-facing `icon.source`
    is set to `public_url_base` when provided (the public Simple Icons URL the
    dashboard frontend can reach), otherwise to the same URL used for the probe.

    :param cards: List of card dictionaries (portfolio_cards)
    :param simpleicons_value: Fully rendered URL/domain used for the HEAD reachability check
    :param web_protocol: Protocol to use (https or http) when resolving a bare domain
    :param public_url_base: Optional separate public base URL written into icon.source
    :return: New list of cards with icon.source set when the icon is reachable
    """
    probe_base = resolve_simpleicons_base(simpleicons_value, web_protocol)
    rewrite_base = (
        resolve_simpleicons_base(public_url_base, web_protocol)
        if public_url_base
        else probe_base
    )

    enhanced = []
    for card in cards:
        title = card.get("title", "")
        if not title:
            enhanced.append(card)
            continue
        # Create slug from title
        slug = slugify(title)
        probe_url = f"{probe_base}/{slug}.svg"
        try:
            resp = requests.head(
                probe_url,
                timeout=2,
                allow_redirects=True,
                verify=get_requests_verify(),
            )
            if resp.status_code == 200:
                card.setdefault("icon", {})["source"] = f"{rewrite_base}/{slug}.svg"
        except requests.RequestException:
            # Ignore network errors and move on
            pass
        enhanced.append(card)
    return enhanced


class FilterModule:
    """Ansible filter plugin to add simpleicons source URLs to portfolio cards"""

    def filters(self):
        return {
            "add_simpleicon_source": add_simpleicon_source,
        }
