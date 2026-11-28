"""The onion backend drop in every play that deploys a stack, and over the life of a port.

``SWARM_ONION_HOST_BACKENDS`` reads a fact the stack host sets right after the
placement step, from the applications carrier parked once the groups are final.
A play that deploys a stack without it renders the refresh digest from an
undefined list and publishes no onion port, so every play that places the
shared services evaluates it and loads the drop before its first stack.

The drop covers that list and every non-public TCP port a live service still
publishes in host mode. A port an earlier run published therefore stays dropped
when the list shrinks, and leaves the drop only once the post-deploy refresh
reads nothing publishing it.
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
import unittest.mock as mock
from collections.abc import Callable, Iterator, Mapping
from typing import TYPE_CHECKING, Any

import jinja2
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.swarm_ingress_guard import FilterModule as SwarmIngressGuard
from plugins.lookup import tor_ports
from plugins.lookup.container_ports import LookupModule as ContainerPorts
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles" / "svc-swarm-node"
TEMPLATE = ROLE / "templates" / "nftables.conf.j2"
REFRESH = ROLE / "tasks" / "utils" / "ingress_guard" / "refresh.yml"
JOIN = ROLE / "tasks" / "00_core" / "ingress_guard.yml"
SWARM = load_yaml_any(str(PROJECT_ROOT / "group_vars" / "all" / "18_swarm.yml"))
DROP = 'iifname != "lo" fib daddr type local tcp dport @onion_backends_tcp drop'
STACK_HOST = "mgr-01"
GROUPS = {
    "wrk-01": ["svc-swarm-node"],
    STACK_HOST: ["svc-swarm-node", "svc-db-mariadb", "svc-net-tor"],
}
FIRST_STACK = {
    "playbook.yml": "tasks/utils/setup/group.yml",
    "playbook-sync.yml": "tasks/utils/sync/",
}
SCOPES = {
    "playbook.yml": [{}],
    "playbook-sync.yml": [{"sync_scope": "role"}, {"sync_scope": "task"}],
}
EXPANDED = ("tasks/stages/", "tasks/utils/constructor/")
PATH_ABSOLUTE = re.compile(r"lookup\('path_absolute', '([^']+)'\)")
SHRUNK = {STACK_HOST: {"swarm_onion_host_backends": []}}


def applications(tor: bool) -> dict:
    """
    Args:
        tor: whether svc-net-tor is deployed for MariaDB.

    Returns:
        An applications view with an exposed MariaDB and an edge proxy that
        declares 443 public.
    """
    return {
        "svc-db-mariadb": {
            "services": {
                "tor": {"enabled": tor},
                "mariadb": {
                    "exposed": True,
                    "ports": {
                        "local": {"mariadb": 3306},
                        "internal": {"mariadb": 3306},
                    },
                },
            }
        },
        "svc-prx-openresty": {
            "services": {
                "openresty": {
                    "ports": {"public": {"https": 443}, "internal": {"https": 443}}
                }
            }
        },
    }


def lookup_on(host: str) -> Callable[..., Any]:
    """
    Args:
        host: the play host whose variables the lookup renders with.

    Returns:
        ``lookup`` as Ansible calls it on *host*: the applications view that
        host renders and the real ``tor_ports`` over it.
    """
    group_names = GROUPS[host]
    view = applications("svc-net-tor" in group_names)

    def lookup(name: str, *terms: object, **kwargs: object) -> object:
        if name == "applications":
            return view
        if name != "tor_ports":
            raise AssertionError(f"unexpected lookup {name!r}")
        with mock.patch.object(tor_ports, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(run=lambda *_a, **_k: [view])
            return tor_ports.LookupModule().run(
                list(terms), variables={"group_names": group_names}, **kwargs
            )[0]

    return lookup


def native() -> NativeEnvironment:
    environment = NativeEnvironment(undefined=jinja2.StrictUndefined)
    environment.filters.update(SwarmIngressGuard().filters())
    environment.filters["bool"] = bool
    environment.filters["to_json"] = json.dumps
    environment.filters["hash"] = lambda text, algorithm: hashlib.new(
        algorithm, text.encode()
    ).hexdigest()
    return environment


class PlayVars(Mapping):
    """The variables of one play host, each templated value rendered on access.

    Args:
        host: the play host.
        facts: per host the facts the play holds.
        read: the lines the ingress guard read printed.
        passed: the ``vars`` of the include that renders, over the group vars.
    """

    def __init__(
        self,
        host: str,
        facts: dict[str, dict],
        read: list[str],
        passed: dict[str, Any] | None = None,
    ) -> None:
        self._environment = native()
        self._values: dict[str, Any] = {
            **SWARM,
            "STACK_HOST": STACK_HOST,
            "inventory_hostname": host,
            "group_names": GROUPS[host],
            "hostvars": {
                name: {**facts.get(name, {}), "group_names": groups}
                for name, groups in GROUPS.items()
            },
            "swarm_ingress_read": {"stdout_lines": read},
            "swarm_ingress_firewall": {"FIREWALL_TABLE": "infinito_svc_swarm_node"},
            "FIREWALL_TABLE": "infinito_svc_swarm_node",
            "lookup": lookup_on(host),
            **(passed or {}),
        }

    def __getitem__(self, key: str) -> Any:
        value = self._values[key]
        if not (isinstance(value, str) and "{{" in value):
            return value
        template = self._environment.from_string(value)
        return self._environment.concat(
            template.root_render_func(template.new_context(self, shared=True))
        )

    def __contains__(self, key: object) -> bool:
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def host_mode(port: int) -> str:
    return (
        f'port [{{"Protocol":"tcp","TargetPort":{port},'
        f'"PublishedPort":{port},"PublishMode":"host"}}]'
    )


def loading_task(source: Path) -> dict:
    """
    Args:
        source: a task file that loads the swarm node baseline.

    Returns:
        Its task that hands the baseline to svc-net-firewall.
    """
    (task,) = [
        task
        for task in load_yaml_any(str(source))
        if "svc-net-firewall"
        in json.dumps(
            task.get("ansible.builtin.include_tasks")
            or task.get("ansible.builtin.include_role")
            or {}
        )
    ]
    return task


def loaded_ruleset(source: Path, facts: dict[str, dict], read: list[str]) -> str:
    """
    Args:
        source: the task file that loads the baseline, the join or the refresh.
        facts: per host the facts the play holds.
        read: the lines the ingress guard read printed.

    Returns:
        The nft table that task renders on a worker.
    """
    variables = PlayVars("wrk-01", facts, read, loading_task(source)["vars"])
    environment = jinja2.Environment(
        keep_trailing_newline=True,
        trim_blocks=True,
        undefined=jinja2.StrictUndefined,
        autoescape=jinja2.select_autoescape(default_for_string=False),
    )
    template = environment.from_string(read_text(str(TEMPLATE)))
    return environment.concat(
        template.root_render_func(template.new_context(variables, shared=True))
    )


def digest(facts: dict[str, dict], read: list[str]) -> str:
    (task,) = [
        task
        for task in load_yaml_any(str(REFRESH))
        if "swarm_ingress_guard_digest" in (task.get("ansible.builtin.set_fact") or {})
    ]
    expression = task["ansible.builtin.set_fact"]["swarm_ingress_guard_digest"]
    return PlayVars(STACK_HOST, facts, read, {"digest": expression})["digest"]


def when_of(task: dict) -> list[str]:
    conditions = task.get("when", [])
    return [conditions] if isinstance(conditions, str) else list(conditions)


def include_path(task: dict) -> str:
    target = task.get("ansible.builtin.include_tasks", task.get("include_tasks", ""))
    if isinstance(target, dict):
        target = target.get("file", "")
    found = PATH_ABSOLUTE.search(str(target))
    return (found.group(1) if found else str(target)).removeprefix("./")


def flatten(
    tasks: list[dict], inherited: list[str]
) -> Iterator[tuple[dict, list[str]]]:
    """
    Args:
        tasks: a task list.
        inherited: the ``when`` conditions of the blocks and includes around it.

    Yields:
        Every task in run order with the conditions around it; blocks and the
        includes of the constructor's own task files are expanded in place.
    """
    for task in tasks:
        yield task, inherited
        path = include_path(task)
        if "block" in task:
            yield from flatten(task["block"], inherited + when_of(task))
        elif path.startswith(EXPANDED) and "{{" not in path:
            yield from flatten(
                load_yaml_any(str(PROJECT_ROOT / path)), inherited + when_of(task)
            )


def before_first_stack(playbook: str) -> list[tuple[dict, list[str]]]:
    """
    Args:
        playbook: a playbook at the project root.

    Returns:
        Its tasks in run order up to the first step that deploys a stack.
    """
    (play,) = load_yaml_any(str(PROJECT_ROOT / playbook))
    ordered = list(flatten(play.get("pre_tasks", []) + play["tasks"], []))
    first = next(
        index
        for index, (task, _) in enumerate(ordered)
        if include_path(task).startswith(FIRST_STACK[playbook])
    )
    return ordered[:first]


def runs(conditions: list[str], **scope: Any) -> bool:
    environment = native()
    return all(
        environment.from_string("{{ " + condition + " }}").render(scope)
        for condition in conditions
    )


def evaluates(task: dict) -> bool:
    return "swarm_onion_host_backends" in (task.get("ansible.builtin.set_fact") or {})


def loads_the_drop(task: dict) -> bool:
    return include_path(task).endswith("ingress_guard/refresh.yml")


def on_stack_host(scope: dict) -> dict:
    return {
        "IS_SWARM_MODE": True,
        "STACK_HOST": STACK_HOST,
        "inventory_hostname": STACK_HOST,
        **scope,
    }


class TestOnionBackendsInEveryPlay(unittest.TestCase):
    def test_every_play_evaluates_the_list_after_its_last_placement(self) -> None:
        for playbook, scopes in SCOPES.items():
            ordered = before_first_stack(playbook)
            for scope in scopes:
                with self.subTest(playbook=playbook, **scope):
                    variables = on_stack_host(scope)
                    placed = [
                        index
                        for index, (task, around) in enumerate(ordered)
                        if "ansible.builtin.add_host" in task
                        and runs(around, **variables)
                    ]
                    evaluated = [
                        index
                        for index, (task, around) in enumerate(ordered)
                        if evaluates(task) and runs(around + when_of(task), **variables)
                    ]
                    self.assertTrue(placed)
                    self.assertEqual(len(evaluated), 1)
                    self.assertGreater(evaluated[0], max(placed))

    def test_every_play_evaluates_the_list_from_a_carrier_parked_after_placing(
        self,
    ) -> None:
        for playbook in SCOPES:
            ordered = before_first_stack(playbook)
            with self.subTest(playbook=playbook):
                evaluation = next(
                    index for index, (task, _) in enumerate(ordered) if evaluates(task)
                )
                placed = max(
                    index
                    for index, (task, _) in enumerate(ordered)
                    if "ansible.builtin.add_host" in task
                )
                carrier = max(
                    index
                    for index, (task, _) in enumerate(ordered[:evaluation])
                    if "applications_carrier" in task
                )
                self.assertGreater(carrier, placed)
                self.assertFalse(
                    ordered[carrier][0]["applications_carrier"].get("clear")
                )

    def test_every_play_loads_the_drop_before_its_first_stack(self) -> None:
        for playbook, scopes in SCOPES.items():
            ordered = before_first_stack(playbook)
            for scope in scopes:
                with self.subTest(playbook=playbook, **scope):
                    variables = on_stack_host(scope)
                    evaluated = [
                        index
                        for index, (task, around) in enumerate(ordered)
                        if evaluates(task) and runs(around + when_of(task), **variables)
                    ]
                    loaded = [
                        index
                        for index, (task, around) in enumerate(ordered)
                        if loads_the_drop(task)
                        and runs(around + when_of(task), **variables)
                    ]
                    self.assertTrue(evaluated)
                    self.assertTrue(loaded)
                    self.assertGreater(min(loaded), evaluated[0])

    def test_a_role_sync_publishes_the_onion_port_and_renders_the_digest(
        self,
    ) -> None:
        ((task, around),) = [
            (task, around)
            for task, around in before_first_stack("playbook-sync.yml")
            if evaluates(task)
        ]
        facts: dict[str, dict] = {}
        for host in GROUPS:
            if runs(
                around + when_of(task),
                **on_stack_host({"sync_scope": "role", "inventory_hostname": host}),
            ):
                facts[host] = {
                    "swarm_onion_host_backends": native()
                    .from_string(
                        task["ansible.builtin.set_fact"]["swarm_onion_host_backends"]
                    )
                    .render(lookup=lookup_on(host))
                }
        publisher = ContainerPorts()
        publisher._loader = mock.MagicMock()
        with mock.patch("plugins.lookup.container_ports.lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications(True)]
            )
            block = publisher.run(
                [["mariadb", "mariadb", "127.0.0.1"]],
                variables={
                    "application_id": "svc-db-mariadb",
                    "DEPLOYMENT_MODE": "swarm",
                    "SWARM_ONION_HOST_BACKENDS": PlayVars("wrk-01", facts, [])[
                        "SWARM_ONION_HOST_BACKENDS"
                    ],
                },
            )[0]
        self.assertIn("published: 3306", block)
        self.assertIn("mode: host", block)
        self.assertRegex(digest(facts, []), r"^[0-9a-f]{64}$")


class TestOnionBackendDropFollowsLivePublishes(unittest.TestCase):
    def test_a_port_still_published_in_host_mode_stays_dropped(self) -> None:
        stale = [host_mode(3306), host_mode(443), "node 10.0.0.2"]
        for source in (JOIN, REFRESH):
            with self.subTest(loaded_by=source.name):
                rendered = loaded_ruleset(source, SHRUNK, stale)
                self.assertIn("elements = { 3306 }", rendered)
                self.assertIn(DROP, rendered)

    def test_the_post_deploy_refresh_reloads_once_nothing_publishes_it(self) -> None:
        stale = [host_mode(3306), host_mode(443), "node 10.0.0.2"]
        drained = [host_mode(443), "node 10.0.0.2"]
        self.assertNotEqual(digest(SHRUNK, stale), digest(SHRUNK, drained))
        self.assertNotIn(DROP, loaded_ruleset(REFRESH, SHRUNK, drained))


if __name__ == "__main__":
    unittest.main()
