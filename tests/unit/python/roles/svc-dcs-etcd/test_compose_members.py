import re
import unittest

import jinja2

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.db.instances import build_instances
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE, ROLE_FILE_VARS_MAIN

TEMPLATE = f"roles/svc-dcs-etcd/{ROLE_FILE_TEMPL_COMPOSE}"
VARS = PROJECT_ROOT / "roles" / "svc-dcs-etcd" / ROLE_FILE_VARS_MAIN
HOSTS = ["mgr-01", "mgr-02", "mgr-03"]


def _env(instances):
    def lookup(name, *_args, **_kwargs):
        if name == "db_instances":
            return instances
        if name == "container_image":
            return "image: etcd"
        if name == "template":
            return "build:\n  context: .\n  dockerfile: Dockerfile"
        return ""

    env = jinja2.Environment(
        autoescape=jinja2.select_autoescape(default_for_string=False),
        loader=jinja2.ChoiceLoader(
            [
                jinja2.DictLoader(
                    {
                        "roles/sys-svc-compose/templates/base.yml.j2": "services:\n\n",
                        "roles/sys-svc-container/templates/base.yml.j2": "",
                    }
                ),
                jinja2.FileSystemLoader(str(PROJECT_ROOT)),
            ]
        ),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["regex_replace"] = lambda value, pattern, repl: re.sub(
        pattern, repl, value
    )
    env.globals["lookup"] = lookup
    return env


def _render(hosts, joining=()):
    """Render the compose members for *hosts*.

    Ansible keeps the YAML-unescaped ``\\1`` of ETCD_INITIAL_CLUSTER a regex
    backreference, while plain Jinja octal-decodes it to ``\\x01``, so the
    expression is re-escaped before this harness renders it.

    Args:
        hosts: inventory hosts carrying an etcd member.
        joining: members this run registers in a live cluster.
    """
    instances = build_instances(
        "svc-dcs-etcd", hosts, deployment_mode="swarm", swarm_nodes=hosts
    )
    env = _env(instances)
    members = [i["service"] for i in instances["instances"]]
    raw_vars = load_yaml_str(read_text(str(VARS)))
    expression = raw_vars["ETCD_INITIAL_CLUSTER"].replace("\\1", "\\\\1")
    initial_cluster = env.from_string(expression).render(
        ETCD_MEMBERS=members, ETCD_PEER_PORT=2380
    )
    rendered = env.get_template(TEMPLATE).render(
        application_id="svc-dcs-etcd",
        ETCD_INITIAL_CLUSTER=initial_cluster,
        ETCD_CLIENT_PORT=2379,
        ETCD_PEER_PORT=2380,
        ETCD_CLUSTER_TOKEN="infinito-etcd",
        ETCD_DATA_TARGET="/var/lib/etcd",
        ETCD_CA_TARGET="/ca.crt",
        ETCD_CERT_TARGET="/etcd.crt",
        ETCD_KEY_TARGET="/etcd.key",
        ETCD_JOINING_MEMBERS=list(joining),
    )
    return load_yaml_str(rendered)["services"]


class TestEtcdComposeMembers(unittest.TestCase):
    def test_three_hosts_render_three_members(self):
        services = _render(HOSTS)
        self.assertEqual(
            sorted(services), ["etcd-mgr-01", "etcd-mgr-02", "etcd-mgr-03"]
        )

    def test_members_share_the_static_initial_cluster(self):
        services = _render(HOSTS)
        expected = (
            "--initial-cluster="
            "etcd-mgr-01=https://etcd-mgr-01:2380,"
            "etcd-mgr-02=https://etcd-mgr-02:2380,"
            "etcd-mgr-03=https://etcd-mgr-03:2380"
        )
        for name, service in services.items():
            with self.subTest(member=name):
                self.assertIn(expected, service["command"])
                self.assertIn(f"--name={name}", service["command"])
                self.assertIn(
                    f"--initial-advertise-peer-urls=https://{name}:2380",
                    service["command"],
                )

    def test_the_cluster_state_does_not_change_between_deploys(self):
        for name, service in _render(HOSTS).items():
            with self.subTest(member=name):
                self.assertIn("--initial-cluster-state=new", service["command"])

    def test_only_a_joining_member_starts_as_existing(self):
        services = _render(HOSTS, joining=["etcd-mgr-02"])
        self.assertIn(
            "--initial-cluster-state=existing", services["etcd-mgr-02"]["command"]
        )
        self.assertIn("--initial-cluster-state=new", services["etcd-mgr-01"]["command"])

    def test_one_host_renders_single_member(self):
        services = _render(["mgr-01"])
        self.assertEqual(list(services), ["etcd"])
        self.assertIn(
            "--initial-cluster=etcd=https://etcd:2380", services["etcd"]["command"]
        )


if __name__ == "__main__":
    unittest.main()
