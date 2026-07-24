#!/usr/bin/env python3
from __future__ import annotations

from typing import Any

from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.action.template import ActionModule as TemplateActionModule
from ansible.template import trust_as_template

# Exception: trust_as_template is required because Ansible 2.19+ refuses to render Python-constructed strings without the TrustedAsTemplate tag.
_IS_STACK_HOST_EXPR = trust_as_template("{{ IS_STACK_HOST | bool }}")


class ActionModule(TemplateActionModule):
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

        self._task.args.setdefault("mode", "0644")
        # Exception: compose.yml.j2 aligns {% set %}/{% if %} to two spaces and
        # {% include %} to four; that layout only renders correctly with
        # lstrip_blocks, which strips a block tag's own leading indentation
        # without eating the preceding newline the way a {%- dash would.
        if str(self._task.args.get("src", "")).endswith("compose.yml.j2"):
            self._task.args.setdefault("lstrip_blocks", True)
        return super().run(tmp=tmp, task_vars=task_vars)
