"""Turn the module results of one plan into a single task result.

Pure data in, pure data out, so the reporting is testable without an
Ansible connection.
"""

from __future__ import annotations

from typing import Any


def failure_message(result: dict[str, Any]) -> str:
    """Describe one failed module call.

    Args:
        result: the module's own return dict, tagged with the module that
            produced it. A module that dies on an unhandled exception never
            carries ``msg`` -- the AnsiballZ wrapper returns only ``failed``
            and ``exception``, whose event holds the sole account of what
            went wrong.
    """
    module = result["module"]
    exception = result.get("exception")
    event_msg = getattr(getattr(exception, "event", None), "msg", None)
    for value in (
        result.get("msg"),
        event_msg,
        exception,
        result.get("module_stderr"),
        result.get("stderr"),
    ):
        if value:
            return f"{module}: {str(value).strip()}"
    return f"{module}: failed without reporting anything"


def aggregate(
    results: list[dict[str, Any]], skipped: list[str], distribution: str
) -> dict[str, Any]:
    """Fold every module result of one package_install task into one result.

    Args:
        results: the module results, in execution order.
        skipped: package ids that declared nothing for this distribution.
        distribution: the target distribution, named in the skip reason.
    """
    if not results:
        return {
            "changed": False,
            "skipped": True,
            "skip_reason": (
                f"{', '.join(skipped)} declare nothing to install on {distribution}"
            ),
        }

    failed = [result for result in results if result.get("failed")]
    aggregated: dict[str, Any] = {
        "changed": any(bool(result.get("changed")) for result in results),
        "results": results,
    }
    if skipped:
        aggregated["skipped_ids"] = skipped
    if failed:
        aggregated["failed"] = True
        aggregated["msg"] = "; ".join(failure_message(r) for r in failed)
    return aggregated
