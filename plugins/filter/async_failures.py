"""Filter `async_failures`: reduce reaped ``async_status`` results to the
failures a deploy should stop for.

``poll: 0`` makes a task fire and forget, so its own ``changed_when`` and
``failed_when`` never see an outcome. The outcome only exists once the job is
collected with ``async_status``, and collecting it is where the verdict has to
be made -- for a whole batch at once, so one run reports every broken job
rather than the first.

A job counts as failed when it never finished, when the module reported
``failed``, or when a command returned a non-zero ``rc``. What distinguishes a
real failure from an idempotent no-op differs per API and lives in different
keys: modules put it in ``msg`` (cloudflare answers "An identical record
already exists"), commands put it in ``stdout`` (``ollama pull`` prints "up to
date" and exits non-zero). Both are searched, so a caller passes the tolerated
phrasing and does not have to know which key carries it.
"""

from __future__ import annotations

import re
from typing import Any

_UNFINISHED = "job did not finish"
_UNREACHABLE = "async job result unavailable (was it started on another host?)"
_SUPPRESSED = "failed_when_suppressed_exception"


def _said(result: dict) -> str:
    """Everything the job said, across the keys modules and commands use.

    Args:
        result: one collected ``async_status`` result.
    """
    parts = (result.get("msg"), result.get("stdout"), result.get("stderr"))
    return " ".join(str(p) for p in parts if p).strip()


def _which(result: dict) -> str:
    """Name the job, so a batch failure says which item broke.

    A collected result nests the fired result under ``item``, which in turn
    nests the original loop value - a model name, a user entry - under the key
    ansible used for it. That key is ``item`` unless ``loop_control.loop_var``
    renamed it, in which case the fired result records the name it chose under
    ``ansible_loop_var``. Without it a twenty-user batch reports only how many
    failed.

    Args:
        result: one collected ``async_status`` result.
    """
    fired = result.get("item")
    if isinstance(fired, dict):
        original = fired.get(fired.get("ansible_loop_var") or "item")
        if original not in (None, ""):
            if isinstance(original, dict):
                for key in ("key", "name", "model"):
                    if original.get(key):
                        return str(original[key])
            else:
                return str(original)
    return str(result.get("ansible_job_id") or "unidentified job")


def _is_failure(result: dict) -> bool:
    """True when the job did not finish, finished badly, or could not be read.

    Collecting with ``failed_when: false`` is what lets one run report every
    broken job instead of aborting on the first, but it also swallows the error
    ansible raises when the job file is not there at all - and that case comes
    back as ``finished: true`` with no outcome keys, so it would otherwise read
    as success. Ansible marks every suppressed failure with
    ``failed_when_suppressed_exception``; a job that really succeeded never
    carries it.

    Args:
        result: one collected ``async_status`` result.
    """
    if _SUPPRESSED in result:
        return True
    if int(result.get("finished") or 0) != 1:
        return True
    if result.get("failed"):
        return True
    return int(result.get("rc") or 0) != 0


def async_failures(results: Any, tolerate: Any) -> list[str]:
    """Describe every reaped job that failed and was not tolerated.

    Args:
        results: the ``results`` list of a looped ``async_status`` task.
        tolerate: substrings that mark an answer as an accepted no-op.
    """
    tolerated = [str(t) for t in (tolerate or [])]
    out: list[str] = []
    for result in results or []:
        if not isinstance(result, dict) or not _is_failure(result):
            continue
        said = _said(result)
        if said and any(phrase in said for phrase in tolerated):
            continue
        if not said:
            said = _UNREACHABLE if _SUPPRESSED in result else _UNFINISHED
        out.append(f"{_which(result)}: {said}")
    return out


def _original(result: dict) -> Any:
    """The loop value a result belongs to, reaped or polled in place.

    Args:
        result: one reaped ``async_status`` result, or one result of a looped
            task that polled its own job.
    """
    fired = result.get("item")
    if isinstance(fired, dict) and "ansible_loop_var" in fired:
        return fired.get(fired["ansible_loop_var"])
    return fired


def async_retry_split(
    results: Any, tolerate: Any, transient: Any
) -> dict[str, list[dict]]:
    """Sort failed jobs into those worth another attempt and those to stop for.

    A job that never finished always counts as transient: a hung request, or a
    job that died before its module ran and left its job file at "started".
    Any other failure is transient only when what it said matches ``transient``.

    Args:
        results: reaped ``async_status`` results, or the results of a looped
            task that polled its own jobs.
        tolerate: substrings that mark an answer as an accepted no-op.
        transient: regular expressions on what a failed job said that mark the
            failure as worth retrying.

    Returns:
        ``{"retry": [...], "failed": [...]}``, each entry
        ``{"item": <loop value>, "error": <what the job said>}``.
    """
    tolerated = [str(t) for t in (tolerate or [])]
    patterns = [re.compile(str(p)) for p in (transient or [])]
    split: dict[str, list[dict]] = {"retry": [], "failed": []}
    for result in results or []:
        if not isinstance(result, dict) or not _is_failure(result):
            continue
        said = _said(result)
        if said and any(phrase in said for phrase in tolerated):
            continue
        unreadable = _SUPPRESSED in result
        unfinished = not unreadable and int(result.get("finished") or 0) != 1
        retry = unfinished or any(p.search(said) for p in patterns)
        if not said:
            said = _UNREACHABLE if unreadable else _UNFINISHED
        split["retry" if retry else "failed"].append(
            {"item": _original(result), "error": said}
        )
    return split


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "async_failures": async_failures,
            "async_retry_split": async_retry_split,
        }
