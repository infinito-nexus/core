"""Render the applications SPOT once and park it as the play-scoped carrier fact.

Ansible forks a fresh worker per task, so the in-process render cache of
``lookup('applications')`` is cold in every task until something renders in
a place all later workers inherit. This action renders in the worker of one
constructor task and returns the payload as a host fact; every later worker
inherits that fact at fork time and ``get_merged_applications`` serves it
instead of rendering. Sits after the token store in
``tasks/stages/01_constructor.yml`` so the embedded user records already
carry the loaded tokens::

    - name: 🧊 Render the applications SPOT once and carry it into every task's worker
      applications_carrier: {}

The result is masked by the action itself: the fact is the whole rendered
tree, about 0.4 MB with every application's credentials, and printing it at
``-v`` is neither credential debugging nor readable.

Args:
    none. Any argument is an error.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase
from ansible.plugins.loader import lookup_loader

from utils.cache.carrier import APPLICATIONS_RENDERED_FACT


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}
        if self._task.args:
            raise AnsibleActionFail("applications_carrier takes no arguments")

        lookup = lookup_loader.get(
            "applications", loader=self._loader, templar=self._templar
        )
        carrier = lookup.run([], variables=task_vars, carrier=True)[0]

        result.update(
            changed=False,
            ansible_facts={APPLICATIONS_RENDERED_FACT: carrier},
            _ansible_no_log=True,
        )
        return result
