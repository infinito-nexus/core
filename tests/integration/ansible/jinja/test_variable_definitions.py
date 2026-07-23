import contextlib
import logging
import re
import sys
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files, iter_project_files_with_content
from utils.cache.yaml import load_yaml_any, load_yaml_str

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class TestVariableDefinitions(unittest.TestCase):
    """
    Ensures that every Jinja2 variable used in templates/playbooks is defined
    somewhere in the repository (direct var files, set_fact/vars blocks,
    loop_var/register names, Jinja set/for definitions, and Jinja macro parameters).

    If a variable is not defined, the test passes only if a corresponding
    fallback key exists (either "default_<var>" or "defaults_<var>").
    """

    def setUp(self):
        from . import PROJECT_ROOT

        self.project_root = str(PROJECT_ROOT)

        # Collect all variable definition files: roles/*/{vars,defaults}/**/*.yml and group_vars/all/*.yml
        self.var_files: list[str] = []
        roles_prefix = str(Path(self.project_root) / "roles") + "/"
        group_vars_prefix = str(Path(self.project_root) / "group_vars" / "all") + "/"

        def _is_role_var_file(p: str) -> bool:
            if not p.startswith(roles_prefix):
                return False
            parts = p[len(roles_prefix) :].split("/")
            return len(parts) >= 3 and parts[1] in ("vars", "defaults")

        for p in iter_project_files(extensions=(".yml",)):
            if _is_role_var_file(p) or (
                p.startswith(group_vars_prefix)
                and "/" not in p[len(group_vars_prefix) :]
            ):
                self.var_files.append(p)

        # File extensions to scan for Jinja usage/inline definitions
        self.scan_extensions = {".yml", ".j2"}

        # -----------------------
        # Raw-block pattern (ignore any Jinja inside {% raw %}...{% endraw %})
        # Supports trimmed variants: {%- raw -%} ... {%- endraw -%}
        self.raw_block_re = re.compile(
            r"{%\s*-?\s*raw\s*-?\s*%}.*?{%\s*-?\s*endraw\s*-?\s*%}",
            re.DOTALL,
        )

        # -----------------------
        # Regex patterns
        # -----------------------

        # Simple {{ var }} usage with optional Jinja filters after a pipe
        self.simple_var_pattern = re.compile(r"{{\s*([a-zA-Z_]\w*)\s*(?:\|[^}]*)?}}")

        # {% set var = ... %}   (allow trimmed variants)
        self.jinja_set_def = re.compile(r"{%\s*-?\s*set\s+([a-zA-Z_]\w*)\s*=")

        # {% set var %} ... {% endset %}  (block-style set)
        self.jinja_set_block_def = re.compile(r"{%\s*-?\s*set\s+([a-zA-Z_]\w*)\s*-?%}")

        # {% for x in ... %}  or  {% for k, v in ... %}   (allow trimmed variants)
        self.jinja_for_def = re.compile(
            r"{%\s*-?\s*for\s+([a-zA-Z_]\w*)(?:\s*,\s*([a-zA-Z_]\w*))?\s+in"
        )

        # {% macro name(param1, param2=..., *varargs, **kwargs) %}   (allow trimmed variants)
        self.jinja_macro_def = re.compile(
            r"{%\s*-?\s*macro\s+[a-zA-Z_]\w*\s*\((.*?)\)\s*-?%}"
        )

        # Ansible YAML anchors for inline var declarations
        # Support short and FQCN forms, plus inline dict after colon
        self.ansible_set_fact = re.compile(
            r"^(?:\s*-\s*)?(?:ansible\.builtin\.)?set_fact\s*:\s*(\{[^}]*\})?\s*$"
        )
        self.ansible_vars_block = re.compile(r"^(?:\s*[-]\s*)?vars\s*:\s*$")
        self.ansible_loop_var = re.compile(r"^\s*loop_var\s*:\s*([a-zA-Z_]\w*)")
        self.mapping_key = re.compile(r"^\s*([a-zA-Z_]\w*)\s*:\s*")
        self.register_pat = re.compile(r"^\s*register\s*:\s*([a-zA-Z_]\w*)")

        # Templated set_fact / vars key, e.g. "{{ prefix }}_HOST_NODE": such a
        # dynamic key defines every concrete '<x>_HOST_NODE' fact, so it is
        # registered as a name pattern rather than a single literal.
        self.templated_mapping_key = re.compile(r'^\s*(["\'])(.*?\{\{.*?\}\}.*?)\1\s*:')

        # Bare vars in YAML list expressions wie:
        #   - SOME_VAR | bool
        #   - OTHER_VAR | length > 0
        self.bare_list_expr_var = re.compile(r"^\s*-\s*([a-zA-Z_]\w*)\b")

        # -----------------------
        # Collect "defined" names
        # -----------------------
        self.defined = set()
        self.dynamic_defined_patterns: list[re.Pattern] = []

        # 1) Keys from var files (top-level dict keys)
        for vf in self.var_files:
            try:
                data = load_yaml_any(vf)
                if isinstance(data, dict):
                    self.defined.update(data.keys())
            except (OSError, yaml.YAMLError) as exc:
                logger.debug(
                    "Skipping variable file %s while collecting definitions: %s",
                    vf,
                    exc,
                )

        # 2) Inline definitions across all scanned files
        for path, content in iter_project_files_with_content(
            extensions=tuple(self.scan_extensions)
        ):
            # Track when we're inside set_fact:/vars: blocks to also extract mapping keys.
            in_set_fact = False
            set_fact_indent = 0
            in_vars_block = False
            vars_block_indent = 0

            try:
                for line in content.splitlines(keepends=True):
                    stripped = line.lstrip()
                    indent = len(line) - len(stripped)

                    # --- set_fact (short and FQCN), supports inline and block forms
                    m_sf = self.ansible_set_fact.match(stripped)
                    if m_sf:
                        inline_map = m_sf.group(1)
                        if inline_map:
                            # Inline mapping: set_fact: { a: 1, b: 2 }
                            try:
                                data = load_yaml_str(inline_map)
                                if isinstance(data, dict):
                                    self.defined.update(
                                        k for k in data if isinstance(k, str)
                                    )
                            except yaml.YAMLError as exc:
                                logger.debug(
                                    "Skipping inline set_fact mapping in %s: %s",
                                    path,
                                    exc,
                                )
                            # do not enter block mode if inline present
                            in_set_fact = False
                        else:
                            # Block mapping: keys on subsequent indented lines
                            in_set_fact = True
                            set_fact_indent = indent
                            continue

                    if in_set_fact:
                        if indent > set_fact_indent and stripped.strip():
                            m = self.mapping_key.match(stripped)
                            if m:
                                self.defined.add(m.group(1))
                            else:
                                mt = self.templated_mapping_key.match(stripped)
                                if mt:
                                    self._add_dynamic_pattern(mt.group(2))
                        elif indent <= set_fact_indent and stripped:
                            in_set_fact = False

                    # --- vars: block (collect mapping keys)
                    if self.ansible_vars_block.match(stripped):
                        in_vars_block = True
                        vars_block_indent = indent
                        continue

                    if in_vars_block:
                        if indent > vars_block_indent and stripped.strip():
                            m = self.mapping_key.match(stripped)
                            if m:
                                self.defined.add(m.group(1))
                        elif indent <= vars_block_indent and stripped:
                            in_vars_block = False

                    # --- Always scan every line (including inside blocks) for Jinja definitions
                    for m in self.jinja_set_def.finditer(line):
                        self.defined.add(m.group(1))

                    # Count block-style set as a definition, too
                    for m in self.jinja_set_block_def.finditer(line):
                        self.defined.add(m.group(1))

                    for m in self.jinja_for_def.finditer(line):
                        self.defined.add(m.group(1))
                        if m.group(2):
                            self.defined.add(m.group(2))

                    for m in self.jinja_macro_def.finditer(line):
                        params_blob = m.group(1)
                        params = [p.strip() for p in params_blob.split(",")]
                        for raw_p in params:
                            if not raw_p:
                                continue
                            p = raw_p.lstrip("*")
                            name = p.split("=", 1)[0].strip()
                            if re.match(r"^[a-zA-Z_]\w*$", name):
                                self.defined.add(name)

                    m_loop = self.ansible_loop_var.match(stripped)
                    if m_loop:
                        self.defined.add(m_loop.group(1))

                    m_reg = self.register_pat.match(stripped)
                    if m_reg:
                        self.defined.add(m_reg.group(1))

            except Exception:
                logger.warning("Failed to parse file: %s", path, exc_info=True)

    def _add_dynamic_pattern(self, key_text: str) -> None:
        """Turn a templated fact key like '{{ prefix }}_HOST_NODE' into a name
        pattern '^[A-Za-z0-9_]+_HOST_NODE$' so every concrete fact it sets counts
        as defined."""
        parts = re.split(r"\{\{.*?\}\}", key_text)
        if len(parts) < 2:
            return
        # Need a real literal segment, else a pure '{{ x }}' key compiles to a
        # catch-all that would match (and silently define) every variable name.
        if not any(p.strip().strip("_") for p in parts):
            return
        regex = "[A-Za-z0-9_]+".join(re.escape(p) for p in parts)
        with contextlib.suppress(re.error):
            self.dynamic_defined_patterns.append(re.compile("^" + regex + "$"))

    def test_all_used_vars_are_defined(self):
        """
        Scan all template/YAML files for {{ var }} usage and fail if a variable
        is not known as defined and has no fallback keys (default_<var>/defaults_<var>).
        """
        undefined_uses = []

        for path, content in iter_project_files_with_content(
            extensions=tuple(self.scan_extensions)
        ):
            try:
                # Mask {% raw %} ... {% endraw %} blocks
                def _mask_raw(m):
                    s = m.group(0)
                    return re.sub(r"[^\n]", " ", s)

                content_wo_raw = self.raw_block_re.sub(_mask_raw, content)

                for lineno, line in enumerate(content_wo_raw.splitlines(True), 1):
                    for m in self.simple_var_pattern.finditer(line):
                        var = m.group(1)

                        if var in (
                            "lookup",
                            "role_name",
                            "domains",
                            "item",
                            "inventory_hostname",
                            "ansible_play_hosts",
                            "role_path",
                            "playbook_dir",
                            "ansible_become_password",
                            "inventory_dir",
                            "ansible_env",
                            "ansible_memtotal_mb",
                            "omit",
                            "group_names",
                            "ansible_processor_vcpus",
                            "ansible_service_mgr",
                            "ansible_distribution_release",
                            "ansible_distribution",
                            "ansible_os_family",
                            "ansible_virtualization_type",
                            "ansible_virtualization_role",
                        ):
                            continue

                        if (
                            var not in self.defined
                            and f"default_{var}" not in self.defined
                            and f"defaults_{var}" not in self.defined
                            and not any(
                                p.match(var) for p in self.dynamic_defined_patterns
                            )
                        ):
                            undefined_uses.append(
                                f"{path}:{lineno}: '{{{{ {var} }}}}' used but not defined"
                            )
                    # Handle bare vars in list expressions, e.g.:
                    #   - SYSTEMD_MANAGER_RESET_PURGE | bool
                    stripped = line.lstrip()

                    # Heuristic: "- VAR | ..." but not a mapping ("key: value")
                    if (
                        stripped.startswith("- ")
                        and "|" in stripped
                        and ":" not in stripped
                    ):
                        m_expr = self.bare_list_expr_var.match(stripped)
                        if m_expr:
                            var = m_expr.group(1)

                            if var not in (  # noqa: SIM102  the long literal whitelist is more readable as a separate guard
                                "lookup",
                                "role_name",
                                "domains",
                                "item",
                                "inventory_hostname",
                                "ansible_play_hosts",
                                "role_path",
                                "playbook_dir",
                                "ansible_become_password",
                                "inventory_dir",
                                "ansible_env",
                                "ansible_memtotal_mb",
                                "omit",
                                "group_names",
                                "ansible_processor_vcpus",
                                "ansible_distribution_release",
                                "ansible_distribution",
                                "ansible_os_family",
                                "ansible_virtualization_type",
                                "ansible_virtualization_role",
                                "not",
                                "and",
                                "or",
                            ):
                                if (
                                    var not in self.defined
                                    and f"default_{var}" not in self.defined
                                    and f"defaults_{var}" not in self.defined
                                    and not any(
                                        p.match(var)
                                        for p in self.dynamic_defined_patterns
                                    )
                                ):
                                    undefined_uses.append(
                                        f"{path}:{lineno}: bare var '{var}' used but not defined"
                                    )

            except Exception as e:
                print(
                    f"WARNING: Skipping file due to exception ({path}): {e}",
                    file=sys.stderr,
                )

        if undefined_uses:
            self.fail(
                "Undefined Jinja2 variables found (no fallback 'default_' or 'defaults_' key):\n"
                + "\n".join(undefined_uses)
            )


if __name__ == "__main__":
    unittest.main()
