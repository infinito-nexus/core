"""Render the applications and users SPOTs once and park them as play-scoped carrier facts.

Ansible forks a fresh worker per task, so the in-process render caches of
``lookup('applications')`` and ``lookup('users')`` are cold in every task
until something renders in a place all later workers inherit. This action
renders in the worker of one constructor task and returns both payloads as
host facts; every later worker inherits them at fork time and
``get_merged_applications`` / ``get_merged_users`` serve them instead of
rendering. The users carrier is keyed like the applications carrier plus
``inventory_hostname``::

    - name: 🧊 Render the applications SPOT once and carry it into every task's worker
      applications_carrier: {}

``tasks/stages/01_constructor.yml`` parks three of them: a block-scoped one
for the merge block, which it drops again at the block's end, one after the
``add_host`` tasks for the swarm bootstrap roles, parked only when
``DEPLOYMENT_MODE`` is ``swarm``, and the stage-wide one after the token store. ``merged_applications_cache_key`` reads ``group_names`` and a
digest of the tokens the users are hydrated from (the tokens file, or the
``sys_token_store_users`` fact once the token store loaded; both key alike for
the same tokens), so a carrier whose groups or tokens no longer match is
rejected and the reader renders afresh::

    - name: 🧊 Drop the merge-block carrier so later stages re-render
      applications_carrier:
        clear: true

``tasks/utils/setup/role.yml`` parks one after every role,
``tasks/utils/load/app.yml`` one after every nested application load and
``roles/sys-token-store/tasks/write_many.yml`` one after every store write;
where the key still matches they serve the carried payload without rendering,
and a users carrier that still matches is left in place instead of being
returned again.

The result is masked by the action itself: the facts are the whole rendered
trees, about 0.4 MB with every application's and user's credentials, and
printing them at ``-v`` is neither credential debugging nor readable.

Args:
    clear: drop both carrier facts instead of rendering. Defaults to false.
        Any other argument is an error.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.action import ActionBase
from ansible.plugins.loader import lookup_loader

from utils.cache.carrier import (
    APPLICATIONS_RENDERED_FACT,
    USERS_RENDERED_FACT,
    _carried_users,
    revalidate_tokens_file,
)


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
                changed=False,
                ansible_facts={
                    APPLICATIONS_RENDERED_FACT: None,
                    USERS_RENDERED_FACT: None,
                },
            )
            return result

        revalidate_tokens_file(task_vars)
        render_vars = dict(task_vars)
        render_vars.pop("application_id", None)
        previous = self._templar.available_variables
        self._templar.available_variables = render_vars
        try:
            carriers = {
                fact: lookup_loader.get(
                    name, loader=self._loader, templar=self._templar
                ).run([], variables=render_vars, carrier=True)[0]
                for fact, name in (
                    (APPLICATIONS_RENDERED_FACT, "applications"),
                    (USERS_RENDERED_FACT, "users"),
                )
            }
        finally:
            self._templar.available_variables = previous

        users_key = carriers[USERS_RENDERED_FACT]["key"]
        if _carried_users(task_vars, (users_key[0], tuple(users_key[1]))) is not None:
            del carriers[USERS_RENDERED_FACT]

        result.update(
            changed=False,
            ansible_facts=carriers,
            _ansible_no_log=True,
        )
        return result
