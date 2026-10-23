from __future__ import annotations

from typing import Any

from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.action import ActionBase
from ansible.template import trust_as_template

_IS_STACK_HOST_EXPR = trust_as_template("{{ IS_STACK_HOST | bool }}")


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if task_vars is None:
            task_vars = {}

        self._templar.available_variables = task_vars
        if not _to_bool(self._templar.template(_IS_STACK_HOST_EXPR)):
            return {
                "changed": False,
                "skipped": True,
                "skip_reason": "IS_STACK_HOST is false; this host does not own the destination",
            }

        result = super().run(tmp, task_vars)
        result.update(
            self._execute_module(
                module_name="stack_host_contents",
                module_args=dict(self._task.args),
                task_vars=task_vars,
            )
        )
        return result
