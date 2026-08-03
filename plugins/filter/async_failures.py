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
    nests the original loop value - a model name, a user entry - under its own
    ``item``. Without it a twenty-user batch reports only how many failed.

    Args:
        result: one collected ``async_status`` result.
    """
    fired = result.get("item")
    if isinstance(fired, dict):
        original = fired.get("item")
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


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "async_failures": async_failures,
        }
