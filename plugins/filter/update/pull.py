"""Filters ``update_pull_images`` and ``update_pull_summary``: the images a deploy of a host runs, and what pulling them did.

update_pull_images:
    Args:
        applications: ``lookup('applications')`` of the host.
        deployed: ``lookup('application_closure', group_names)``, the roles a
            deploy of the host runs.

    Returns:
        ``{"pull": [...], "built": [...]}``: ``pull`` holds the sorted pull
        reference of every image a deployed role pins for a service it runs
        itself, ``built`` every image such a service builds locally, as
        ``<name> (<role>, ...)``.

update_pull_summary:
    Args:
        results: ``results`` of the loop that ran ``pull.sh`` over ``pull``.
        built: ``built`` of ``update_pull_images``.

    Returns:
        The counts, the references per outcome, and one line per failed
        reference with its error.
"""

from __future__ import annotations

from collections import defaultdict
from functools import partial

from utils.docker.image.custom import custom_image_name
from utils.docker.image.pin import pull_reference
from utils.roles.entity.name import get_entity_name
from utils.update_check.common import FAIL, OK, pinned, services

PULLED = "pulled"
PRESENT = "present"


def update_pull_images(applications, deployed):
    apps = sorted(app for app in deployed if app in applications)
    pull = {
        pull_reference(str(service["image"]).strip(), service["version"])
        for app in apps
        for _, service in pinned(app, applications[app])
    }
    built = defaultdict(set)
    for app in apps:
        for key, service in services(app, applications[app]):
            if not service.get("custom"):
                continue
            name = custom_image_name(service["custom"], partial(get_entity_name, app))
            if not name:
                raise ValueError(f"{app}: services.{key}.custom names no image")
            built[name].add(app)
    return {
        "pull": sorted(pull),
        "built": [
            f"{name} ({', '.join(sorted(roles))})"
            for name, roles in sorted(built.items())
        ],
    }


def _error(result) -> str:
    text = result.get("stderr") or result["msg"]
    return " ".join(line.strip() for line in str(text).splitlines() if line.strip())


def update_pull_summary(results, built):
    done = defaultdict(list)
    failed = []
    for result in results:
        reference = str(result["item"])
        if result.get("failed"):
            failed.append(f"{FAIL} {reference}: {_error(result)}")
            continue
        outcome = str(result["stdout"]).strip()
        if outcome not in (PULLED, PRESENT):
            raise ValueError(f"{reference}: pull.sh printed {outcome!r}")
        done[outcome].append(reference)
    counts = "   ".join(
        [
            f"⬇️ {len(done[PULLED])} pulled",
            f"{OK} {len(done[PRESENT])} already present",
            f"⏭️ {len(built)} built by role",
            f"{FAIL} {len(failed)} failed",
        ]
    )
    return [
        counts,
        f"⬇️ pulled: {', '.join(done[PULLED])}",
        f"{OK} already present: {', '.join(done[PRESENT])}",
        f"⏭️ built by role: {', '.join(built)}",
        *failed,
    ]


class FilterModule:
    def filters(self):
        return {
            "update_pull_images": update_pull_images,
            "update_pull_summary": update_pull_summary,
        }
