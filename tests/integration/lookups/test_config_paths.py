import fnmatch
import re
import unittest
from pathlib import Path

import yaml  # requires PyYAML
from plugins.filter.get_role import get_role
from utils.applications.config import get, ConfigEntryNotSetError
from utils.cache.applications import get_application_defaults
from utils.cache.users import get_user_defaults
from utils.cache.files import iter_project_files_with_content


def _role_id_from_path(file_path: Path) -> str | None:
    """Return the role id when ``file_path`` lives under ``roles/<role>/...``.

    Used by the wildcard-concat scanner to resolve the role context for
    lookups whose app argument is a Jinja variable (typically
    ``application_id``). Returns ``None`` for files outside the roles tree.
    """
    parts = file_path.parts
    try:
        idx = parts.index("roles")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


def _expr_to_wildcard_path(expr: str) -> str | None:
    """Convert a `~`-concatenated lookup-path expression into a dotted path
    with `*` placeholders for every Jinja variable segment.

    Examples:
      ``'services.' ~ entity_name ~ '.ports.inter'`` -> ``services.*.ports.inter``
      ``'services.openldap.ports.local.' ~ _ldap_protocol`` -> ``services.openldap.ports.local.*``

    Returns ``None`` when the expression cannot be parsed (mismatched quotes,
    unrecognised operators, etc.) so the caller can skip it instead of
    raising.
    """
    parts: list[str] = []
    i = 0
    n = len(expr)
    expecting_value = True
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if expecting_value:
            if ch in ("'", '"'):
                quote = ch
                j = expr.find(quote, i + 1)
                if j == -1:
                    return None
                parts.append(expr[i + 1 : j])
                i = j + 1
            else:
                # Bareword variable: any run of non-whitespace, non-`~` chars.
                j = i
                while j < n and not expr[j].isspace() and expr[j] != "~":
                    j += 1
                token = expr[i:j].strip()
                if not token:
                    return None
                parts.append("*")
                i = j
            expecting_value = False
        else:
            if ch == "~":
                expecting_value = True
                i += 1
            else:
                # Anything other than ~ between values is unexpected.
                return None
    if expecting_value:
        return None
    raw = "".join(parts)
    # Normalise: collapse repeated `*` between dots (a literal segment
    # ending with `.` followed by a wildcard part collapses cleanly when
    # joined). Then split on `.` and drop empty segments at the edges
    # caused by leading/trailing dots in the literals.
    segments = [seg for seg in raw.split(".") if seg != ""]
    return ".".join(segments) if segments else None


def _match_wildcard_segment(mapping: dict, segment: str) -> bool:
    """Return ``True`` when ``segment`` matches at least one top-level key
    in ``mapping``. ``segment`` may contain ``*`` glob characters; bare
    ``*`` matches any key."""
    if not isinstance(mapping, dict):
        return False
    if "*" not in segment:
        return segment in mapping
    return any(fnmatch.fnmatchcase(k, segment) for k in mapping.keys())


def _match_wildcard_path(mapping: dict, dotted: str) -> bool:
    """Return ``True`` when ``dotted`` matches at least one nested path in
    ``mapping``. A segment may be a literal key, a bare ``*`` (matches any
    single key), or a glob containing ``*`` (matches any key whose name
    matches the glob, e.g. ``*_jwt_secret`` matches ``whiteboard_jwt_secret``).
    A variable that touches a literal without a dot separator (for example
    ``'credentials.' ~ X ~ '_jwt_secret'`` -> ``credentials.*_jwt_secret``)
    therefore resolves correctly.
    """
    keys = dotted.split(".")

    def walk(cur, idx: int) -> bool:
        if idx == len(keys):
            return True
        if not isinstance(cur, dict):
            return False
        key = keys[idx]
        if "*" not in key:
            if key not in cur:
                return False
            return walk(cur[key], idx + 1)
        # Glob match: any child whose key matches the pattern.
        return any(
            fnmatch.fnmatchcase(child_key, key) and walk(child_val, idx + 1)
            for child_key, child_val in cur.items()
        )

    return walk(mapping, 0)


class TestGetAppConfPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup paths
        root = Path(__file__).resolve().parents[3]
        cls.root = root
        cls.application_defaults = get_application_defaults(roles_dir=root / "roles")
        cls.user_defaults = get_user_defaults(roles_dir=root / "roles")

        # Preload role schemas: map application_id -> schema dict
        cls.role_schemas = {}
        cls.role_for_app = {}
        roles_path = str(root / "roles")
        for app_id in cls.application_defaults:
            try:
                role = get_role(app_id, roles_path)
                cls.role_for_app[app_id] = role
                schema_file = root / "roles" / role / "meta" / "schema.yml"
                with schema_file.open(encoding="utf-8") as sf:
                    schema = yaml.safe_load(sf) or {}
                cls.role_schemas[app_id] = schema
            except Exception:
                # skip apps without schema or role
                continue

        # Regex to find lookup('config', app_id, 'path') calls
        cls.pattern = re.compile(
            r"lookup\(\s*['\"]config['\"]\s*,\s*([^,]+?)\s*,\s*['\"]([^'\"]+)['\"]"
        )

        # Regex to find any lookup('config', <app>, <path-expr>) call where
        # <path-expr> is a `~`-concatenation of quoted literals and barewords.
        # The literal-path regex above only captures the FIRST quoted string
        # and never validates the full constructed path, so a wrong path
        # built via concat (for example
        # 'services.' ~ entity_name ~ '.port' against a role whose meta
        # declares 'services.<entity>.ports.inter') used to slip through
        # silently. We capture the entire expression up to the closing
        # paren so we can rebuild a wildcard-template and validate it.
        cls.concat_pattern = re.compile(
            r"lookup\(\s*['\"]config['\"]\s*,\s*([^,]+?)\s*,\s*(.+?)\s*\)"
        )

        # Scan files once
        cls.literal_paths = {}  # app_id -> {path: [(file,line)...]}
        cls.variable_paths = {}  # path -> [(file,line)...]
        # wildcard concat lookups: (app_id, wildcard_path) -> [(file,line)...]
        # `wildcard_path` has every Jinja variable substituted with `*`.
        cls.wildcard_paths = {}

        for path_str, text in iter_project_files_with_content(
            exclude_tests=True,
            exclude_dirs=("docs",),
        ):
            # ignore .py and .sh files (the existing lookup-scan contract)
            if path_str.endswith((".py", ".sh")):
                continue
            file_path = Path(path_str)
            for m in cls.pattern.finditer(text):
                # Determine the start and end of the current line
                start = text.rfind("\n", 0, m.start()) + 1
                end = text.find("\n", start)
                line = text[start:end] if end != -1 else text[start:]

                # 1) Skip lines that are entirely commented out
                if line.lstrip().startswith("#"):
                    continue

                # 2) Skip calls preceded by an inline comment
                idx_call = line.find("lookup")
                idx_hash = line.find("#")
                if 0 <= idx_hash < idx_call:
                    continue
                lineno = text.count("\n", 0, m.start()) + 1
                app_arg = m.group(1).strip()
                path_arg = m.group(2).strip()
                # ignore any templated Jinja2 raw-blocks
                if "{%" in path_arg:
                    continue
                if (app_arg.startswith("'") and app_arg.endswith("'")) or (
                    app_arg.startswith('"') and app_arg.endswith('"')
                ):
                    app_id = app_arg.strip("'\"")
                    # Path strings ending with `.` are partial — they get
                    # concatenated with a Jinja variable via `~` (e.g.
                    # `'services.openldap.ports.local.' ~ _ldap_protocol`).
                    # Validate them via the variable_paths wildcard‐prefix
                    # path instead of attempting an exact lookup.
                    if path_arg.endswith("."):
                        cls.variable_paths.setdefault(path_arg, []).append(
                            (file_path, lineno)
                        )
                    else:
                        cls.literal_paths.setdefault(app_id, {}).setdefault(
                            path_arg, []
                        ).append((file_path, lineno))
                else:
                    cls.variable_paths.setdefault(path_arg, []).append(
                        (file_path, lineno)
                    )

            # Second pass: catch any `~`-concatenated path expression. Every
            # bareword between `~`s is treated as a wildcard so the test does
            # not need special-case knowledge of variable names. The resolved
            # template must match at least one nested path in the role's
            # application defaults; a single `*` accepts any single key at
            # that level.
            for m in cls.concat_pattern.finditer(text):
                start = text.rfind("\n", 0, m.start()) + 1
                end = text.find("\n", start)
                line = text[start:end] if end != -1 else text[start:]
                if line.lstrip().startswith("#"):
                    continue
                idx_call = line.find("lookup")
                idx_hash = line.find("#")
                if 0 <= idx_hash < idx_call:
                    continue
                app_arg = m.group(1).strip()
                expr = m.group(2).strip()
                # Skip pure-literal paths (handled by the first pass).
                if "~" not in expr:
                    continue
                # Skip Jinja statement blocks defensively.
                if "{%" in expr:
                    continue
                wildcard_path = _expr_to_wildcard_path(expr)
                if wildcard_path is None:
                    continue
                lineno = text.count("\n", 0, m.start()) + 1
                # Resolve role: literal app id wins, otherwise infer from
                # the file's roles/<role>/... path. Lookups outside the
                # roles tree with a non-literal app argument are skipped
                # because the role context is ambiguous.
                if (app_arg.startswith("'") and app_arg.endswith("'")) or (
                    app_arg.startswith('"') and app_arg.endswith('"')
                ):
                    role_id = app_arg.strip("'\"")
                else:
                    role_id = _role_id_from_path(file_path)
                if role_id is None:
                    continue
                cls.wildcard_paths.setdefault((role_id, wildcard_path), []).append(
                    (file_path, lineno)
                )

    def assertNested(self, mapping, dotted, context):
        keys = dotted.split(".")
        cur = mapping
        for k in keys:
            assert isinstance(cur, dict), f"{context}: expected dict at {k}"
            assert k in cur, f"{context}: missing '{k}' in '{dotted}'"
            cur = cur[k]

    def test_literal_paths(self):
        # Check each literal path exists or is allowed by schema
        for app_id, paths in self.literal_paths.items():
            with self.subTest(app=app_id):
                self.assertIn(
                    app_id,
                    self.application_defaults,
                    f"App '{app_id}' missing in application defaults",
                )
                for dotted, occs in paths.items():
                    with self.subTest(path=dotted):
                        try:
                            # will raise ConfigEntryNotSetError if defined in schema but not set
                            get(
                                applications=self.application_defaults,
                                application_id=app_id,
                                config_path=dotted,
                                strict=True,
                            )
                        except ConfigEntryNotSetError:
                            # defined in schema but not set: acceptable
                            continue
                        # otherwise, perform static validation
                        self._validate(app_id, dotted, occs)

    def test_wildcard_paths(self):
        """Catch full-path drift in any `~`-concatenated lookup expression.

        The literal-path scanner only sees the first quoted string and
        falls back to wildcard-prefix matching for paths ending in `.`,
        which is too permissive: a wrong suffix like
        `services.<entity>.port` against a meta declaring
        `services.<entity>.ports.inter` slips through. This test
        reconstructs the full path with `*` placeholders for every Jinja
        variable segment and validates the resulting wildcard path
        against the same fallback chain the literal-path test uses
        (application defaults -> users -> credentials in defaults
        -> credentials in schema -> images presence)."""
        if not self.wildcard_paths:
            self.skipTest("No `~`-concatenated lookup paths found")
        for (role_id, wildcard_path), occs in self.wildcard_paths.items():
            with self.subTest(role=role_id, path=wildcard_path):
                cfg = self.application_defaults.get(role_id)
                if cfg is None:
                    # Role has no application defaults entry — handled by
                    # other tests; skip here to keep the failure focused on
                    # path mismatches.
                    continue
                if _match_wildcard_path(cfg, wildcard_path):
                    continue
                # users.<sub> fallback
                if wildcard_path.startswith("users."):
                    sub = wildcard_path.split(".", 1)[1]
                    if _match_wildcard_path(
                        {"_root": self.user_defaults}, "_root." + sub
                    ):
                        continue
                # credentials.<sub> fallback: defaults then schema
                if wildcard_path.startswith("credentials."):
                    sub = wildcard_path.split(".", 1)[1]
                    creds_cfg = cfg.get("credentials")
                    if isinstance(creds_cfg, dict) and _match_wildcard_segment(
                        creds_cfg, sub
                    ):
                        continue
                    schema = self.role_schemas.get(role_id, {})
                    creds = (
                        schema.get("credentials") if isinstance(schema, dict) else None
                    )
                    if isinstance(creds, dict) and _match_wildcard_segment(creds, sub):
                        continue
                # images.<sub> fallback: any role with an images dict suffices
                if wildcard_path.startswith("images.") and isinstance(
                    cfg.get("images"), dict
                ):
                    continue
                file_path, lineno = occs[0]
                self.fail(
                    f"wildcard path '{wildcard_path}' has no match in "
                    f"application defaults / schema for role '{role_id}'; "
                    f"called at {file_path}:{lineno}"
                )

    def test_variable_paths(self):
        # dynamic paths: must exist somewhere
        if not self.variable_paths:
            self.skipTest("No dynamic lookup('config', ...) calls")
        for dotted, occs in self.variable_paths.items():
            with self.subTest(path=dotted):
                found = False
                # schema-defined entries: acceptable if defined in any role schema
                for schema in self.role_schemas.values():
                    if isinstance(schema, dict) and dotted in schema:
                        found = True
                        break
                if found:
                    continue

                # Wildcard‑prefix: if the path ends with '.', treat it as a prefix
                # and check for nested dicts in application defaults
                if dotted.endswith("."):
                    prefix = dotted.rstrip(".")
                    parts = prefix.split(".")
                    for cfg in self.application_defaults.values():
                        cur = cfg
                        ok = True
                        for p in parts:
                            if isinstance(cur, dict) and p in cur:
                                cur = cur[p]
                            else:
                                ok = False
                                break
                        if ok:
                            found = True
                            break
                    if found:
                        continue

                # credentials.*: first inspect application defaults, then schema
                if dotted.startswith("credentials."):
                    key = dotted.split(".", 1)[1]
                    # 1) application_defaults[app_id].credentials
                    for aid, cfg in self.application_defaults.items():
                        creds = cfg.get("credentials", {})
                        if isinstance(creds, dict) and key in creds:
                            found = True
                            break
                    if found:
                        continue
                    # 2) role_schema.credentials
                    for aid, schema in self.role_schemas.items():
                        creds = schema.get("credentials", {})
                        if isinstance(creds, dict) and key in creds:
                            found = True
                            break
                    if found:
                        continue
                # images.*: any images dict
                if dotted.startswith("images."):
                    if any(
                        isinstance(cfg.get("images"), dict)
                        for cfg in self.application_defaults.values()
                    ):
                        continue
                # users.*: user defaults fallback
                if dotted.startswith("users."):
                    subpath = dotted.split(".", 1)[1]
                    try:
                        # this will raise if the nested key doesn’t exist
                        self.assertNested(self.user_defaults, subpath, "user_defaults")
                        continue
                    except AssertionError:
                        # It's expected that subpath may not exist in user defaults; continue.
                        pass
                # application defaults
                for aid, cfg in self.application_defaults.items():
                    try:
                        self.assertNested(cfg, dotted, aid)
                        found = True
                        break
                    except AssertionError:
                        # It's expected that not every config dict will have the required nested keys;
                        # try the next config dict until found.
                        pass
                if not found:
                    file_path, lineno = occs[0]
                    self.fail(
                        f"No entry for '{dotted}'; called at {file_path}:{lineno}"
                    )

    def _validate(self, app_id, dotted, occs):
        # try app defaults
        cfg = self.application_defaults.get(app_id, {})
        try:
            self.assertNested(cfg, dotted, app_id)
            return
        except AssertionError:
            pass
        # users.* fallback
        if dotted.startswith("users."):
            sub = dotted.split(".", 1)[1]
            if sub in self.user_defaults:
                return
        # credentials.* fallback: application defaults, then schema
        if dotted.startswith("credentials."):
            key = dotted.split(".", 1)[1]
            # 1) application_defaults[app_id].credentials
            creds_cfg = cfg.get("credentials", {})
            if isinstance(creds_cfg, dict) and key in creds_cfg:
                return
            # 2) schema
            schema = self.role_schemas.get(app_id, {})
            creds = schema.get("credentials", {})
            self.assertIn(key, creds, f"Credential '{key}' missing for app '{app_id}'")
            return
        # images.* fallback
        if dotted.startswith("images."):
            if isinstance(cfg.get("images"), dict):
                return
        # final fail
        file_path, lineno = occs[0]
        self.fail(
            f"'{dotted}' not found for '{app_id}'; called at {file_path}:{lineno}"
        )


if __name__ == "__main__":
    unittest.main()
