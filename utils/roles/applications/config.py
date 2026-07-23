import re
from collections.abc import Mapping
from pathlib import Path

from ansible.errors import AnsibleFilterError, AnsibleUndefinedVariable
from ansible.template import AnsibleUndefined

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SCHEMA


class AppConfigKeyError(AnsibleFilterError, ValueError):
    """
    Raised when a required application config key is missing (strict mode).
    Compatible with Ansible error handling and Python ValueError.
    """


class ConfigEntryNotSetError(AppConfigKeyError):
    """
    Raised when a config entry is defined in schema but not set in application.
    """


# Exception: the sentinel must not be False - genuine False leaves would be coerced to the default.
_MISSING = object()


def get(
    applications,
    application_id,
    config_path,
    strict=True,
    default=None,
    skip_missing_app=False,
):
    schema_path = str(Path("roles") / application_id / ROLE_FILE_META_SCHEMA)

    def schema_defines(path):
        if not Path(schema_path).is_file():
            return False
        schema = load_yaml_any(schema_path, default_if_missing={}) or {}
        node = schema
        for part in path.split("."):
            key_match = re.match(r"^([a-zA-Z0-9_-]+)", part)
            if not key_match:
                return False
            k = key_match.group(1)
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return False
        return True

    def access(obj, key, path_trace):
        m = re.match(r"^([a-zA-Z0-9_-]+)(?:\[(\d+)\])?$", key)
        if not m:
            raise AppConfigKeyError(
                f"Invalid key format in config_path: '{key}'\n"
                f"Full path so far: {'.'.join(path_trace)}\n"
                f"application_id: {application_id}\n"
                f"config_path: {config_path}"
            )
        k, idx = m.group(1), m.group(2)

        if isinstance(obj, (AnsibleUndefined, AnsibleUndefinedVariable)):
            if not strict:
                return _MISSING
            raise AppConfigKeyError(
                f"Key '{k}' is undefined at '{'.'.join(path_trace)}'\n"
                f"  actual type: {type(obj).__name__}\n"
                f"  repr(obj): {obj!r}\n"
                f"  repr(applications): {applications!r}\n"
                f"application_id: {application_id}\n"
                f"config_path: {config_path}"
            )

        if isinstance(obj, Mapping):
            if k not in obj:
                if not strict:
                    return _MISSING
                trace_path = ".".join(path_trace[1:])
                if schema_defines(trace_path):
                    raise ConfigEntryNotSetError(
                        f"Config entry '{trace_path}' is defined in schema at '{schema_path}' but not set in application '{application_id}'. "
                        f"Present keys at this level: {sorted(obj.keys()) if isinstance(obj, Mapping) else type(obj).__name__}."
                    )
                raise AppConfigKeyError(
                    f"Key '{k}' not found in dict at '{key}'\n"
                    f"Full path so far: {'.'.join(path_trace)}\n"
                    f"Current object: {obj!r}\n"
                    f"application_id: {application_id}\n"
                    f"config_path: {config_path}"
                )
            obj = obj[k]
        else:
            if not strict:
                return _MISSING
            raise AppConfigKeyError(
                f"Expected dict for '{k}', got {type(obj).__name__} at '{key}'\n"
                f"Full path so far: {'.'.join(path_trace)}\n"
                f"Current object: {obj!r}\n"
                f"application_id: {application_id}\n"
                f"config_path: {config_path}"
            )

        if idx is not None:
            if not isinstance(obj, list):
                if not strict:
                    return _MISSING
                raise AppConfigKeyError(
                    f"Expected list for '{k}[{idx}]', got {type(obj).__name__}\n"
                    f"Full path so far: {'.'.join(path_trace)}\n"
                    f"Current object: {obj!r}\n"
                    f"application_id: {application_id}\n"
                    f"config_path: {config_path}"
                )
            i = int(idx)
            if i >= len(obj):
                if not strict:
                    return _MISSING
                raise AppConfigKeyError(
                    f"Index {i} out of range for list at '{k}'\n"
                    f"Full path so far: {'.'.join(path_trace)}\n"
                    f"Current object: {obj!r}\n"
                    f"application_id: {application_id}\n"
                    f"config_path: {config_path}"
                )
            obj = obj[i]
        return obj

    path_trace = [f"applications[{application_id!r}]"]
    try:
        obj = applications[application_id]
    except KeyError:
        if skip_missing_app:
            return default if default is not None else False
        raise AppConfigKeyError(
            f"Application ID '{application_id}' not found in applications dict.\n"
            f"path_trace: {path_trace}\n"
            f"applications keys: {list(applications.keys())}\n"
            f"config_path: {config_path}"
        ) from None

    for part in config_path.split("."):
        path_trace.append(part)
        obj = access(obj, part, path_trace)
        if obj is _MISSING:
            return default if default is not None else False
    return obj
