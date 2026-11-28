from __future__ import annotations

import json
from pathlib import Path


def check(before_file, after_file):
    """
    Args:
        before_file: the state recorded before the backup.
        after_file: the state recorded after the restore.

    Returns:
        The failed proofs.
    """
    before = json.loads(Path(before_file).read_text(encoding="utf-8"))
    after = json.loads(Path(after_file).read_text(encoding="utf-8"))
    failed = []
    if after["sealed"] is False:
        print("workspace drill: OpenBao unseals with the inventory's seal key")
    else:
        failed.append(f"OpenBao reports sealed={after['sealed']} after the restore")
    proofs = (
        (
            "SeaweedFS serves every object version of",
            "versions",
            lambda held: any(held.values()),
        ),
        ("Gitea serves the repository of", "repositories", bool),
        (
            "Keycloak holds the organization and groups of",
            "organizations",
            lambda held: bool(held["organizations"] and held["groups"]),
        ),
    )
    for ws in before["workspaces"]:
        for label, key, filled in proofs:
            held = before[key][ws]
            if not filled(held):
                failed.append(f"{key} of {ws} was empty before the backup")
            elif after[key][ws] != held:
                failed.append(f"{key} of {ws} differ after the restore")
            else:
                print(f"workspace drill: {label} {ws}")
    return failed
