"""User-block validation: inventory user keys vs declared user defaults."""

from __future__ import annotations

import sys


def compare_user_keys(users, user_defaults, source) -> list[str]:
    errs: list[str] = []
    for user, conf in users.items():
        if user not in user_defaults:
            print(f"Warning: {source}: Unknown user '{user}'", file=sys.stderr)
            continue
        def_conf = user_defaults[user]
        for key in conf:
            if key in ("password", "credentials"):
                continue
            if key not in def_conf:
                errs.append(f"Missing default for user '{user}': key '{key}'")
    return errs
