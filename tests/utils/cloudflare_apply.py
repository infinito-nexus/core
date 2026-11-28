from __future__ import annotations

import copy

import jinja2
from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str

ROLE = PROJECT_ROOT / "roles" / "sys-dns-cloudflare-records"
MODULE = "community.general.cloudflare_dns"
UNRENDERED = ("api_token", "timeout")
OMIT = "__omit__"
ALIASES = {"content": "value", "name": "record", "domain": "zone"}
SOLO = "{{ item.solo | default(false) }}"
STATES = ("present", "absent")
TYPES = (
    "A",
    "AAAA",
    "CNAME",
    "DS",
    "MX",
    "NS",
    "SRV",
    "SSHFP",
    "TLSA",
    "CAA",
    "TXT",
    "PTR",
)
NON_EMPTY = ("A", "AAAA", "CNAME", "TXT", "MX", "NS", "PTR")
DS_SET = ("key_tag", "algorithm", "hash_type")
SOLO_ABSENT = "solo=true can only be used with state=present"


def role_tasks(name):
    return load_yaml_str(read_text(str(ROLE / "tasks" / name)))


def _render(expression, variables):
    """Args:
        expression: one templated value of ``tasks/apply.yml``.
        variables: the variables it reads.

    Returns:
        Its native value under the Ansible core filters.
    """
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters.update(
        {
            name: function
            for name, function in CoreFilters().filters().items()
            if name not in environment.filters
        }
    )
    return environment.from_string(str(expression)).render(**variables)


def applying_tasks(tasks, records):
    """Args:
        tasks: the tasks of ``tasks/apply.yml``.
        records: the pending ``cloudflare_records`` entries.

    Returns:
        ``[(record, task name, module arguments)]`` for every record each
        ``cloudflare_dns`` task loops over, its arguments rendered for it.
    """
    applied = []
    for task in tasks:
        if MODULE not in task:
            continue
        for item in _render(task["loop"], {"_cf_pending": records}):
            arguments = {
                name: _render(value, {"item": item, "omit": OMIT})
                for name, value in task[MODULE].items()
                if name not in UNRENDERED
            }
            applied.append((item, task["name"], arguments))
    return applied


def module_rejections(arguments):
    """Args:
        arguments: the arguments of one ``cloudflare_dns`` call, an omitted one
            as ``__omit__``.

    Returns:
        Every message the argument checks of ``community.general.cloudflare_dns``
        14.0.1 fail the call with before it reaches the API: the choices, the
        DS all-or-none rule, ``DS records only apply to subdomains``, the
        solo sanity check and the non-empty value of a present record.
    """
    given = {
        ALIASES.get(name, name): value
        for name, value in arguments.items()
        if value != OMIT
    }
    blank = given.get("value") is None or given["value"] == ""
    state = given["state"]
    rtype = given["type"]
    rejections = []
    if state not in STATES:
        rejections.append(f"state {state!r} is no choice")
    if rtype not in TYPES:
        rejections.append(f"type {rtype!r} is no choice")
    if given.get("hash_type") not in (None, 1, 2):
        rejections.append(f"hash_type {given['hash_type']!r} is no choice")
    if rtype == "DS":
        fields = [given.get(field) for field in DS_SET]
        if not (None not in fields and not blank) and not (
            fields == [None] * len(DS_SET) and blank
        ):
            rejections.append(
                "For DS records the params key_tag, algorithm, hash_type and "
                "value all need to be defined, or not at all."
            )
        record = str(given["record"])
        zone = str(given["zone"])
        if (record if record.endswith(zone) else f"{record}.{zone}") == zone:
            rejections.append("DS records only apply to subdomains.")
    if given.get("solo") is True and state == "absent":
        rejections.append(SOLO_ABSENT)
    if state == "present" and rtype in NON_EMPTY and blank:
        rejections.append(
            "You must provide a non-empty value to create this record type"
        )
    return rejections


def solo_for_every_state():
    """Returns:
    ``tasks/apply.yml`` as it stood before the solo guard: every task passes
    ``solo`` on, whatever the state of the record.
    """
    tasks = copy.deepcopy(role_tasks("apply.yml"))
    for task in tasks:
        if MODULE in task:
            task[MODULE]["solo"] = SOLO
    return tasks
