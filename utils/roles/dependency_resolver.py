import os
import fnmatch
import re
from typing import Dict, Set, Iterable, Tuple, Optional

import logging


class RoleDependencyResolver:
    _RE_PURE_JINJA = re.compile(r"\s*\{\{\s*[^}]+\s*\}\}\s*$")

    def __init__(self, roles_dir: str):
        self.roles_dir = roles_dir

    # -------------------------- public API --------------------------

    def resolve_transitively(
        self,
        start_roles: Iterable[str],
        *,
        resolve_include_role: bool = True,
        resolve_import_role: bool = True,
        resolve_dependencies: bool = True,
        resolve_run_after: bool = False,
        max_depth: Optional[int] = None,
    ) -> Set[str]:
        to_visit = list(dict.fromkeys(start_roles))
        visited: Set[str] = set()
        depth: Dict[str, int] = {}

        for r in to_visit:
            depth[r] = 0

        while to_visit:
            role = to_visit.pop()
            cur_d = depth.get(role, 0)
            if role in visited:
                continue
            visited.add(role)

            if max_depth is not None and cur_d >= max_depth:
                continue

            for dep in self.get_role_dependencies(
                role,
                resolve_include_role=resolve_include_role,
                resolve_import_role=resolve_import_role,
                resolve_dependencies=resolve_dependencies,
                resolve_run_after=resolve_run_after,
            ):
                if dep not in visited:
                    to_visit.append(dep)
                    depth[dep] = cur_d + 1

        return visited

    def get_role_dependencies(
        self,
        role_name: str,
        *,
        resolve_include_role: bool = True,
        resolve_import_role: bool = True,
        resolve_dependencies: bool = True,
        resolve_run_after: bool = False,
    ) -> Set[str]:
        role_path = os.path.join(self.roles_dir, role_name)
        if not os.path.isdir(role_path):
            return set()

        deps: Set[str] = set()

        if resolve_include_role or resolve_import_role:
            includes, imports = self._scan_tasks(role_path)
            if resolve_include_role:
                deps |= includes
            if resolve_import_role:
                deps |= imports

        if resolve_dependencies:
            deps |= self._extract_meta_dependencies(role_path)

        if resolve_run_after:
            deps |= self._extract_meta_run_after(role_path)

        return deps

    # -------------------------- scanning helpers --------------------------

    def _scan_tasks(self, role_path: str) -> Tuple[Set[str], Set[str]]:
        tasks_dir = os.path.join(role_path, "tasks")
        include_roles: Set[str] = set()
        import_roles: Set[str] = set()

        if not os.path.isdir(tasks_dir):
            return include_roles, import_roles

        all_roles = self._list_role_dirs(self.roles_dir)

        candidates = []
        for root, _, files in os.walk(tasks_dir):
            for f in files:
                if f.endswith(".yml") or f.endswith(".yaml"):
                    candidates.append(os.path.join(root, f))

        from utils.cache.yaml import load_yaml_any

        for file_path in candidates:
            try:
                # Ansible task files are single-document. Wrap the cached
                # parse in a list so the downstream multi-doc loop keeps
                # the same shape.
                doc = load_yaml_any(file_path, default_if_missing=None)
                docs = [doc] if doc is not None else []
            except Exception:
                inc, imp = self._tolerant_scan_file(file_path, all_roles)
                include_roles |= inc
                import_roles |= imp
                continue

            for doc in docs or []:
                if not isinstance(doc, list):
                    continue
                for task in doc:
                    if not isinstance(task, dict):
                        continue
                    if "include_role" in task:
                        include_roles |= self._extract_from_task(
                            task, "include_role", all_roles
                        )
                    if "import_role" in task:
                        import_roles |= self._extract_from_task(
                            task, "import_role", all_roles
                        )

        return include_roles, import_roles

    def _extract_from_task(
        self, task: dict, key: str, all_roles: Iterable[str]
    ) -> Set[str]:
        roles: Set[str] = set()
        spec = task.get(key)
        if not isinstance(spec, dict):
            return roles

        name = spec.get("name")
        loop_val = self._collect_loop_values(task)

        if loop_val is not None:
            for item in self._iter_flat(loop_val):
                cand = self._role_from_loop_item(item, name_template=name)
                if cand:
                    roles.add(cand)

            if (
                isinstance(name, str)
                and name.strip()
                and not self._is_pure_jinja_var(name)
            ):
                pattern = (
                    self._jinja_to_glob(name)
                    if ("{{" in name and "}}" in name)
                    else name
                )
                self._match_glob_into(pattern, all_roles, roles)
            return roles

        if isinstance(name, str) and name.strip():
            if "{{" in name and "}}" in name:
                if self._is_pure_jinja_var(name):
                    return roles
                pattern = self._jinja_to_glob(name)
                self._match_glob_into(pattern, all_roles, roles)
            else:
                roles.add(name.strip())

        return roles

    def _collect_loop_values(self, task: dict):
        for k in ("loop", "with_items", "with_list", "with_flattened"):
            if k in task:
                return task[k]
        return None

    def _iter_flat(self, value):
        if isinstance(value, list):
            for v in value:
                if isinstance(v, list):
                    for x in v:
                        yield x
                else:
                    yield v

    def _role_from_loop_item(self, item, name_template=None) -> Optional[str]:
        tmpl = (name_template or "").strip() if isinstance(name_template, str) else ""

        if isinstance(item, str):
            if tmpl in ("{{ item }}", "{{item}}") or not tmpl or "item" in tmpl:
                return item.strip()
            return None

        if isinstance(item, dict):
            for k in ("role", "name"):
                v = item.get(k)
                if isinstance(v, str) and v.strip():
                    if (
                        tmpl in (f"{{{{ item.{k} }}}}", f"{{{{item.{k}}}}}")
                        or not tmpl
                        or "item" in tmpl
                    ):
                        return v.strip()
        return None

    def _match_glob_into(self, pattern: str, all_roles: Iterable[str], out: Set[str]):
        if "*" in pattern or "?" in pattern or "[" in pattern:
            for r in all_roles:
                if fnmatch.fnmatch(r, pattern):
                    out.add(r)
        else:
            out.add(pattern)

    # -------------------------- meta helpers --------------------------

    def _extract_meta_dependencies(self, role_path: str) -> Set[str]:
        deps: Set[str] = set()
        meta_main = os.path.join(role_path, "meta", "main.yml")
        if not os.path.isfile(meta_main):
            return deps
        try:
            from utils.cache.yaml import load_yaml_any

            meta = load_yaml_any(meta_main, default_if_missing={}) or {}
            raw_deps = meta.get("dependencies", []) if isinstance(meta, dict) else []
            if isinstance(raw_deps, list):
                for item in raw_deps:
                    if isinstance(item, str):
                        deps.add(item.strip())
                    elif isinstance(item, dict):
                        r = item.get("role")
                        if isinstance(r, str) and r.strip():
                            deps.add(r.strip())
        except Exception:
            logging.exception(f"Failed to parse dependencies from {meta_main}")
        return deps

    def _extract_meta_run_after(self, role_path: str) -> Set[str]:
        # Per req-010 `run_after` lives on the role's primary entity at
        # `meta/services.yml.<primary_entity>.run_after`. Delegate to the
        # canonical helper so the primary-entity derivation is in one
        # place, and degrade gracefully if the file is absent.
        from utils.roles.meta_lookup import get_role_run_after

        try:
            entries = get_role_run_after(role_path)
        except Exception:
            logging.exception(
                f"Failed to parse run_after from {role_path}/meta/services.yml"
            )
            return set()
        return {dep for dep in entries if dep}

    # -------------------------- small utils --------------------------

    def _list_role_dirs(self, roles_dir: str) -> list[str]:
        return [
            d
            for d in os.listdir(roles_dir)
            if os.path.isdir(os.path.join(roles_dir, d))
        ]

    @classmethod
    def _is_pure_jinja_var(cls, s: str) -> bool:
        return bool(cls._RE_PURE_JINJA.fullmatch(s or ""))

    @staticmethod
    def _jinja_to_glob(s: str) -> str:
        pattern = re.sub(r"\{\{[^}]+\}\}", "*", s or "")
        pattern = re.sub(r"\*{2,}", "*", pattern)
        return pattern.strip()
