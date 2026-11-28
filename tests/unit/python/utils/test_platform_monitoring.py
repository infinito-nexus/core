from __future__ import annotations

import ast
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from ansible.errors import AnsibleFilterError
from jinja2 import Environment, StrictUndefined, select_autoescape

import plugins.filter.platform.monitoring as platform_filters
import utils.monitoring.addresses as addresses
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.openbao_client import OpenBaoError
from utils.platform_monitoring import (
    AGENT_KEY_PATTERN,
    EXTERNAL_VECTORS,
    FEDERATE_MATCHES,
    FEDERATED,
    GLOBAL_EXCEPTIONS,
    INTERNAL_NETWORKS,
    INTERNAL_VECTORS,
    KINDS,
    ROLE,
    VARIABLE,
    agent_key_line,
    agent_key_reference,
    canonical_host,
    checkmk_host_name,
    configuration_base,
    digest_entry,
    digest_path,
    digest_reference,
    federate_matches,
    federation_domain,
    host_segment,
    internal_address,
    main,
    refusals,
    share,
    stack_host,
)
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

FilterModule = platform_filters.FilterModule
platform_monitoring_agent_key_line = platform_filters.platform_monitoring_agent_key_line
platform_monitoring_share = platform_filters.platform_monitoring_share


def load_helper(path, name):
    """Args:
    path: a script of a role.
    name: the module name it loads under.

    Returns:
        The loaded module.
    """
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROMETHEUS_CONFIG = (
    PROJECT_ROOT / "roles/web-app-prometheus/templates/configuration/prometheus.yml.j2"
)
SEMAPHORE_PYTHON = PROJECT_ROOT / "roles" / "web-app-semaphore" / "files" / "python"
MONITORING = SEMAPHORE_PYTHON / "monitoring.py"
MONITORING_OPENBAO = SEMAPHORE_PYTHON / "monitoring" / "openbao.py"
MONITORING_SURVEY = SEMAPHORE_PYTHON / "monitoring" / "survey.py"
RELEASE_HOST = SEMAPHORE_PYTHON / "release" / "host.py"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
ROLE_VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
CORE_TASKS = ROLE_DIR / "tasks" / "00_core.yml"
AGENT_STATE = ROLE_DIR / "tasks" / "01_agent_state.yml"
AGENT_TASKS = ROLE_DIR / "tasks" / "02_agent.yml"
ABSENT_TASKS = ROLE_DIR / "tasks" / "03_agent_absent.yml"
FEDERATION_TASKS = ROLE_DIR / "tasks" / "04_federation.yml"
DIGEST_LINE = ROLE_DIR / "files" / "python" / "digest_line.py"
AGENT_SCRIPT = b"#!/bin/sh\necho '<<<check_mk>>>'\n"
ALL_ON = dict.fromkeys(KINDS, True)
WORKSPACE = "0a1b2c3d-0000-4000-8000-00000000abcd"


def conditions(task):
    """Args:
    task: one task as Ansible reads it.

    Returns:
        Its ``when`` conditions as a list.
    """
    found = task.get("when") or []
    return found if isinstance(found, list) else [found]


def leaves(tasks, outer=()):
    """Args:
    tasks: a task list as Ansible reads it.
    outer: the ``when`` conditions of the blocks around ``tasks``.

    Returns:
        ``(task, conditions)`` of every task below ``tasks`` that is no
        block, with the conditions of its blocks before its own.
    """
    found = []
    for task in tasks:
        guards = (*outer, *conditions(task))
        if "block" in task:
            found += leaves(task["block"], guards)
        else:
            found.append((task, guards))
    return found


class ShareSchemaTests(unittest.TestCase):
    def test_an_absent_value_shares_every_kind(self):
        self.assertEqual(share(None), ALL_ON)
        self.assertEqual(refusals(None, VARIABLE), [])

    def test_an_absent_key_shares_its_kind(self):
        self.assertEqual(share({}), ALL_ON)
        self.assertEqual(share({"traffic": False}), {**ALL_ON, "traffic": False})

    def test_every_kind_switches_off_alone(self):
        for kind in KINDS:
            with self.subTest(kind):
                shared = share({kind: False})
                self.assertFalse(shared[kind])
                self.assertTrue(all(shared[other] for other in KINDS if other != kind))

    def test_an_unknown_key_is_refused(self):
        self.assertEqual(
            refusals({"agent": True, "logs": True}, VARIABLE),
            ["platform_monitoring.logs is no share kind"],
        )
        with self.assertRaises(ValueError):
            share({"logs": False})

    def test_a_kind_that_is_no_boolean_is_refused(self):
        for value in ("false", 0, 1, None, [], "yes"):
            with self.subTest(value=value):
                self.assertEqual(
                    refusals({"agent": value}, VARIABLE),
                    ["platform_monitoring.agent is no boolean"],
                )

    def test_a_value_that_is_no_mapping_is_refused(self):
        for value in (False, "all", ["agent"]):
            with self.subTest(value=value):
                self.assertEqual(len(refusals(value, "here")), 1)
                self.assertTrue(
                    refusals(value, "here")[0].startswith("here is no mapping")
                )


class FederateMatchTests(unittest.TestCase):
    def test_all_on_answers_every_federated_kind(self):
        self.assertEqual(
            federate_matches(ALL_ON),
            [selector for kind in FEDERATED for selector in FEDERATE_MATCHES[kind]],
        )

    def test_all_three_off_answers_nothing(self):
        self.assertEqual(
            federate_matches({**ALL_ON, **dict.fromkeys(FEDERATED, False)}), []
        )

    def test_a_kind_switched_off_drops_its_selectors_only(self):
        for kind in FEDERATED:
            with self.subTest(kind):
                selectors = federate_matches({**ALL_ON, kind: False})
                for other in FEDERATED:
                    for selector in FEDERATE_MATCHES[other]:
                        if other == kind:
                            self.assertNotIn(selector, selectors)
                        else:
                            self.assertIn(selector, selectors)

    def test_reachability_and_agent_add_no_series(self):
        self.assertEqual(
            federate_matches({**ALL_ON, "reachability": False, "agent": False}),
            federate_matches(ALL_ON),
        )

    def test_health_series_never_ride_on_system_or_traffic(self):
        for kind in ("system", "traffic"):
            for selector in FEDERATE_MATCHES[kind]:
                with self.subTest(selector):
                    self.assertIn(
                        '__name__!~"infinito_hlth_.+|nginx_stack_up"', selector
                    )

    def test_every_job_a_selector_names_is_scraped_by_the_instance(self):
        jobs = set(
            re.findall(r'job_name: "([^"]+)"', read_text(str(PROMETHEUS_CONFIG)))
        )
        named = {
            job
            for selectors in FEDERATE_MATCHES.values()
            for selector in selectors
            for job in re.findall(r'job="([^"]+)"', selector)
        }
        self.assertTrue(named)
        self.assertLessEqual(named, jobs)

    def test_the_digest_reference_is_the_path_the_monitoring_template_writes(self):
        workspace = "0a1b2c3d-0000-4000-8000-00000000abcd"
        reference = digest_reference(workspace, "target")
        monitoring = read_text(str(MONITORING_OPENBAO))
        mount = re.search(r'^DIGEST_MOUNT = "([^"]+)"$', monitoring, re.MULTILINE)[1]
        path = re.search(r'^DIGEST_PATH = "([^"]+)"$', monitoring, re.MULTILINE)[1]
        field = re.search(r'^DIGEST_FIELD = "([^"]+)"$', monitoring, re.MULTILINE)[1]
        written = path.format(alias=f"ws-{workspace}", host="target")
        self.assertEqual(reference, {"openbao": f"{mount}/{written}#{field}"})

    def test_the_agent_key_reference_is_the_path_the_monitoring_template_mirrors(self):
        workspace = "0a1b2c3d-0000-4000-8000-00000000abcd"
        monitoring = read_text(str(MONITORING_OPENBAO))
        mount = re.search(r'^DIGEST_MOUNT = "([^"]+)"$', monitoring, re.MULTILINE)[1]
        path = re.search(r'^AGENT_KEY_PATH = "([^"]+)"$', monitoring, re.MULTILINE)[1]
        field = re.search(r'^AGENT_KEY_FIELD = "([^"]+)"$', monitoring, re.MULTILINE)[1]
        written = path.format(alias=f"ws-{workspace}", host="2001_db8__1")
        self.assertEqual(
            agent_key_reference(workspace, "2001:db8::1"),
            {"openbao": f"{mount}/{written}#{field}"},
        )

    def test_the_digest_sits_in_the_nginx_configuration_base(self):
        self.assertEqual(
            digest_path("/etc/nginx/conf.d/"), "/etc/nginx/conf.d/federate.sha256"
        )

    def test_the_configuration_base_follows_the_openresty_volume(self):
        self.assertEqual(configuration_base(PROJECT_ROOT), "/etc/nginx/conf.d/")


class AgentKeyTests(unittest.TestCase):
    KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyMaterial0123456789abcdefgh"

    def test_the_line_runs_the_agent_only_from_the_checkmk_address(self):
        line = agent_key_line(f"{self.KEY} platform@checkmk", "192.0.2.7", WORKSPACE)
        self.assertEqual(
            line,
            f"command=\"echo '<<<infinito_workspace>>>'; echo ws-{WORKSPACE}; "
            f'exec check_mk_agent",restrict,from="192.0.2.7" {self.KEY} '
            "infinito-platform-monitoring",
        )
        self.assertRegex(line, AGENT_KEY_PATTERN)

    def test_the_forced_command_names_its_workspace_before_the_agent(self):
        line = agent_key_line(self.KEY, "192.0.2.7", WORKSPACE)
        forced = re.match(r'command="([^"]*)"', line).group(1)
        printed = subprocess.run(
            ["/bin/sh", "-c", forced.replace("exec check_mk_agent", "echo AGENT")],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
        self.assertEqual(printed, f"<<<infinito_workspace>>>\nws-{WORKSPACE}\nAGENT\n")

    def test_a_line_written_before_the_binding_is_still_ours(self):
        legacy = (
            f'command="check_mk_agent",restrict,from="192.0.2.7" {self.KEY} '
            "infinito-platform-monitoring"
        )
        self.assertRegex(legacy, AGENT_KEY_PATTERN)
        self.assertNotRegex(
            legacy.replace("check_mk_agent", "sh -c id; check_mk_agent"),
            AGENT_KEY_PATTERN,
        )

    def test_an_ipv6_address_is_accepted(self):
        self.assertIn(
            'from="2001:db8::7"', agent_key_line(self.KEY, "2001:db8::7", WORKSPACE)
        )

    def test_options_cannot_be_smuggled_in(self):
        for key, address, workspace in (
            (f'command="sh" {self.KEY}', "192.0.2.7", WORKSPACE),
            (f"{self.KEY}\nssh-ed25519 AAAA other", "192.0.2.7", WORKSPACE),
            ("", "192.0.2.7", WORKSPACE),
            (self.KEY, '192.0.2.7",permitopen="*', WORKSPACE),
            (self.KEY, "checkmk.example.org", WORKSPACE),
            (self.KEY, "", WORKSPACE),
            (self.KEY, "192.0.2.7", ""),
            (self.KEY, "192.0.2.7", None),
            (self.KEY, "192.0.2.7", f"ws-{WORKSPACE}"),
            (self.KEY, "192.0.2.7", f'{WORKSPACE}; id",permitopen="*'),
        ):
            with (
                self.subTest(key=key, address=address, workspace=workspace),
                self.assertRaises(ValueError),
            ):
                agent_key_line(key, address, workspace)

    def test_a_loopback_or_unset_checkmk_source_is_refused_by_name(self):
        for address in (
            "127.0.0.1",
            "127.0.1.1",
            "::1",
            "0.0.0.0",  # noqa: S104 a source the rule refuses, never bound
            "::",
            "",
            None,
        ):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(
                    ValueError, "PLATFORM_CHECKMK_ADDRESS.*networks.internet.ip4"
                ),
            ):
                agent_key_line(self.KEY, address, WORKSPACE)

    def test_the_role_and_the_release_match_the_same_line(self):
        role_vars = load_yaml(str(ROLE_VARS))
        self.assertEqual(role_vars["CHECKMK_AGENT_KEY_PATTERN"], AGENT_KEY_PATTERN)
        spec = spec_from_file_location("release_host_under_test", RELEASE_HOST)
        release = module_from_spec(spec)
        spec.loader.exec_module(release)
        self.assertEqual(release.MONITORING_KEY_LINE.pattern, AGENT_KEY_PATTERN)
        self.assertEqual(role_vars["CHECKMK_AGENT_SCRIPT"], release.AGENT_SCRIPT)
        self.assertEqual(role_vars["CHECKMK_AGENT_MARKER"], release.AGENT_MARKER)

    def install_steps(self, script_before, marker_before, download_fails, ours=True):
        """Args:
        script_before: whether the host holds an agent script before the run.
        marker_before: whether it holds the marker before the run.
        download_fails: whether ``get_url_retry`` fails.
        ours: whether the marker records the SHA-256 the script has.

        Returns:
            The effect of ``01_agent_state.yml`` and ``02_agent.yml`` as their
            ``when`` conditions decide it: the script left after the run, or
            ``"refused"``, the marker left and whether the run failed.
        """
        variables = load_yaml(str(ROLE_VARS))
        recorded = "a" * 64 if ours else "b" * 64
        facts = {
            "platform_monitoring_agent_script": {
                "stat": {"exists": script_before, "checksum": "a" * 64}
            },
            "platform_monitoring_agent_marker": {"stat": {"exists": marker_before}},
            "platform_monitoring_agent_record": {
                "content": base64.b64encode(f"{recorded}\n".encode()).decode()
            },
        }
        env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        env.filters["bool"] = lambda value: value is True or value == "True"
        env.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
        facts["CHECKMK_AGENT_OURS"] = (
            env.from_string(variables["CHECKMK_AGENT_OURS"]).render(**facts).strip()
        )

        def runs(guards):
            return all(env.compile_expression(c)(**facts) for c in guards)

        marker = marker_before
        for task, guards in leaves(load_yaml_any(str(AGENT_STATE))):
            if "ansible.builtin.file" in task and runs(guards):
                marker = False
        tasks = load_yaml_any(str(AGENT_TASKS))
        refusal = next(t for t in tasks if "ansible.builtin.fail" in t)
        if runs(conditions(refusal)):
            return "refused", marker, True
        install = agent_install()
        script = script_before or not download_fails
        if not download_fails:
            return script, True, False
        for task, guards in leaves(install["rescue"]):
            if "ansible.builtin.file" in task and runs(guards):
                if task["ansible.builtin.file"]["path"] == "{{ CHECKMK_AGENT_SCRIPT }}":
                    script = False
                else:
                    marker = False
        return script, marker, True

    def test_a_foreign_agent_is_never_replaced_or_marked(self):
        self.assertEqual(
            self.install_steps(True, False, False), ("refused", False, True)
        )

    def test_an_agent_another_install_changed_is_left_and_unmarked(self):
        self.assertEqual(
            self.install_steps(True, True, False, ours=False), ("refused", False, True)
        )

    def test_the_marker_records_the_digest_only_after_the_download(self):
        block = agent_install()["block"]
        self.assertEqual(
            [next(iter(set(task) - {"name"})) for task in block],
            ["get_url_retry", "ansible.builtin.copy"],
        )
        marker = block[1]["ansible.builtin.copy"]
        self.assertEqual(marker["dest"], "{{ CHECKMK_AGENT_MARKER }}")
        self.assertEqual(marker["content"], "{{ CHECKMK_AGENT_SHA256 }}\n")
        self.assertEqual(
            block[0]["get_url_retry"]["checksum"],
            "sha256:{{ CHECKMK_AGENT_SHA256 }}",
        )
        self.assertEqual(self.install_steps(False, False, False), (True, True, False))

    def test_a_failed_first_download_leaves_neither_script_nor_marker(self):
        self.assertEqual(self.install_steps(False, False, True), (False, False, True))

    def test_a_rerun_updates_its_own_agent_and_keeps_it_on_failure(self):
        self.assertEqual(self.install_steps(True, True, False), (True, True, False))
        self.assertEqual(self.install_steps(True, True, True), (True, True, True))

    def test_removal_needs_the_recorded_digest(self):
        absent = load_yaml_any(str(ABSENT_TASKS))
        script = next(
            task
            for task in absent
            if task.get("ansible.builtin.file", {}).get("path")
            == "{{ CHECKMK_AGENT_SCRIPT }}"
        )
        self.assertEqual(script["when"], "CHECKMK_AGENT_OURS | bool")
        paths = [task.get("ansible.builtin.file", {}).get("path") for task in absent]
        self.assertLess(
            paths.index("{{ CHECKMK_AGENT_SCRIPT }}"),
            paths.index("{{ CHECKMK_AGENT_MARKER }}"),
        )
        self.assertNotIn("when", absent[paths.index("{{ CHECKMK_AGENT_MARKER }}")])
        core = load_yaml_any(str(CORE_TASKS))
        self.assertEqual(core[1]["ansible.builtin.include_tasks"], AGENT_STATE.name)
        withdraw = next(
            task["ansible.builtin.include_tasks"]
            for task in core
            if isinstance(task.get("ansible.builtin.include_tasks"), dict)
        )
        self.assertEqual(withdraw["file"], ABSENT_TASKS.name)
        self.assertIs(withdraw["apply"]["become"], True)


class StackHostTests(unittest.TestCase):
    def test_a_swarm_writes_the_digest_on_its_first_manager(self):
        inventory = {"svc-swarm-manager": {"hosts": ["manager", "standby"]}}
        self.assertEqual(stack_host(inventory, "worker"), "manager")

    def test_a_manager_of_a_child_group_is_the_stack_host(self):
        inventory = {
            "svc-swarm-manager": {"children": ["mgr"]},
            "mgr": {"hosts": ["10.0.0.2"]},
            "customers": {"hosts": ["1.2.3.4"]},
        }
        self.assertEqual(stack_host(inventory, "1.2.3.4"), "10.0.0.2")

    def test_the_order_is_the_one_ansible_gives_groups(self):
        inventory = {
            "svc-swarm-manager": {"children": ["mgr", "other"], "hosts": ["z"]},
            "mgr": {"children": ["deep"], "hosts": ["10.0.0.2"]},
            "deep": {"hosts": ["d1"]},
            "other": {"hosts": ["o1"]},
        }
        self.assertEqual(stack_host(inventory, "1.2.3.4"), "z")
        del inventory["svc-swarm-manager"]["hosts"]
        self.assertEqual(stack_host(inventory, "1.2.3.4"), "10.0.0.2")
        del inventory["mgr"]["hosts"], inventory["other"]["hosts"]
        self.assertEqual(stack_host(inventory, "1.2.3.4"), "d1")

    def test_an_ambiguous_deep_manager_fails_loud(self):
        inventory = {
            "svc-swarm-manager": {"children": ["a", "b"]},
            "a": {"children": ["a1"]},
            "b": {"children": ["b1"]},
            "a1": {"hosts": ["m1"]},
            "b1": {"hosts": ["m2"]},
        }
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            stack_host(inventory, "1.2.3.4")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(
                    ["stack-host", "1.2.3.4"],
                    io.StringIO(json.dumps(inventory)),
                    io.StringIO(),
                ),
                1,
            )

    def test_a_single_host_writes_it_on_itself(self):
        self.assertEqual(
            stack_host({"all": {"children": ["ungrouped"]}}, "target"), "target"
        )
        self.assertEqual(stack_host({"svc-swarm-manager": {}}, "target"), "target")

    def test_the_release_script_asks_on_the_command_line(self):
        out = io.StringIO()
        inventory = io.StringIO(json.dumps({"svc-swarm-manager": {"hosts": ["m"]}}))
        self.assertEqual(main(["stack-host", "w"], inventory, out), 0)
        self.assertEqual(out.getvalue(), "m\n")
        out = io.StringIO()
        self.assertEqual(
            main(["digest-file", str(PROJECT_ROOT)], io.StringIO(), out), 0
        )
        self.assertEqual(out.getvalue(), "/etc/nginx/conf.d/federate.sha256\n")
        out = io.StringIO()
        self.assertEqual(main(["host-segment", "Target"], io.StringIO(), out), 0)
        self.assertEqual(out.getvalue(), "target\n")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["digest"], io.StringIO(), io.StringIO()), 2)
            self.assertEqual(
                main(["host-segment", "." * 2], io.StringIO(), io.StringIO()), 1
            )

    def test_a_digest_entry_starts_with_the_host_segment(self):
        digest = "a" * 64
        segment = host_segment("2001:DB8::1")
        self.assertEqual(digest_entry(digest, "2001:DB8::1"), f"{segment} {digest}")
        self.assertNotIn(" ", segment)
        for bad in ("A" * 64, "a" * 63, ""):
            with self.subTest(digest=bad), self.assertRaises(ValueError):
                digest_entry(bad, "target")

    def test_a_deploy_rewrites_and_drops_its_own_digest_line_alone(self):
        helper = load_helper(DIGEST_LINE, "digest_line")
        with tempfile.TemporaryDirectory() as scratch:
            held = Path(scratch, "federate.sha256")
            own = digest_entry("a" * 64, "Target")
            other = f"targetx {'b' * 64}"
            self.assertTrue(helper.converge(held, "target", own))
            self.assertFalse(helper.converge(held, "target", own))
            self.assertTrue(helper.converge(held, "targetx", other))
            renewed = digest_entry("c" * 64, "target")
            self.assertTrue(helper.converge(held, "target", renewed))
            text = held.read_text(
                encoding="utf-8"
            )  # nocheck: cache-read rewritten here
            self.assertEqual(text, f"{other}\n{renewed}\n")
            self.assertTrue(helper.converge(held, "target", None))
            text = held.read_text(
                encoding="utf-8"
            )  # nocheck: cache-read rewritten here
            self.assertEqual(text, f"{other}\n")
            with self.assertRaises(ValueError):
                helper.converge(held, "target", other)
            self.assertTrue(helper.converge(held, "targetx", None))
            self.assertFalse(held.exists())
        tasks = load_yaml_any(str(FEDERATION_TASKS))
        edit = next(task for task in tasks if "ansible.builtin.script" in task)
        self.assertTrue(
            edit["ansible.builtin.script"]["cmd"].startswith(
                f"{DIGEST_LINE.parent.name}/{DIGEST_LINE.name} "
            )
        )
        self.assertIn(
            "platform_monitoring_digest_entry(inventory_hostname)",
            edit["ansible.builtin.script"]["cmd"],
        )
        self.assertEqual(edit["delegate_to"], "{{ STACK_HOST }}")

    def test_a_workspace_worker_never_federates(self):
        tasks = load_yaml_any(str(FEDERATION_TASKS))
        env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
        env.filters["bool"] = bool

        def runs(task, **facts):
            conditions = task.get("when") or []
            conditions = conditions if isinstance(conditions, list) else [conditions]
            return all(env.compile_expression(c)(**facts) for c in conditions)

        refusal = next(task for task in tasks if "ansible.builtin.fail" in task)
        edit = next(task for task in tasks if "ansible.builtin.script" in task)
        for workspace, host, federated, refused, edits in (
            ("ws", "worker", True, True, False),
            ("ws", "worker", False, False, False),
            ("ws", "manager", True, False, True),
            ("", "worker", True, False, True),
        ):
            facts = {
                "PLATFORM_MONITORING_WORKSPACE": workspace,
                "PLATFORM_MONITORING_FEDERATED": federated,
                "inventory_hostname": host,
                "STACK_HOST": "manager",
            }
            with self.subTest(**facts):
                self.assertEqual(runs(refusal, **facts), refused)
                self.assertEqual(runs(edit, **facts), edits)

    def test_no_ipv6_literal_and_hostname_share_a_segment(self):
        self.assertEqual(host_segment("2001:DB8::1"), "2001_db8__1")
        for name in ("2001_db8__1", "a_b", "fe80--1."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                host_segment(name)
        self.assertEqual(host_segment("fe80--1"), "fe80--1")
        self.assertNotEqual(host_segment("fe80::1"), host_segment("fe80--1"))


def pinned(domain):
    """Returns:
    ``applications`` pinning ``domain`` as the canonical domain of
    ``web-app-prometheus``.
    """
    return {"web-app-prometheus": {"server": {"domains": {"canonical": [domain]}}}}


class FederationDomainTests(unittest.TestCase):
    def test_the_domain_is_derived_from_the_primary_domain_without_a_pin(self):
        self.assertEqual(
            federation_domain({"DOMAIN_PRIMARY": "target.example.org"}),
            "prometheus.target.example.org",
        )

    def test_a_pin_inside_the_primary_domain_wins(self):
        for domain in ("metrics.target.example.org", "target.example.org"):
            with self.subTest(domain=domain):
                variables = {
                    "DOMAIN_PRIMARY": "target.example.org",
                    "applications": pinned(domain),
                }
                self.assertEqual(federation_domain(variables), domain)

    def test_negative_control_a_pin_outside_the_primary_domain_is_derived_over(self):
        for domain in (
            "metrics.example.net",
            "eviltarget.example.org",
            "target.example.org.evil.net",
            "x..y",
        ):
            with self.subTest(domain=domain):
                variables = {
                    "DOMAIN_PRIMARY": "target.example.org",
                    "applications": pinned(domain),
                }
                self.assertEqual(
                    federation_domain(variables), "prometheus.target.example.org"
                )

    def test_negative_control_nothing_to_derive_from_refuses(self):
        for variables in (
            {},
            {"DOMAIN_PRIMARY": "Target.example.org"},
            {"DOMAIN_PRIMARY": "{{ lookup('pipe', 'id') }}"},
            {"applications": pinned("prometheus.target.example.org")},
        ):
            with self.subTest(variables=variables), self.assertRaises(ValueError):
                federation_domain(variables)

    def test_the_release_asks_for_no_federation_domain(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(
                    ["federation-domain", "target.example.org"],
                    io.StringIO("{}"),
                    io.StringIO(),
                ),
                2,
            )


class InternalAddressTests(unittest.TestCase):
    INTERNAL = (
        "192.0.0.8",
        "192.0.0.11",
        "192.0.0.170",
        "192.88.99.1",
        "198.18.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "100::1",
        "2001:1::4",
        "2001:2::1",
        "2001:4:113::1",
        "2001:10::1",
        "2001:40::1",
        "fe80::1%x",
        "3fff::1",
        "5f00::1",
        "localhost.localdomain",
        "ip6-localhost",
        "IP6-LOOPBACK.",
        "::a00:5",
        "224.0.0.1",
        "239.255.255.250",
        "ff02::1",
        "ff0e::1",
        "::ffff:224.0.0.1",
        "64:ff9b::e000:1",
        "64:ff9b::a00:5",
        "64:ff9b:1::a00:5",
        "64:ff9b:1::808:808",
        "::ffff:0:a00:5",
        "2002:a00:5::1",
        "2002:808:808::1",
        "2001:0:4136:e378:8000:63bf:f5ff:fffa",
        "203.0.113.10",
        "2001:db8::1",
        "127.0.0.1",
        "127.1",
        "0x7f000001",
        "2130706433",
        "10.0.0.5",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "[::1]",
        "fe80::1",
        "fe80::1%eth0",
        "fc00::1",
        "fd12:3456::1",
        "::ffff:10.0.0.1",
        "::ffff:127.0.0.1",
        "localhost",
        "LOCALHOST.",
        "app.localhost",
        "100.64.0.1",
        "100.127.255.254",
        "fec0::1",
        "0.0.0.0",  # noqa: S104 a vector the rule refuses, never bound
        "0.1.2.3",
        "0",
        "::",
        "[::]",
        "::ffff:0.0.0.0",
        "::ffff:100.64.0.1",
    )
    EXTERNAL = (
        "192.0.0.9",
        "192.0.0.10",
        "2001:1::1",
        "2001:1::2",
        "2001:1::3",
        "2001:3::1",
        "2001:4:112::1",
        "2001:20::1",
        "2001:2f:ffff::1",
        "2001:30::1",
        "192.52.193.1",
        "192.175.48.1",
        "2620:4f:8000::1",
        "192.0.1.1",
        "2001:200::1",
        "::808:808",
        "64:ff9b::808:808",
        "::ffff:0:808:808",
        "17.0.0.1",
        "172.32.0.1",
        "100.63.255.255",
        "100.128.0.1",
        "1.0.0.0",
        "example.org",
        "10.example.org",
        "notlocalhost",
        None,
    )

    def test_the_vector_lists_are_pinned(self):
        self.assertEqual(
            (INTERNAL_VECTORS, EXTERNAL_VECTORS), (self.INTERNAL, self.EXTERNAL)
        )
        self.assertEqual((len(self.INTERNAL), len(self.EXTERNAL)), (65, 27))

    def test_the_globally_reachable_exceptions_are_the_iana_ones(self):
        self.assertEqual(
            [str(network) for network in GLOBAL_EXCEPTIONS],
            [
                "192.0.0.9/32",
                "192.0.0.10/32",
                "2001:1::1/128",
                "2001:1::2/128",
                "2001:1::3/128",
                "2001:3::/32",
                "2001:4:112::/48",
                "2001:20::/28",
                "2001:30::/28",
            ],
        )
        for network in GLOBAL_EXCEPTIONS:
            with self.subTest(network=network):
                self.assertTrue(
                    any(
                        network.version == block.version and network.subnet_of(block)
                        for block in INTERNAL_NETWORKS
                    )
                )

    def test_every_internal_vector_is_internal(self):
        for value in self.INTERNAL:
            with self.subTest(value=value):
                self.assertTrue(internal_address(value))

    def test_the_vectors_hold_without_the_is_global_of_ipaddress(self):
        class Unknowing:
            def __init__(self, address):
                self.address = address

            def __getattr__(self, name):
                return True if name == "is_global" else getattr(self.address, name)

        original = addresses.routable
        with mock.patch.object(
            addresses, "routable", lambda address: original(Unknowing(address))
        ):
            self.assertEqual(
                [value for value in self.INTERNAL if not internal_address(value)], []
            )
            self.assertEqual(
                [value for value in self.EXTERNAL if internal_address(value)], []
            )

    def test_negative_control_every_external_vector_is_external(self):
        for value in self.EXTERNAL:
            with self.subTest(value=value):
                self.assertFalse(internal_address(value))


class CheckmkHostNameTests(unittest.TestCase):
    WS = "ws-0a1b2c3d-0000-4000-8000-00000000abcd"

    def test_every_spelling_of_a_host_maps_to_its_canonical_form(self):
        for host, canonical in (
            ("2001:db8::1", "2001:db8::1"),
            ("2001:DB8::1", "2001:db8::1"),
            ("2001:db8:0::1", "2001:db8::1"),
            ("2001:0db8::1", "2001:db8::1"),
            ("203.0.113.10", "203.0.113.10"),
            ("target", "target"),
            ("Target", "target"),
            ("Host-A.Example.ORG", "host-a.example.org"),
        ):
            with self.subTest(host=host):
                self.assertEqual(canonical_host(host), canonical)
                self.assertEqual(host_segment(host), host_segment(canonical))

    def test_only_an_ambiguous_legacy_ipv4_form_is_refused(self):
        for host in ("01.2.3.4", "1.2.3.04", "127.1", "0x7f000001", "2130706433"):
            with (
                self.subTest(host=host),
                self.assertRaisesRegex(ValueError, "ambiguous legacy IPv4 form"),
            ):
                canonical_host(host)
        for host in ("fe80::1%x", "[2001:db8::1]", "bad host", "-target", "", None):
            with self.subTest(host=host), self.assertRaises(ValueError):
                canonical_host(host)

    def test_a_host_that_gives_a_dot_segment_is_refused(self):
        for host in (".", "." * 2, "", "..."):
            with self.subTest(host=host), self.assertRaises(ValueError):
                host_segment(host)

    def test_the_sanitising_rules(self):
        for host, name in (
            ("target", "target"),
            ("shop.example.org", "shop.example.org"),
            ("db-1-a", "db-1-a"),
            ("2001:db8::1", "2001_db8__1"),
            ("Mixed", "mixed"),
        ):
            with self.subTest(host=host):
                self.assertEqual(checkmk_host_name(self.WS, host), f"{self.WS}-{name}")
        for host in ("db_1-a", "a b/c@d", "ümlaut"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                checkmk_host_name(self.WS, host)

    def test_an_ipv6_host_never_collides_with_a_hostname(self):
        for address, hostname in (
            ("fe80::1", "fe80--1"),
            ("2001:db8::1", "2001-db8--1"),
        ):
            with self.subTest(address=address):
                self.assertNotEqual(host_segment(address), host_segment(hostname))
                self.assertNotEqual(
                    checkmk_host_name(self.WS, address),
                    checkmk_host_name(self.WS, hostname),
                )

    def test_an_ipv6_scope_id_is_refused_so_no_two_zones_collide(self):
        for host in ("fe80::1%a:b", "fe80::1%a_b", "fe80::1%eth0"):
            with (
                self.subTest(host=host),
                self.assertRaisesRegex(ValueError, "scope id"),
            ):
                host_segment(host)

    def test_the_monitoring_template_names_hosts_with_the_same_function(self):
        spec = spec_from_file_location("monitoring_under_test", MONITORING)
        spec.loader.exec_module(module_from_spec(spec))
        module = sys.modules["monitoring.survey"]
        self.assertEqual(
            module.checkmk_host_name.__code__.co_filename,
            checkmk_host_name.__code__.co_filename,
        )
        self.assertEqual(
            module.path_host.__code__.co_filename, host_segment.__code__.co_filename
        )
        self.assertEqual(module.path_host("fe80::1"), host_segment("fe80::1"))
        self.assertNotIn("def checkmk_host_name", read_text(str(MONITORING_SURVEY)))


class FilterTests(unittest.TestCase):
    def test_the_filters_are_registered(self):
        self.assertEqual(
            set(FilterModule().filters()),
            {
                "platform_monitoring_share",
                "platform_monitoring_federate",
                "platform_monitoring_digest",
                "platform_monitoring_digest_entry",
                "platform_monitoring_host_segment",
                "platform_monitoring_digest_reference",
                "platform_monitoring_agent_key_reference",
                "platform_monitoring_agent_key_line",
                "platform_monitoring_agent_url",
                "platform_monitoring_federate_sources",
                "platform_monitoring_resolve",
            },
        )

    def test_a_workspace_federates_to_the_platform_prometheus_alone(self):
        self.assertEqual(
            platform_filters.platform_monitoring_federate_sources(
                WORKSPACE, "198.51.100.7"
            ),
            ["198.51.100.7"],
        )
        self.assertEqual(
            platform_filters.platform_monitoring_federate_sources("", ""), []
        )

    def test_negative_control_a_workspace_without_a_clean_address_fails(self):
        for address in (
            "",
            None,
            "prometheus.example.org",
            "fe80::1%eth0",
            "1.2.3",
            "127.0.0.1",
            "::1",
            "0.0.0.0",  # noqa: S104 a source the rule refuses, never bound
        ):
            with (
                self.subTest(address=address),
                self.assertRaisesRegex(
                    AnsibleFilterError,
                    "PLATFORM_PROMETHEUS_ADDRESS.*networks.internet.ip4",
                ),
            ):
                platform_filters.platform_monitoring_federate_sources(
                    WORKSPACE, address
                )

    def test_the_agent_url_comes_from_the_platform_values_only(self):
        self.assertEqual(
            platform_filters.platform_monitoring_agent_url(
                "checkmk.platform.example.org", "cmk", "ab" * 32
            ),
            "https://checkmk.platform.example.org/cmk/check_mk/agents/check_mk_agent.linux",
        )

    def test_negative_control_a_malformed_platform_value_fails_the_deploy(self):
        good = ("checkmk.platform.example.org", "cmk", "ab" * 32)
        for index, value, finding in (
            (0, "", "PLATFORM_CHECKMK_SERVER"),
            (0, "evil.example.org/x?", "PLATFORM_CHECKMK_SERVER"),
            (1, "../x", "PLATFORM_CHECKMK_SITE"),
            (2, "", "PLATFORM_CHECKMK_AGENT_SHA256"),
            (2, "AB" * 32, "PLATFORM_CHECKMK_AGENT_SHA256"),
            (2, "ab" * 31, "PLATFORM_CHECKMK_AGENT_SHA256"),
        ):
            values = list(good)
            values[index] = value
            with (
                self.subTest(values=values),
                self.assertRaisesRegex(AnsibleFilterError, finding),
            ):
                platform_filters.platform_monitoring_agent_url(*values)

    def test_a_broken_share_fails_the_deploy_with_its_key(self):
        with self.assertRaisesRegex(AnsibleFilterError, "platform_monitoring.logs"):
            platform_monitoring_share({"logs": True})

    def test_a_broken_agent_key_fails_the_deploy(self):
        with self.assertRaisesRegex(AnsibleFilterError, "no IP address"):
            platform_monitoring_agent_key_line(AgentKeyTests.KEY, "", WORKSPACE)

    def test_a_deploy_outside_a_workspace_writes_no_agent_line(self):
        with self.assertRaisesRegex(AnsibleFilterError, "WORKSPACE"):
            platform_monitoring_agent_key_line(AgentKeyTests.KEY, "192.0.2.7", "")

    def test_the_derived_reference_is_read_through_the_openbao_session(self):
        reference = digest_reference(WORKSPACE, "2001:db8::1")
        self.assertEqual(
            reference["openbao"],
            f"monitoring/ws-{WORKSPACE}/federation/2001_db8__1#federation_token_sha256",
        )
        with mock.patch.object(
            platform_filters, "resolve", return_value="ab" * 32
        ) as resolve:
            self.assertEqual(
                platform_filters.platform_monitoring_resolve(
                    reference, "federation_token_sha256"
                ),
                "ab" * 32,
            )
        self.assertEqual(
            resolve.call_args.args[:3],
            (
                reference,
                "secrets.credentials.federation_token_sha256",
                "svc-net-platform-monitoring",
            ),
        )

    def test_a_refused_openbao_read_fails_the_deploy(self):
        with (
            mock.patch.object(
                platform_filters, "resolve", side_effect=OpenBaoError("HTTP 403")
            ),
            self.assertRaisesRegex(AnsibleFilterError, "HTTP 403"),
        ):
            platform_filters.platform_monitoring_resolve(
                agent_key_reference(WORKSPACE, "h"), "agent_public_key"
            )


def agent_install():
    return next(task for task in load_yaml_any(str(AGENT_TASKS)) if "block" in task)


class AgentDownloadTests(unittest.TestCase):
    def test_the_agent_task_verifies_tls_and_the_platform_digest(self):
        install = agent_install()
        fetch = install["block"][0]["get_url_retry"]
        self.assertEqual(fetch["url"], "{{ CHECKMK_AGENT_SCRIPT_URL }}")
        self.assertEqual(fetch["checksum"], "sha256:{{ CHECKMK_AGENT_SHA256 }}")
        self.assertIs(fetch["validate_certs"], True)

    def test_a_checksum_failure_names_the_workspace_reapply(self):
        install = agent_install()
        failure = install["rescue"][-1]["ansible.builtin.fail"]["msg"]
        self.assertIn("re-apply the workspace after a Checkmk upgrade", failure)
        self.assertIn("{{ ansible_failed_result.msg }}", failure)
        self.assertEqual(len(leaves(install["rescue"])), 3)

    def fetch(self, digest):
        """Args:
        digest: the ``sha256:`` checksum the download has to match.

        Returns:
            ``(returncode, installed)``: the exit of the real ``get_url``
            module fetching ``AGENT_SCRIPT`` and whether it reached its
            destination.
        """
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp, "check_mk_agent.linux")
            source.write_bytes(AGENT_SCRIPT)
            dest = Path(tmp, "check_mk_agent")
            run = subprocess.run(
                [
                    str(Path(sys.executable).parent / "ansible"),
                    "localhost",
                    "-c",
                    "local",
                    "-i",
                    "localhost,",
                    "-m",
                    "ansible.builtin.get_url",
                    "-a",
                    f"url=file://{source} dest={dest} checksum=sha256:{digest}",
                ],
                cwd=tmp,
                env={
                    **os.environ,
                    "HOME": tmp,
                    "ANSIBLE_HOME": tmp,
                    "ANSIBLE_LOCAL_TEMP": tmp,
                },
                capture_output=True,
                text=True,
                check=False,
            )
            return run.returncode, dest.exists()

    def test_the_platform_digest_admits_the_agent(self):
        self.assertEqual(
            self.fetch(hashlib.sha256(AGENT_SCRIPT).hexdigest()), (0, True)
        )

    def test_negative_control_a_wrong_digest_is_refused(self):
        code, installed = self.fetch("ab" * 32)
        self.assertNotEqual(code, 0)
        self.assertFalse(installed)


def _literal(rendered):
    """Args:
    rendered: one rendered role variable.

    Returns:
        The value Ansible turns it into: a reference mapping stays a mapping.
    """
    try:
        return ast.literal_eval(rendered)
    except (ValueError, SyntaxError):
        return rendered


class DerivedCredentialTests(unittest.TestCase):
    def render(self, name, workspace, credentials):
        """Args:
        name: the role variable to render.
        workspace: the task's ``WORKSPACE``, empty outside a workspace task.
        credentials: what ``lookup('config')`` holds for the role's
            ``secrets.credentials``.

        Returns:
            ``(value, read)``: the rendered variable and every reference the
            stand-in OpenBao session read.
        """
        role_vars = load_yaml(str(ROLE_VARS))
        read = []
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        env.filters.update(FilterModule().filters())

        def resolve(reference, credential):
            read.append(reference["openbao"])
            return f"from {reference['openbao']}"

        def lookup(kind, *terms):
            if kind == "env":
                return workspace
            return credentials[terms[1].rsplit(".", 1)[1]]

        env.filters["platform_monitoring_resolve"] = resolve
        env.globals["lookup"] = lookup
        context = {
            "application_id": role_vars["application_id"],
            "inventory_hostname": "h",
        }
        references = (
            ("PLATFORM_MONITORING_DIGEST_REFERENCE", "CHECKMK_AGENT_KEY_REFERENCE")
            if workspace
            else ()
        )
        # Exception: Ansible templates a variable only when a used one names it; outside a workspace no reference is reached, and bao_path refuses its empty segment.
        for key in ("PLATFORM_MONITORING_WORKSPACE", *references, name):
            rendered = env.from_string(str(role_vars[key])).render(**context)
            context[key] = rendered if key == name else _literal(rendered)
        return context[name].strip(), read

    def test_a_workspace_deploy_reads_core_derived_references_only(self):
        planted = {
            "federation_token_sha256": "chosen by the inventory",
            "agent_public_key": "chosen by the inventory",
        }
        digest, read = self.render("PLATFORM_MONITORING_DIGEST", WORKSPACE, planted)
        self.assertEqual(
            read, [f"monitoring/ws-{WORKSPACE}/federation/h#federation_token_sha256"]
        )
        self.assertNotIn("chosen by the inventory", digest)
        key, read = self.render("CHECKMK_AGENT_PUBLIC_KEY", WORKSPACE, planted)
        self.assertEqual(read, [f"monitoring/ws-{WORKSPACE}/agent/h#public_key"])
        self.assertNotIn("chosen by the inventory", key)

    def test_negative_control_outside_a_workspace_the_inventory_value_is_used(self):
        digest, read = self.render(
            "PLATFORM_MONITORING_DIGEST", "", {"federation_token_sha256": "ci"}
        )
        self.assertEqual((digest, read), ("ci", []))


if __name__ == "__main__":
    unittest.main()
