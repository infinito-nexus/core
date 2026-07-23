#!/usr/bin/env python3
"""Action plugin for the ``database_query`` module.

The module opens ``query_file`` on the host it runs on. In swarm,
``database_query`` is delegated to the stack host, which has no repo
checkout at ``role_path``, so a target-side open fails with
``could not read query_file``. Reading the file here on the controller and
handing the SQL to the module as ``query`` keeps every role's
``query_file:`` call working in both compose and swarm, without rewriting
call sites.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if task_vars is None:
            task_vars = {}
        result = super().run(tmp, task_vars)

        self._templar.available_variables = task_vars
        args = dict(self._task.args)

        query_file = args.get("query_file")
        if query_file and not args.get("query"):
            query_file = self._templar.template(query_file)
            try:
                with Path(query_file).open(encoding="utf-8") as handle:
                    args["query"] = handle.read()
            except OSError as exc:
                raise AnsibleActionFail(
                    f"could not read query_file {query_file!r} on the controller: {exc}"
                ) from exc
            args.pop("query_file", None)

        result.update(
            self._execute_module(
                module_name="database_query",
                module_args=args,
                task_vars=task_vars,
            )
        )
        return result
