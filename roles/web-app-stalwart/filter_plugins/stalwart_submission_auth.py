from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleFilterError

SUBMISSION_TERMS = {
    "saslMechanisms": "[plain]",
    "require": "true",
}


def _terms(field: str, expression: Any) -> tuple[list[dict[str, Any]], Any]:
    if isinstance(expression, str):
        return [], expression
    if not isinstance(expression, dict) or "else" not in expression:
        raise AnsibleFilterError(
            f"stalwart MtaStageAuth: '{field}' is no expression, got {expression!r}"
        )
    match = expression.get("match") or {}
    return [match[key] for key in sorted(match, key=int)], expression["else"]


def stalwart_submission_auth(auth: dict[str, Any], port: Any) -> dict[str, Any]:
    """
    Args:
        auth: the live ``x:MtaStageAuth`` singleton.
        port: the container port of the submission listener.

    Returns:
        ``{field: expression}`` for every field of ``SUBMISSION_TERMS`` whose
        expression does not yet open with the term for ``port``, that term
        first and the live terms after it in their order; ``{}`` when both
        already open with it.

    Raises:
        AnsibleFilterError: ``auth`` is no mapping, a field is missing or holds
            no expression, or ``port`` is no port number.
    """
    if not isinstance(auth, dict):
        raise AnsibleFilterError(
            f"stalwart MtaStageAuth: a mapping is required, got {auth!r}"
        )
    try:
        number = int(port)
    except (TypeError, ValueError) as exc:
        raise AnsibleFilterError(
            f"stalwart MtaStageAuth: no port number: {port!r}"
        ) from exc
    condition = f"local_port == {number}"
    update: dict[str, Any] = {}
    for field, then in SUBMISSION_TERMS.items():
        if field not in auth:
            raise AnsibleFilterError(f"stalwart MtaStageAuth: '{field}' is missing")
        terms, fallback = _terms(field, auth[field])
        term = {"if": condition, "then": then}
        if terms[:1] == [term]:
            continue
        ordered = [term, *(t for t in terms if t.get("if") != condition)]
        update[field] = {
            "match": {str(index): item for index, item in enumerate(ordered)},
            "else": fallback,
        }
    return update


class FilterModule:
    def filters(self):
        return {"stalwart_submission_auth": stalwart_submission_auth}
