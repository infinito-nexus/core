from __future__ import annotations

import ast
import contextlib
import copy
import datetime as dt
import json
import os
import re
import time
import unittest
import unittest.mock as mock

import jinja2
from ansible.errors import AnsibleFilterError
from ansible.plugins.filter.core import FilterModule as CoreFilters
from ansible.plugins.filter.mathstuff import FilterModule as MathFilters
from ansible.plugins.test.core import TestModule as CoreTests
from jinja2.defaults import DEFAULT_FILTERS
from jinja2.nativetypes import NativeEnvironment

from plugins.filter import knot_delegation as delegation
from tests.utils.knot_keys import (
    FIRST_KSK,
    FRESH_KSK,
    HOSTS,
    HOUR,
    NEW_ZONE_KSK,
    NOW,
    OLD_KSK,
    PARENT,
    ROLLED_KSK,
    SECOND_KSK,
    ZONE,
    ZSK,
    active,
    build,
    cloudflare_zones,
    ds_output,
)
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_str

SEMAPHORE_DIR = PROJECT_ROOT / "roles" / "web-app-semaphore"
FLAVOR_DIR = SEMAPHORE_DIR / "tasks" / "flavors" / "dns"
DELEGATE = FLAVOR_DIR / "knot" / "delegate.yml"
FILTER_ROOTS = (PROJECT_ROOT / "plugins" / "filter", SEMAPHORE_DIR / "filter_plugins")
KNOT_TEXT = read_text(str(FLAVOR_DIR / "knot.yml"))
DELEGATE_TEXT = read_text(str(DELEGATE))
KNOT_FILTERS = frozenset(delegation.FilterModule().filters())
BUILTIN_FILTERS = frozenset(
    {*DEFAULT_FILTERS, *CoreFilters().filters(), *MathFilters().filters()}
)
FILTER_USE = re.compile(r"\|[ \t]*([A-Za-z_]\w*)")
KNOT_TERM = re.compile(r"svc-dns-knot|semaphore_knot_|\bknot_\w+")
PRE_WHEN_KEYS = ("delegate_to", "loop", "run_once", "throttle", "any_errors_fatal")
SECTIONS = ("block", "rescue", "always")
STAGING = "staging.example.org"
STAGING_ZONE = f"ws.{STAGING}"
CO_UK = "example.co.uk"
CO_UK_ZONE = f"ws.{CO_UK}"
KNOT_GUARD = "(groups.get('svc-dns-knot') or []) | length > 0"
GATES = (
    "IS_STACK_HOST | bool",
    "DNS_PROVIDER == 'cloudflare'",
    KNOT_GUARD,
    "run_once_svc_dns_knot) is defined",
)
STACK_HOST = {"IS_STACK_HOST": True, "DNS_PROVIDER": "cloudflare"}
INCLUDE_TASKS = "ansible.builtin.include_tasks"
INCLUDE_ROLE = "ansible.builtin.include_role"
SET_FACT = "ansible.builtin.set_fact"
SUBMIT = "zone-ksk-submitted"
NO_READY_KEY = "error: (no key ready for submission)"


def flavor_tasks():
    return {
        path.stem: load_yaml_str(read_text(str(path)))
        for path in sorted(FLAVOR_DIR.glob("*.yml"))
    }


def delegate_tasks():
    return load_yaml_str(DELEGATE_TEXT)


def delegate_includes(tasks):
    return [
        task
        for task in tasks
        if INCLUDE_TASKS in task
        and task[INCLUDE_TASKS].replace("{{ role_path }}", str(SEMAPHORE_DIR))
        == str(DELEGATE)
    ]


def flavor_findings(flavors):
    """Args:
        flavors: ``{flavor: tasks}`` of ``tasks/flavors/dns/<flavor>.yml``.

    Returns:
        One message per flavor other than ``knot`` that writes the knot
        delegation, one when ``knot`` does not include ``knot/delegate.yml``
        exactly once, and one per gate that include lacks.
    """
    findings = []
    for flavor, tasks in flavors.items():
        includes = delegate_includes(tasks)
        if flavor != "knot" and (includes or "knot_delegation" in json.dumps(tasks)):
            findings.append(f"{flavor}: writes the knot delegation")
        if flavor == "knot" and len(includes) != 1:
            findings.append(f"knot: {len(includes)} delegation includes, expected one")
        for include in includes:
            conditions = " ".join(include.get("when", []))
            findings += [
                f"{flavor}: the include lacks {gate}"
                for gate in GATES
                if gate not in conditions
            ]
    return findings


def walk(tasks):
    for task in tasks:
        yield task
        for section in SECTIONS:
            yield from walk(task.get(section, []))


def ungated_terms(tasks):
    """Args:
        tasks: the tasks of a flavor file.

    Returns:
        ``<task>: <key>`` for every key Ansible templates before the ``when``
        of a task, ``delegate_to``, ``loop`` and ``with_*`` in the task
        executor and ``run_once``, ``throttle`` and ``any_errors_fatal`` in the
        strategy, that names the knot group, a ``semaphore_knot_*`` variable
        or a knot filter. ``vars`` is templated lazily, never before the
        ``when``. Only a file the gated include loads may name them, as
        Ansible loads it after the gate passed.
    """
    return [
        f"{task.get('name')}: {key}"
        for task in walk(tasks)
        for key in task
        if (key in PRE_WHEN_KEYS or key.startswith("with_"))
        and KNOT_TERM.search(json.dumps(task[key]))
    ]


def r4_layout(tasks):
    """Args:
        tasks: the tasks of ``knot.yml``.

    Returns:
        ``knot.yml`` as round 4 laid it out: the tasks of ``knot/delegate.yml``
        inline in a block that carries the gate of the include.
    """
    return [
        {**delegation_step(), "when": task["when"]}
        if delegate_includes([task])
        else task
        for task in tasks
    ]


def defined_filters(source):
    """Args:
        source: the text of a filter plugin.

    Returns:
        The names the dict literals of its ``FilterModule`` map.
    """
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == "FilterModule":
            for item in ast.walk(node):
                if isinstance(item, ast.Dict):
                    names.update(
                        k.value
                        for k in item.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    )
    return names


def semaphore_filters():
    """Returns:
    Every filter that loads wherever ``web-app-semaphore`` runs: those of
    ``plugins/filter/`` and of the role's own ``filter_plugins/``.
    """
    roots = tuple(f"{root}/" for root in FILTER_ROOTS)
    names = set()
    for path in iter_project_files(extensions=(".py",)):
        if path.startswith(roots):
            names |= defined_filters(read_text(path))
    return names


def unresolved_filters(text, defined):
    """Args:
        text: the text of a task file.
        defined: the filters that load beside the Ansible and Jinja ones.

    Returns:
        Every filter the task file uses that none of them defines.
    """
    return sorted(set(FILTER_USE.findall(text)) - BUILTIN_FILTERS - defined)


def ansible_now(*, utc=False):
    """Args:
        utc: whether the step asks for UTC, as ``now(utc=true)`` does.

    Returns:
        ``NOW`` the way Ansible's ``now`` returns it: a naive datetime, in UTC
        with ``utc`` and in the local time of the controller without it.
    """
    moment = dt.datetime.fromtimestamp(NOW, tz=dt.UTC)
    return (moment if utc else moment.astimezone()).replace(tzinfo=None)


@contextlib.contextmanager
def controller_zone(name):
    """Args:
        name: a POSIX ``TZ`` value for the controller, ``EAST-1`` for UTC+1.

    Yields:
        With the local time of the process in that zone.
    """
    try:
        with mock.patch.dict(os.environ, {"TZ": name}):
            time.tzset()
            yield
    finally:
        time.tzset()


def render(expression, context):
    """Args:
        expression: a Jinja expression of the delegation step.
        context: the variables it reads.

    Returns:
        Its native value under the Ansible filters and the knot filters.
    """
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    for module in (CoreFilters(), MathFilters(), delegation.FilterModule()):
        environment.filters.update(module.filters())
    environment.tests.update(CoreTests().tests())
    environment.globals["now"] = ansible_now
    return environment.from_string(expression).render(**context)


def gate_open(conditions, context):
    """Args:
        conditions: the ``when`` list of a task.
        context: the variables it reads.

    Returns:
        Whether every condition holds, evaluated in order and stopped at the
        first false one, as ansible-core evaluates a ``when`` list.
    """
    return all(render("{{ " + c + " }}", context) for c in conditions)


def delegation_step():
    """Returns:
    The delegation as one step: the ``vars`` the include in ``knot.yml``
    hands over and the tasks of ``knot/delegate.yml`` as its ``block``.
    """
    (include,) = delegate_includes(flavor_tasks()["knot"])
    return {"vars": include["vars"], "block": delegate_tasks()}


def step_context(step, keys, zone, zones):
    """Args:
        step: the delegation step, as ``delegation_step`` builds it.
        keys: the keys ``keymgr -j <zone> list`` prints on the primary.
        zone: the subzone of the knot flavor.
        zones: ``(name, status)`` of every Cloudflare zone the token reads.

    Returns:
        The variables its tasks read, rendered task by task as the step sets
        them, with the DS output of every KSK on the primary and the answer
        of the Cloudflare zones API to every name the step asks for.
    """
    context = {
        "groups": {"svc-dns-knot": list(HOSTS)},
        "SEMAPHORE_DNS": {"flavor": "knot", "zone": zone.upper()},
        "hostvars": {h: {"networks": {"internet": v}} for h, v in HOSTS.items()},
        "semaphore_knot_keys": {"stdout": json.dumps(keys)},
        "semaphore_knot_ds": {"stdout": ds_output(f"{zone}.", FIRST_KSK, SECOND_KSK)},
    }
    for name in ("semaphore_knot_hosts", "semaphore_knot_zone"):
        context[name] = render(step["vars"][name], context)
    for task in step["block"]:
        if "uri_retry" in task:
            loop_var = task["loop_control"]["loop_var"]
            context[task["register"]] = {
                "results": [
                    {loop_var: name, "json": {"result": cloudflare_zones(name, zones)}}
                    for name in render(task["loop"], context)
                ]
            }
        for name, value in task.get(SET_FACT, {}).items():
            context[name] = render(value, context)
    return context


def r4_clock(step):
    """Args:
        step: the delegation step, as ``delegation_step`` builds it.

    Returns:
        The block with the clock of round 4, ``now(utc=true).timestamp()``.
    """
    planted = copy.deepcopy(step)
    for task in planted["block"]:
        facts = task.get(SET_FACT, {})
        if "semaphore_knot_ksk" in facts:
            facts["semaphore_knot_ksk"] = facts["semaphore_knot_ksk"].replace(
                "now()", "now(utc=true)"
            )
    return planted


def order_findings(block, context):
    """Args:
        block: the tasks of the delegation step.
        context: the variables they read, ``step_context`` of the step.

    Returns:
        One message per break of the order: a record written past
        ``sys-dns-cloudflare-records``, role runs other than the NS and glue
        and then the DS alone, and a KSK confirmation other than one after
        the DS run.
    """
    findings = []
    if "community.general.cloudflare_dns" in json.dumps(block):
        findings.append("a record bypasses sys-dns-cloudflare-records")
    runs = [
        (index, render(task["vars"]["cloudflare_records"], context))
        for index, task in enumerate(block)
        if INCLUDE_ROLE in task
    ]
    records = context["semaphore_knot_delegation"]
    want = [
        [r for r in records if r["type"] != "DS"],
        [r for r in records if r["type"] == "DS"],
    ]
    if [run for _, run in runs] != want:
        findings.append("the role runs are not the NS and glue, then the DS alone")
    submits = [index for index, task in enumerate(block) if SUBMIT in json.dumps(task)]
    if len(submits) != 1 or len(runs) != 2 or submits[0] < runs[-1][0]:
        findings.append(f"{SUBMIT} does not follow the DS run once")
    return findings


def submission_task(step):
    (task,) = [t for t in step["block"] if SUBMIT in json.dumps(t)]
    return task


def submission_wanted(step, context):
    return render("{{ " + submission_task(step)["when"] + " }}", context)


def knotc(rc, stdout, stderr):
    return {"rc": rc, "stdout": stdout, "stderr": stderr}


def submission_outcome(task, result):
    """Args:
        task: the ``knotc zone-ksk-submitted`` task of the step.
        result: what the task registers.

    Returns:
        ``(failed, changed)`` of the task, a missing ``failed_when`` failing
        on an exit status other than 0 only, as the shell module does.
    """
    context = {task["register"]: result}
    if "failed_when" in task:
        failed = render("{{ " + task["failed_when"] + " }}", context)
    else:
        failed = result["rc"] != 0
    return failed, render("{{ " + task["changed_when"] + " }}", context)


class TestKnotFlavorGate(unittest.TestCase):
    def test_only_the_knot_flavor_includes_the_delegation_behind_its_gates(self):
        flavors = flavor_tasks()
        self.assertEqual(set(flavors), {"knot", "route53", "cloudflare"})
        self.assertEqual(flavor_findings(flavors), [])

    def test_negative_control_the_route53_flavor_yields_no_knot_records(self):
        flavors = flavor_tasks()
        planted = {**flavors, "route53": flavors["route53"] + flavors["knot"]}
        self.assertIn("route53: writes the knot delegation", flavor_findings(planted))

    def test_negative_control_an_ungated_include_is_found(self):
        for gate in GATES:
            with self.subTest(gate=gate):
                planted = flavor_tasks()
                (include,) = delegate_includes(planted["knot"])
                include["when"] = [c for c in include["when"] if gate not in c]
                self.assertIn(
                    f"knot: the include lacks {gate}", flavor_findings(planted)
                )

    def test_no_flavor_templates_the_knot_group_before_the_gate(self):
        findings = {
            flavor: ungated_terms(tasks) for flavor, tasks in flavor_tasks().items()
        }
        self.assertEqual({f: t for f, t in findings.items() if t}, {})

    def test_negative_control_the_r4_inline_block_templates_it_before_the_gate(self):
        findings = ungated_terms(r4_layout(flavor_tasks()["knot"]))
        keys = {finding.rsplit(": ", 1)[1] for finding in findings}
        self.assertEqual(keys, {"delegate_to", "loop"})

    def test_the_gate_closes_without_a_knot_group_and_does_not_raise(self):
        (include,) = delegate_includes(flavor_tasks()["knot"])
        absent = {**STACK_HOST, "groups": {}, "hostvars": {}}
        self.assertFalse(gate_open(include["when"], absent))
        deployed = {
            **STACK_HOST,
            "groups": {"svc-dns-knot": ["knot-primary"]},
            "hostvars": {"knot-primary": {"run_once_svc_dns_knot": True}},
        }
        self.assertTrue(gate_open(include["when"], deployed))

    def test_negative_control_a_dropped_or_late_guard_raises_without_the_group(self):
        (include,) = delegate_includes(flavor_tasks()["knot"])
        others = [c for c in include["when"] if c != KNOT_GUARD]
        self.assertEqual(len(others), len(include["when"]) - 1)
        plants = {"dropped": others, "after the lookup": [*others, KNOT_GUARD]}
        absent = {**STACK_HOST, "groups": {}, "hostvars": {}}
        for case, conditions in plants.items():
            with (
                self.subTest(case=case),
                self.assertRaises(jinja2.UndefinedError),
            ):
                gate_open(conditions, absent)

    def test_every_filter_of_the_knot_flavor_loads_without_svc_dns_knot(self):
        text = KNOT_TEXT + DELEGATE_TEXT
        self.assertLessEqual(KNOT_FILTERS, set(FILTER_USE.findall(text)))
        self.assertEqual(unresolved_filters(text, semaphore_filters()), [])

    def test_negative_control_role_local_knot_filters_do_not_resolve(self):
        r3_layout = semaphore_filters() - KNOT_FILTERS
        self.assertEqual(
            unresolved_filters(KNOT_TEXT + DELEGATE_TEXT, r3_layout),
            sorted(KNOT_FILTERS),
        )


class TestKnotDelegationStep(unittest.TestCase):
    def test_the_step_sends_every_record_through_the_role_ds_last(self):
        step = delegation_step()
        context = step_context(step, [ZSK, NEW_ZONE_KSK], ZONE, active(PARENT))
        self.assertEqual(context["semaphore_knot_delegation"], build(HOSTS))
        self.assertEqual(order_findings(step["block"], context), [])
        for task in step["block"]:
            if INCLUDE_ROLE in task:
                self.assertEqual(
                    task[INCLUDE_ROLE]["name"], "sys-dns-cloudflare-records"
                )

    def test_the_step_writes_into_the_longest_active_zone_above_the_subzone(self):
        step = delegation_step()
        cases = {
            ZONE: (active(PARENT, "example.net"), PARENT),
            STAGING_ZONE: (((STAGING, "pending"), *active(PARENT)), PARENT),
            CO_UK_ZONE: (active(CO_UK), CO_UK),
        }
        for zone, (zones, parent) in cases.items():
            with self.subTest(zone=zone):
                context = step_context(step, [ZSK, NEW_ZONE_KSK], zone, zones)
                self.assertEqual(context["semaphore_knot_parent_zone"], parent)
                self.assertEqual(
                    {r["zone"] for r in context["semaphore_knot_delegation"]},
                    {parent},
                )

    def test_negative_control_a_subzone_without_a_cloudflare_parent_fails(self):
        with self.assertRaisesRegex(AnsibleFilterError, "reads no active zone"):
            step_context(
                delegation_step(), [ZSK, NEW_ZONE_KSK], ZONE, active("other.org")
            )

    def test_negative_control_the_r1_workaround_and_reorders_are_found(self):
        step = delegation_step()
        context = step_context(step, [ZSK, NEW_ZONE_KSK], ZONE, active(PARENT))
        block = step["block"]
        roles = [i for i, t in enumerate(block) if INCLUDE_ROLE in t]
        (submit,) = [i for i, t in enumerate(block) if SUBMIT in json.dumps(t)]
        bypass = {
            "name": "📌 Delegate by NS",
            "community.general.cloudflare_dns": {"type": "NS"},
        }
        swapped = list(block)
        swapped[roles[0]], swapped[roles[1]] = block[roles[1]], block[roles[0]]
        early = [t for i, t in enumerate(block) if i != submit]
        early.insert(roles[1], block[submit])
        plants = {
            "bypass": [*block, bypass],
            "DS before NS": swapped,
            "submission before the DS": early,
        }
        for case, planted in plants.items():
            with self.subTest(case=case):
                self.assertNotEqual(order_findings(planted, context), [])

    def test_a_ready_ksk_is_confirmed_and_an_active_one_is_left_alone(self):
        step = delegation_step()
        cases = {
            "new zone": ([ZSK, NEW_ZONE_KSK], True),
            "rollover": ([ZSK, OLD_KSK, ROLLED_KSK], True),
            "steady": ([ZSK, OLD_KSK], False),
        }
        for case, (keys, wanted) in cases.items():
            with self.subTest(case=case):
                context = step_context(step, keys, ZONE, active(PARENT))
                self.assertIs(submission_wanted(step, context), wanted)

    def test_the_ksk_clock_is_the_epoch_wherever_the_controller_runs(self):
        step = delegation_step()
        early = {**ROLLED_KSK, "ready": NOW + HOUR}
        cases = {
            "fresh KSK": ([ZSK, FRESH_KSK], FIRST_KSK),
            "KSK ready in an hour": ([ZSK, OLD_KSK, early], FIRST_KSK),
        }
        for zone in ("UTC0", "EAST-1", "WEST+5"):
            for case, (keys, tag) in cases.items():
                with self.subTest(zone=zone, case=case), controller_zone(zone):
                    context = step_context(step, keys, ZONE, active(PARENT))
                    self.assertEqual(context["semaphore_knot_ksk"]["tag"], tag)

    def test_negative_control_the_r4_utc_clock_shifts_by_the_offset(self):
        planted = r4_clock(delegation_step())
        self.assertNotEqual(planted, delegation_step())
        with (
            controller_zone("EAST-1"),
            self.assertRaisesRegex(AnsibleFilterError, "no ready, unretired KSK"),
        ):
            step_context(planted, [ZSK, FRESH_KSK], ZONE, active(PARENT))
        early = {**ROLLED_KSK, "ready": NOW + HOUR}
        with controller_zone("WEST+5"):
            context = step_context(planted, [ZSK, OLD_KSK, early], ZONE, active(PARENT))
        self.assertEqual(context["semaphore_knot_ksk"]["tag"], SECOND_KSK)

    def test_the_confirmation_fails_on_every_knotc_error_but_no_ready_key(self):
        task = submission_task(delegation_step())
        cases = {
            "confirmed": (knotc(0, "OK", ""), (False, True)),
            "no ready key": (knotc(1, "", NO_READY_KEY), (False, False)),
            "error": (knotc(1, "", "error: (operation not permitted)"), (True, False)),
            "error, status 0": (knotc(0, "error: (not exists)", ""), (True, False)),
        }
        for case, (result, outcome) in cases.items():
            with self.subTest(case=case):
                self.assertEqual(submission_outcome(task, result), outcome)

    def test_negative_control_without_the_check_an_error_with_status_0_passes(self):
        task = dict(submission_task(delegation_step()))
        del task["failed_when"]
        result = knotc(0, "error: (not exists)", "")
        self.assertEqual(submission_outcome(task, result), (False, False))


if __name__ == "__main__":
    unittest.main()
