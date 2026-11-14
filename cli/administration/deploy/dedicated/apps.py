from __future__ import annotations

import sys


def validate_application_ids(inventory: str, app_ids: list[str]) -> None:
    """Validate requested application IDs using ValidDeployId."""
    if not app_ids:
        return

    from utils.roles.validation.deploy_id import ValidDeployId

    validator = ValidDeployId()
    invalid = validator.validate(inventory, app_ids)

    if not invalid:
        return

    print(f"\n[ERROR] Some application_ids are invalid for inventory {inventory}:\n")
    for app_id, status in invalid.items():
        reasons = []
        if not status.get("in_roles", True):
            reasons.append("not defined as a role")
        if not status.get("in_inventory", True):
            reasons.append("not present in inventory")
        print(f"  - {app_id}: {', '.join(reasons)}")

    sys.exit(1)
