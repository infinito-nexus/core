"""Render the applications SPOT once and park it as the play-scoped carrier fact.

Ansible forks a fresh worker per task, so the in-process render cache of
``lookup('applications')`` is cold in every task until something renders in
a place all later workers inherit. This action renders in the worker of one
constructor task and returns the payload as a host fact; every later worker
inherits that fact at fork time and ``get_merged_applications`` serves it
instead of rendering::

    - name: 🧊 Render the applications SPOT once and carry it into every task's worker
      applications_carrier: {}

``tasks/stages/01_constructor.yml`` parks three of them: a block-scoped one
for the merge block, which it drops again at the block's end, one after the
``add_host`` tasks for the swarm bootstrap roles, parked only when
``DEPLOYMENT_MODE`` is ``swarm``, and the stage-wide one after the token store. ``merged_applications_cache_key`` reads ``group_names`` and the
tokens file's path and content digest, so a carrier whose groups or tokens no
longer match is rejected and the reader renders afresh::

    - name: 🧊 Drop the merge-block carrier so later stages re-render
      applications_carrier:
        clear: true

``tasks/utils/setup/role.yml`` parks one after every role and
``roles/sys-token-store/tasks/write.yml`` one after every persisted token;
where the key still matches they serve the carried payload without rendering.

The result is masked by the action itself: the fact is the whole rendered
tree, about 0.4 MB with every application's credentials, and printing it at
``-v`` is neither credential debugging nor readable.

Args:
    clear: drop the carrier fact instead of rendering. Defaults to false.
        Any other argument is an error.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.action import ActionBase
from ansible.plugins.loader import lookup_loader

from utils.cache.carrier import APPLICATIONS_RENDERED_FACT, revalidate_tokens_file


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}
        args = self._task.args or {}
        unexpected = sorted(set(args) - {"clear"})
        if unexpected:
            raise AnsibleActionFail(
                f"applications_carrier: unknown argument(s) {', '.join(unexpected)}; "
                "the only argument is 'clear'"
            )

        if boolean(args.get("clear", False)):
            result.update(
                changed=False, ansible_facts={APPLICATIONS_RENDERED_FACT: None}
            )
            return result

        revalidate_tokens_file(task_vars)
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
