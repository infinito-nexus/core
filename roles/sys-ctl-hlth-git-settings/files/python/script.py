#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

from git.core import UNSUPPORTED, CheckError, emit, provider, read_token

USER_AGENT = "infinito-git-settings"
ABSENT = "absent"
MAX_VALUE = 300
CHECK_NAMES = {
    "open_secret_scanning_alerts": "secret_scanning",
    "open_dependabot_alerts": "dependabot",
}
EXTRA_FIELDS = ("collaborators", "deploy_keys", "pull_request_target")


def text(value):
    if value is None:
        return ABSENT
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)[:MAX_VALUE]


def drift(scope, check, expected, actual, extra=False):
    """Return one drift event per field whose actual value differs from the expected one.

    Args:
        scope: ``org`` or ``org/repo`` the fields belong to.
        check: the check's name.
        expected: field to expected value.
        actual: field to actual value; a missing field is ``absent``.
        extra: also report fields that are only in ``actual``.
    """
    fields = sorted(set(expected) | (set(actual) if extra else set()))
    events = []
    for field in fields:
        want, have = text(expected.get(field)), text(actual.get(field))
        if want != have:
            events.append(
                {
                    "gs_kind": "drift",
                    "gs_scope": scope,
                    "gs_check": check,
                    "gs_field": str(field),
                    "gs_expected": want,
                    "gs_actual": have,
                }
            )
    return events


def error(scope, check, reason):
    return {
        "gs_kind": "error",
        "gs_scope": scope,
        "gs_check": check,
        "gs_reason": str(reason)[:MAX_VALUE],
    }


def unsupported(adapter, scope, check, field):
    return {
        "gs_kind": "unsupported",
        "gs_provider": adapter.NAME,
        "gs_scope": scope,
        "gs_check": check,
        "gs_field": field,
    }


def fields(key, value):
    """Return an expected-file value as the field to value mapping drift compares.

    Args:
        key: the expected-file key.
        value: its expected or current value.
    """
    if key == "deploy_keys":
        return {
            str(
                item["id"]
            ): f"{item['title']} ({'read-only' if item['read_only'] else 'read-write'})"
            for item in value
        }
    if key == "pull_request_target":
        return dict.fromkeys(value, "present")
    if key in CHECK_NAMES:
        return {"open_alerts": value}
    return value


def check_org(api, adapter, org, expected):
    return drift(
        org,
        "owners",
        dict.fromkeys(expected["owners"], "owner"),
        dict.fromkeys(adapter.owners(api, org), "owner"),
        extra=True,
    )


def check_repo(api, adapter, scope, expected, branch):
    events = []
    for key, collect in adapter.collectors(api, scope, branch).items():
        check = CHECK_NAMES.get(key, key)
        if collect is UNSUPPORTED:
            events.append(unsupported(adapter, scope, check, "*"))
            continue
        try:
            current = collect()
        except CheckError as failure:
            events.append(error(scope, check, failure))
            continue
        want, have = fields(key, expected[key]), fields(key, current)
        if isinstance(have, dict):
            for field in sorted(
                name for name, value in have.items() if value is UNSUPPORTED
            ):
                events.append(unsupported(adapter, scope, check, field))
                want = {name: value for name, value in want.items() if name != field}
                have = {name: value for name, value in have.items() if name != field}
        events += drift(scope, check, want, have, extra=key in EXTRA_FIELDS)
    return events


def run(api, adapter, expected):
    """Return every drift, failure and unsupported event of one check run, then the run summary.

    Args:
        api: the provider's API client.
        adapter: the provider's adapter module.
        expected: the parsed expected state.
    """
    org = expected["organization"]
    events = []
    if not api.token:
        events.append(error(org, "token", "the token file is empty"))
    else:
        try:
            events += check_org(api, adapter, org, expected)
        except CheckError as failure:
            events.append(error(org, "owners", failure))
        for name, repo_expected in sorted(expected["repositories"].items()):
            scope = f"{org}/{name}"
            try:
                branch = adapter.default_branch(api, scope)
            except CheckError as failure:
                events.append(error(scope, "repository", failure))
                continue
            events += check_repo(api, adapter, scope, repo_expected, branch)
    count = {
        kind: sum(event["gs_kind"] == kind for event in events)
        for kind in ("drift", "error", "unsupported")
    }
    events.append(
        {
            "gs_kind": "run",
            "gs_provider": adapter.NAME,
            "gs_scope": org,
            "gs_drift": str(count["drift"]),
            "gs_errors": str(count["error"]),
            "gs_unsupported": str(count["unsupported"]),
        }
    )
    return events


def current_state(api, adapter, expected):
    """Return the current settings in the expected file's format, for the organization and repositories it lists.

    Args:
        api: the provider's API client.
        adapter: the provider's adapter module.
        expected: the parsed expected state; only its organization and repository names are read.

    Raises:
        CheckError: any value could not be read, naming every failed check, so no partial state is printed.
    """
    org = expected["organization"]
    if not api.token:
        raise CheckError("token: the token file is empty")
    failures = []
    state = {"organization": org, "owners": [], "repositories": {}}
    try:
        state["owners"] = adapter.owners(api, org)
    except CheckError as failure:
        failures.append(f"{org} owners: {failure}")
    for name in sorted(expected["repositories"]):
        scope = f"{org}/{name}"
        try:
            branch = adapter.default_branch(api, scope)
        except CheckError as failure:
            failures.append(f"{scope} repository: {failure}")
            continue
        repo = state["repositories"][name] = {}
        for key, collect in adapter.collectors(api, scope, branch).items():
            if collect is UNSUPPORTED:
                continue
            try:
                value = collect()
            except CheckError as failure:
                failures.append(f"{scope} {key}: {failure}")
                continue
            repo[key] = (
                {
                    field: item
                    for field, item in value.items()
                    if item is not UNSUPPORTED
                }
                if isinstance(value, dict)
                else value
            )
    if failures:
        raise CheckError("; ".join(failures))
    return state


YAML_PLAIN = re.compile(r"^[A-Za-z_./][A-Za-z0-9_./-]*$")
YAML_WORDS = {
    "true",
    "false",
    "null",
    "yes",
    "no",
    "on",
    "off",
    "y",
    "n",
    ".inf",
    ".nan",
}


def yaml_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if value == {}:
        return "{}"
    if value == []:
        return "[]"
    value = str(value)
    return (
        value
        if YAML_PLAIN.match(value) and value.lower() not in YAML_WORDS
        else json.dumps(value)
    )


def to_yaml(value, indent=0):
    """Return the lines of a block-style YAML rendering of nested dicts, lists and scalars.

    Args:
        value: a dict or list.
        indent: the nesting level, two spaces each.
    """
    pad = "  " * indent
    lines = []
    for key, item in value.items() if isinstance(value, dict) else enumerate(value):
        nested = isinstance(item, (dict, list)) and item
        if isinstance(value, dict):
            lines.append(
                f"{pad}{yaml_scalar(key)}:"
                + ("" if nested else f" {yaml_scalar(item)}")
            )
            lines += to_yaml(item, indent + 1) if nested else []
        elif isinstance(item, dict) and item:
            first, *rest = to_yaml(item, indent + 1)
            lines += [f"{pad}- {first.strip()}", *rest]
        else:
            lines.append(f"{pad}- {yaml_scalar(item)}")
    return lines


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare a git provider's organization and repository settings with their expected state."
    )
    parser.add_argument(
        "--provider", required=True, help="the git provider: github, gitea or gitlab"
    )
    parser.add_argument("--api-url", required=True, help="the provider's API base URL")
    parser.add_argument(
        "--token-file", required=True, help="file holding the read-only token"
    )
    parser.add_argument(
        "--expected",
        required=True,
        help="the expected state as JSON; --print-current reads only its organization and repository names",
    )
    parser.add_argument(
        "--tag",
        help="journald tag every event is logged under; required unless --print-current",
    )
    parser.add_argument(
        "--timeout", required=True, type=int, help="seconds per API request"
    )
    parser.add_argument(
        "--print-current",
        action="store_true",
        help="print the current settings as expected-file YAML instead of checking",
    )
    args = parser.parse_args(argv)
    if not args.print_current and not args.tag:
        parser.error("--tag is required unless --print-current is set")
    return args


def main():
    args = parse_args()
    adapter = provider(args.provider)
    api = adapter.client(
        args.api_url, read_token(args.token_file), args.timeout, USER_AGENT
    )
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    if args.print_current:
        try:
            state = current_state(api, adapter, expected)
        except CheckError as failure:
            raise SystemExit(
                f"cannot read the current {args.provider} settings: {failure}"
            ) from failure
        print("\n".join(["---", *to_yaml(state)]))
        return
    emit(args.tag, run(api, adapter, expected), "gs_kind")


if __name__ == "__main__":
    main()
