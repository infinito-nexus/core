#!/usr/bin/env python3
"""Install a package by its logical id from the meta/packages.yml registry.

The registry owns every distro mapping and every acquisition path, so a
role states what it needs and never how to get it::

    - name: "📦 Install the userspace NFS server"
      package_install:
        id: nfs-ganesha

    - name: "📦 Install the storage stack"
      package_install:
        id:
          - nfs-ganesha
          - libntirpc

Distribution repositories, the AUR, COPR, PPA and source builds all run
through here, including the unprivileged build environment the AUR needs.
:mod:`utils.packages.plan` decides which module calls that takes; this
plugin only executes them.

Args:
    id: logical package id, or a list of ids, each declared either in the
        calling role's own meta/packages.yml or in the shared root
        meta/packages.yml.
    state: ``present`` (default) or ``absent``.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase

from utils.packages.plan import (
    GENERIC_PACKAGE,
    STATE_PRESENT,
    STATES,
    ModuleCall,
    build_plan,
)
from utils.packages.registry import build_registry, project_root_from_env, resolve
from utils.packages.schema import ROLE_FILE_META_PACKAGES, PackagesShapeError


class ActionModule(ActionBase):
    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        super().run(tmp, task_vars)
        task_vars = task_vars or {}

        state = self._state()
        distribution, os_family = self._facts(task_vars)

        package_ids = self._package_ids()
        registry = self._registry()
        role = self._role()

        results: list[dict[str, Any]] = []
        skipped: list[str] = []

        for package_id in package_ids:
            spec = self._spec_for(registry, package_id, distribution, os_family, role)
            plan = self._plan_for(spec, state)
            if not plan:
                skipped.append(package_id)
                continue
            results.extend(self._run_plan(plan, task_vars))

        return self._aggregate(results, skipped, distribution)

    def _plan_for(self, spec, state) -> list[ModuleCall]:
        try:
            return build_plan(spec, state)
        except ValueError as exc:
            raise AnsibleActionFail(str(exc)) from exc

    def _run_plan(
        self, plan: list[ModuleCall], task_vars: dict[str, Any]
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for call in plan:
            result = self._execute(call, task_vars)
            results.append(result)
            if result.get("failed"):
                break
        return results

    def _execute(self, call: ModuleCall, task_vars: dict[str, Any]) -> dict[str, Any]:
        args = {k: v for k, v in call.args.items() if v is not None}
        module = self._module_name(call, task_vars)
        if not call.become_user:
            return self._execute_module(
                module_name=module, module_args=args, task_vars=task_vars
            )

        become = self._connection.become
        if become is None:
            raise AnsibleActionFail(
                f"package_install must escalate to '{call.become_user}' to build "
                "this package, but the task runs without become."
            )
        previous = become.get_option("become_user")
        become.set_option("become_user", call.become_user)
        try:
            return self._execute_module(
                module_name=module, module_args=args, task_vars=task_vars
            )
        finally:
            become.set_option("become_user", previous)

    def _module_name(self, call: ModuleCall, task_vars: dict[str, Any]) -> str:
        if call.module != GENERIC_PACKAGE:
            return call.module
        pkg_mgr = str((task_vars.get("ansible_facts") or {}).get("pkg_mgr", "")).strip()
        if not pkg_mgr:
            raise AnsibleActionFail(
                "package_install needs ansible_facts.pkg_mgr to choose a package "
                "manager module; gather facts before installing."
            )
        return pkg_mgr

    def _facts(self, task_vars: dict[str, Any]) -> tuple[str, str]:
        facts = task_vars.get("ansible_facts") or {}
        distribution = str(facts.get("distribution", "")).strip().lower()
        os_family = str(facts.get("os_family", "")).strip()
        if not distribution or not os_family:
            raise AnsibleActionFail(
                "package_install needs gathered facts; ansible_facts.distribution "
                "and ansible_facts.os_family must both be set."
            )
        return distribution, os_family

    def _role(self) -> str | None:
        role = getattr(self._task, "_role", None)
        return str(role.get_name(include_role_fqcn=False)) if role is not None else None

    def _registry(self):
        try:
            return build_registry(project_root_from_env())
        except PackagesShapeError as exc:
            raise AnsibleActionFail(str(exc)) from exc

    def _state(self) -> str:
        state = str(self._task.args.get("state", STATE_PRESENT)).strip()
        if state not in STATES:
            raise AnsibleActionFail(
                f"package_install state {state!r} is not one of {STATES}."
            )
        return state

    def _package_ids(self) -> list[str]:
        raw = self._task.args.get("id")
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        if isinstance(raw, list) and raw:
            return [str(item).strip() for item in raw if str(item).strip()]
        raise AnsibleActionFail(
            "package_install requires 'id' as a package id or a list of ids."
        )

    def _spec_for(
        self,
        registry,
        package_id: str,
        distribution: str,
        os_family: str,
        role: str | None,
    ):
        declaration = registry.get(package_id)
        if declaration is None:
            raise AnsibleActionFail(
                f"Package id '{package_id}' is declared in no meta/packages.yml. "
                f"Declare it in the owning role before installing it."
            )
        if role and not declaration.shared and declaration.role != role:
            raise AnsibleActionFail(
                f"Role '{role}' installs '{package_id}', which "
                f"'{declaration.role}' declares. A role may only install ids "
                f"from its own {ROLE_FILE_META_PACKAGES} or from the shared "
                f"root {ROLE_FILE_META_PACKAGES}. Move the package to the root "
                f"file when more than one role needs it."
            )
        try:
            spec = resolve(declaration, distribution, os_family)
        except PackagesShapeError as exc:
            raise AnsibleActionFail(str(exc)) from exc
        if spec is None:
            raise AnsibleActionFail(
                f"Package '{package_id}' has no mapping for distribution "
                f"'{distribution}' (os_family '{os_family}') in {declaration.path}."
            )
        return spec

    def _aggregate(
        self, results: list[dict[str, Any]], skipped: list[str], distribution: str
    ) -> dict[str, Any]:
        if not results:
            return {
                "changed": False,
                "skipped": True,
                "skip_reason": (
                    f"{', '.join(skipped)} declare nothing to install on {distribution}"
                ),
            }

        failed = [result for result in results if result.get("failed")]
        aggregated: dict[str, Any] = {
            "changed": any(bool(result.get("changed")) for result in results),
            "results": results,
        }
        if skipped:
            aggregated["skipped_ids"] = skipped
        if failed:
            aggregated["failed"] = True
            aggregated["msg"] = "; ".join(
                str(result.get("msg", "package install failed")) for result in failed
            )
        return aggregated
