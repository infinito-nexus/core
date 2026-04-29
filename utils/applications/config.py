import os
import re
from utils.cache.yaml import load_yaml_any
from ansible.errors import AnsibleFilterError
from collections.abc import Mapping

from ansible.errors import AnsibleUndefinedVariable

try:
    from ansible.utils.unsafe_proxy import AnsibleUndefined
except ImportError:

    class AnsibleUndefined:
        pass


class AppConfigKeyError(AnsibleFilterError, ValueError):
    """
    Raised when a required application config key is missing (strict mode).
    Compatible with Ansible error handling and Python ValueError.
    """

    pass


class ConfigEntryNotSetError(AppConfigKeyError):
    """
    Raised when a config entry is defined in schema but not set in application.
    """

    pass


def get(
    applications,
    application_id,
    config_path,
    strict=True,
    default=None,
    skip_missing_app=False,
):
    # Path to the schema file for this application
    schema_path = os.path.join("roles", application_id, "meta", "schema.yml")

    def schema_defines(path):
        if not os.path.isfile(schema_path):
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
        # Match either 'key' or 'key[index]'
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
                return default if default is not None else False
            raise AppConfigKeyError(
                f"Key '{k}' is undefined at '{'.'.join(path_trace)}'\n"
                f"  actual type: {type(obj).__name__}\n"
                f"  repr(obj): {obj!r}\n"
                f"  repr(applications): {applications!r}\n"
                f"application_id: {application_id}\n"
                f"config_path: {config_path}"
            )

        # Access dict key
        if isinstance(obj, Mapping):
            if k not in obj:
                # Non-strict mode: always return default on missing key
                if not strict:
                    return default if default is not None else False
                # Schema-defined but unset: strict raises ConfigEntryNotSetError
                trace_path = ".".join(path_trace[1:])
                if schema_defines(trace_path):
                    raise ConfigEntryNotSetError(
                        f"Config entry '{trace_path}' is defined in schema at '{schema_path}' but not set in application '{application_id}'."
                    )
                # Generic missing-key error
                raise AppConfigKeyError(
                    f"Key '{k}' not found in dict at '{key}'\n"
                    f"Full path so far: {'.'.join(path_trace)}\n"
                    f"Current object: {repr(obj)}\n"
                    f"application_id: {application_id}\n"
                    f"config_path: {config_path}"
                )
            obj = obj[k]
        else:
            if not strict:
                return default if default is not None else False
            raise AppConfigKeyError(
                f"Expected dict for '{k}', got {type(obj).__name__} at '{key}'\n"
                f"Full path so far: {'.'.join(path_trace)}\n"
                f"Current object: {repr(obj)}\n"
                f"application_id: {application_id}\n"
                f"config_path: {config_path}"
            )

        # If index was provided, access list element
        if idx is not None:
            if not isinstance(obj, list):
                if not strict:
                    return default if default is not None else False
                raise AppConfigKeyError(
                    f"Expected list for '{k}[{idx}]', got {type(obj).__name__}\n"
                    f"Full path so far: {'.'.join(path_trace)}\n"
                    f"Current object: {repr(obj)}\n"
                    f"application_id: {application_id}\n"
                    f"config_path: {config_path}"
                )
            i = int(idx)
            if i >= len(obj):
                if not strict:
                    return default if default is not None else False
                raise AppConfigKeyError(
                    f"Index {i} out of range for list at '{k}'\n"
                    f"Full path so far: {'.'.join(path_trace)}\n"
                    f"Current object: {repr(obj)}\n"
                    f"application_id: {application_id}\n"
                    f"config_path: {config_path}"
                )
            obj = obj[i]
        return obj

    # Begin traversal
    path_trace = [f"applications[{repr(application_id)}]"]
    try:
        obj = applications[application_id]
    except KeyError:
        if skip_missing_app:
            # Simply return default instead of failing
            return default if default is not None else False
        raise AppConfigKeyError(
            f"Application ID '{application_id}' not found in applications dict.\n"
            f"path_trace: {path_trace}\n"
            f"applications keys: {list(applications.keys())}\n"
            f"config_path: {config_path}"
        )

    for part in config_path.split("."):
        path_trace.append(part)
        obj = access(obj, part, path_trace)
        if obj is False and not strict:
            return default if default is not None else False
    return obj
