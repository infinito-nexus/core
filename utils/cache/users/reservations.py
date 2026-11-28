from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping


def materialize_domain_label_reservations(
    users: Mapping[str, Any] | None,
    variables: Mapping[str, Any] | None,
    templar: Any = None,
) -> dict[str, Any]:
    """Reserve one username per label of the deployment's primary domain.

    Args:
        users: the users resolved so far.
        variables: play variables; ``DOMAIN_PRIMARY`` wins over
            ``SYSTEM_EMAIL_DOMAIN``.
        templar: optional templar used to render a templated candidate.

    Returns:
        A copy of ``users`` with one ``domain_label_<n>`` entry per label.
    """
    from utils.templating.ansible import _templar_render_best_effort

    def _normalize_domain_candidate(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if ("{{" in text or "{%" in text) and variables:
            text = str(
                _templar_render_best_effort(templar, text, dict(variables))
            ).strip()
        if "://" in text:
            parsed = urlparse(text)
            text = parsed.hostname or text
        return text.split("/", 1)[0].split(":", 1)[0].strip()

    out: dict[str, Any] = copy.deepcopy(dict(users or {}))
    variables = variables or {}

    primary_domain = ""
    for candidate_key in ("DOMAIN_PRIMARY", "SYSTEM_EMAIL_DOMAIN"):
        primary_domain = _normalize_domain_candidate(variables.get(candidate_key))
        if primary_domain:
            break

    for index, label in enumerate(
        label for label in primary_domain.split(".") if label
    ):
        out[f"domain_label_{index}"] = {
            "description": (
                f"Auto generated account reserving the domain label '{label}'"
            ),
            "username": label,
            "accounts": [],
        }

    return out
