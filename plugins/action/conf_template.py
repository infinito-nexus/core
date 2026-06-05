#!/usr/bin/env python3
#
# Local action plugin: drop-in replacement for `template:` that gates
# delivery on IS_STACK_HOST.
#
# Why this exists: directories like /etc/nginx/conf.d/global/ are
# created exclusively on IS_STACK_HOST (see
# roles/sys-svc-webserver-core/tasks/01_core.yml line 2-3); a raw
# `template:` targeting that tree from a worker aborts with
# "Destination directory does not exist". This wrapper turns the gate
# into a SPOT so every consumer of a .conf.j2 destined for a
# stack-host-only directory inherits the skip semantics without having
# to repeat `when: IS_STACK_HOST | bool` on every task.

from __future__ import annotations

from typing import Any

from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.action.template import ActionModule as TemplateActionModule


class ActionModule(TemplateActionModule):
    """Drop-in `template:` replacement that skips on non-stack hosts.

    Inherits every `template:` argument (src, dest, owner, group,
    backup, validate, ...). Required args (src, dest) are enforced by
    the underlying template module; this wrapper adds no arguments of
    its own.

    Defaults:
        mode: "0644" (only when caller omits it).

    Skip semantics:
        IS_STACK_HOST evaluated to false  ->  returns `skipped: true`
        without touching the filesystem.
    """

    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if task_vars is None:
            task_vars = {}

        self._templar.available_variables = task_vars
        if not _to_bool(
            self._templar.template("{{ IS_STACK_HOST | default(false) | bool }}")
        ):
            return {
                "changed": False,
                "skipped": True,
                "skip_reason": "IS_STACK_HOST is false; worker hosts do not own the destination",
            }

        self._task.args.setdefault("mode", "0644")

        return super().run(tmp=tmp, task_vars=task_vars)
