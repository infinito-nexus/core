"""Failed-job reader: parse the JSON a gh-api run/jobs call returns and keep the
jobs that concluded in failure, as the id/name pairs a later step needs to pull
each job's log.
"""

from __future__ import annotations

import json


def failed_jobs(runs_json: str) -> list[dict]:
    """Return ``{"id", "name"}`` for every job whose ``conclusion`` is
    ``"failure"``, in the order the JSON lists them.

    Accepts either the ``{"jobs": [...]}`` object a gh-api jobs call returns or
    a bare list of job objects.

    Args:
        runs_json: the gh-api run/jobs response as a JSON string.
    """
    data = json.loads(runs_json)
    jobs = data["jobs"] if isinstance(data, dict) else data
    return [
        {"id": job["id"], "name": job["name"]}
        for job in jobs
        if job["conclusion"] == "failure"
    ]
