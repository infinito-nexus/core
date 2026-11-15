import importlib.util
import json
import os
import re
import shlex
import sys
import tempfile
import unittest
import unittest.mock as mock
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, select_autoescape

from plugins.lookup import container_volumes as container_volumes_plugin
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-bkp-volume-2-local"
FILES = ROLE / "files" / "python" / "baudolo"
SERVICE_ROLE = PROJECT_ROOT / "roles" / "sys-service"
UNIT_TEMPLATE = SERVICE_ROLE / "templates" / "systemctl.service.j2"
PATHS = PROJECT_ROOT / "group_vars" / "all" / "05_paths.yml"
NOW = datetime(2026, 11, 13, 2, 0, tzinfo=UTC)
RFC3339_NUMERIC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
SIGNAL_TOKENS = (
    "/run/infinito/maintenance",
    "DIR_MAINTENANCE",
    "FILE_MAINTENANCE_BACKUP",
)
VHOST_SUFFIXES = (".conf", ".conf.j2", ".nginx", ".nginx.j2")
SCANNED_SUFFIXES = (".j2", ".conf", ".lua", ".yml", ".yaml")
SIGNAL_OWNERS = frozenset({"svc-bkp-volume-2-local"})
CLEAR = "{{ BKP_VOLUME_2_LOCAL_MAINTENANCE_CLEAR }}"
STOPS = ["web-app-openbao", "web-svc-seaweedfs"]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


if str(FILES) not in sys.path:
    sys.path.append(str(FILES))
SIGNAL = _load("baudolo_maintenance", FILES / "maintenance.py")
LAUNCHER = _load("baudolo_snapshot", FILES / "snapshot.py")
SYSTEMD_DIRECTIVE = _load(
    "systemd_directive", SERVICE_ROLE / "filter_plugins" / "systemd_directive.py"
)


def _maintenance_dir():
    return load_yaml_any(str(PATHS))["DIR_MAINTENANCE"]


def _service_task_vars():
    for task in load_yaml_any(str(ROLE / "tasks" / "00_core.yml")):
        if (task.get("include_role") or {}).get("name") == "sys-service":
            return task["vars"]
    raise AssertionError("tasks/00_core.yml includes no sys-service unit")


def render_unit(template_path, task_vars):
    """
    Args:
        template_path: the sys-service unit template.
        task_vars: the ``system_service_tpl_*`` values the role passes.

    Returns:
        The rendered unit file.
    """
    environment = Environment(autoescape=select_autoescape())
    environment.filters["systemd_directive"] = SYSTEMD_DIRECTIVE.systemd_directive
    source = read_text(str(template_path))
    context = {
        "SOFTWARE_NAME": "Infinito.Nexus",
        "system_service_id": "svc-bkp-volume-2-local",
        "system_service_tpl_on_failure": "",
        "system_service_tpl_after": "",
        "system_service_tpl_before": "",
        "system_service_tpl_wants": "",
        "system_service_tpl_type": "oneshot",
        "system_service_tpl_environment": [],
        "system_service_tpl_remain_after_exit": "",
        "system_service_tpl_timeout_start_sec": "",
        "system_service_tpl_exec_start_pre": "",
        "system_service_tpl_exec_start": "/bin/true",
        "system_service_tpl_exec_start_post": "",
        "system_service_tpl_exec_stop_post": "",
        "system_service_tpl_runtime": "",
        "system_service_tpl_wanted_by": "",
    }
    context.update(task_vars)
    return environment.from_string(source).render(**context)


def unit_directives(rendered, key):
    return [
        line.split("=", 1)[1]
        for line in rendered.splitlines()
        if line.startswith(f"{key}=")
    ]


def role_files():
    """Returns:
    Every file of the project's roles tree.
    """
    roles = f"{PROJECT_ROOT / 'roles'}{os.sep}"
    return [Path(path) for path in iter_project_files() if path.startswith(roles)]


def signal_references(roles_dir, owners, files):
    """
    Args:
        roles_dir: the roles tree the files belong to.
        owners: roles whose own vars and tasks may name the signal.
        files: the files of that tree to scan.

    Returns:
        Every vhost file, and every file of a role outside owners, that names
        the maintenance directory.
    """
    found = []
    for path in sorted(files):
        if not path.name.endswith(SCANNED_SUFFIXES):
            continue
        role = path.relative_to(roles_dir).parts[0]
        vhost = path.name.endswith(VHOST_SUFFIXES) or "nginx" in path.parts
        if role in owners and not vhost:
            continue
        try:
            text = read_text(str(path))
        except (UnicodeDecodeError, OSError):
            continue
        if any(token in text for token in SIGNAL_TOKENS):
            found.append(path)
    return found


class TestSignalDocument(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.document = Path(self.scratch.name) / "backup.json"

    def test_the_signal_holds_its_three_fields(self):
        SIGNAL.announce(self.document, list(reversed(STOPS)), 3600, NOW)
        stored = json.loads(
            self.document.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        )
        self.assertEqual(set(stored), {"applications", "started", "until"})
        self.assertEqual(stored["applications"], STOPS)
        self.assertEqual(stored["started"], "2026-11-13T02:00:00+00:00")
        self.assertEqual(stored["until"], "2026-11-13T03:00:00+00:00")
        for field in ("started", "until"):
            self.assertRegex(stored[field], RFC3339_NUMERIC)
            self.assertIsNotNone(datetime.fromisoformat(stored[field]).utcoffset())

    def test_negative_control_a_planted_fourth_field_fails(self):
        document = SIGNAL.build(["web-app-openbao"], NOW, 60)
        document["reason"] = "nightly"
        with self.assertRaises(ValueError):
            SIGNAL.validate(document)
        with self.assertRaises(ValueError):
            SIGNAL.write(self.document, document)
        self.assertFalse(self.document.exists())

    def test_negative_control_a_time_without_an_offset_fails(self):
        for value in ("2026-11-13T02:00:00", "2026-11-13T02:00:00Z"):
            document = SIGNAL.build(["web-app-openbao"], NOW, 60)
            document["started"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                SIGNAL.validate(document)
        with self.assertRaises(ValueError):
            SIGNAL.stamp(NOW.replace(tzinfo=None))


class TestFailedRun(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.document = Path(self.scratch.name) / "backup.json"

    def unit(self, template_path=UNIT_TEMPLATE):
        task_vars = _service_task_vars()
        return render_unit(
            template_path,
            {
                key: task_vars[key]
                for key in (
                    "system_service_tpl_exec_start_post",
                    "system_service_tpl_exec_stop_post",
                )
            },
        )

    def clear_argv(self):
        variables = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        command = variables["BKP_VOLUME_2_LOCAL_MAINTENANCE_CLEAR"]
        self.assertEqual(
            command,
            "{{ BKP_VOLUME_2_LOCAL_MAINTENANCE_BIN }} clear"
            " --file {{ FILE_MAINTENANCE_BACKUP }}",
        )
        rendered = command.replace(
            "{{ BKP_VOLUME_2_LOCAL_MAINTENANCE_BIN }}", "baudolo-maintenance"
        ).replace("{{ FILE_MAINTENANCE_BACKUP }}", str(self.document))
        return shlex.split(rendered)

    def test_a_failed_run_clears_the_signal(self):
        rendered = self.unit()
        self.assertEqual(unit_directives(rendered, "ExecStopPost"), [CLEAR])
        self.assertEqual(unit_directives(rendered, "ExecStartPost"), [CLEAR])
        SIGNAL.announce(self.document, STOPS, 3600, NOW)
        SIGNAL.main(self.clear_argv()[1:])
        self.assertEqual(SIGNAL.active(self.document, NOW + timedelta(minutes=1)), [])
        stored = json.loads(
            self.document.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        )
        self.assertEqual(stored["applications"], [])

    def test_negative_control_a_unit_without_exec_stop_post_keeps_the_signal(self):
        template = read_text(str(UNIT_TEMPLATE)).replace(
            "  ('ExecStopPost',    system_service_tpl_exec_stop_post),\n", ""
        )
        planted = Path(self.scratch.name) / "systemctl.service.j2"
        planted.write_text(template, encoding="utf-8")
        self.assertEqual(unit_directives(self.unit(planted), "ExecStopPost"), [])

    def test_a_missing_document_is_no_maintenance(self):
        self.assertEqual(SIGNAL.active(self.document, NOW), [])

    def test_an_empty_list_is_no_maintenance(self):
        SIGNAL.announce(self.document, [], 3600, NOW)
        self.assertEqual(SIGNAL.active(self.document, NOW + timedelta(minutes=1)), [])

    def test_a_signal_past_until_is_stale(self):
        SIGNAL.announce(self.document, ["web-app-openbao"], 600, NOW)
        during = NOW + timedelta(seconds=300)
        after = NOW + timedelta(seconds=601)
        self.assertEqual(SIGNAL.active(self.document, during), ["web-app-openbao"])
        self.assertEqual(SIGNAL.active(self.document, after), [])


class TestSnapshotRun(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.document = Path(self.scratch.name) / "backup.json"

    def launch(self, flags):
        order = []

        def write_signal(argv):
            SIGNAL.main(argv[1:])
            announced = SIGNAL.active(self.document, datetime.now(UTC))
            order.append(("announce", announced))
            return ""

        argv = [
            "baudolo-snapshot",
            "--mode",
            "auto",
            "--state-file",
            ".app-control-state",
            "--maintenance-bin",
            "/usr/bin/baudolo-maintenance",
            "--maintenance-file",
            str(self.document),
            "--maintenance-seconds",
            "3600",
            "--stopping",
            STOPS[0],
            "--stopping",
            STOPS[1],
            "--",
            "baudolo",
            "--only-sql",
        ]
        with (
            mock.patch.object(LAUNCHER.sys, "argv", argv),
            mock.patch.object(LAUNCHER, "guarded_flags", return_value=flags),
            mock.patch.object(LAUNCHER, "run", side_effect=write_signal),
            mock.patch.object(
                LAUNCHER.os,
                "execvp",
                side_effect=lambda *_: order.append(("exec", None)),
            ),
        ):
            LAUNCHER.main()
        return order

    def test_a_snapshot_run_announces_no_stop(self):
        order = self.launch(
            ["--snapshot", "btrfs", "--snapshot-subject", "/var/lib/docker"]
        )
        self.assertEqual(order, [("announce", []), ("exec", None)])
        stored = json.loads(
            self.document.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        )
        self.assertEqual(stored["applications"], [])

    def test_negative_control_a_live_run_announces_its_stops_before_baudolo(self):
        self.assertEqual(self.launch([]), [("announce", STOPS), ("exec", None)])


class TestConsumers(unittest.TestCase):
    def render(self, services, maintenance_dir, render_jinja=None):
        return container_volumes_plugin.container_volumes(
            {"web-app-store": {"services": services}},
            "web-app-store",
            "store",
            render_jinja=render_jinja,
            maintenance_dir=maintenance_dir,
        )

    def test_the_signal_is_mounted_read_only_for_its_consumers(self):
        directory = _maintenance_dir()
        self.assertEqual(directory, "/run/infinito/maintenance")
        mount = f"{directory}:{directory}:ro"
        self.assertIn(mount, self.render({"maintenance": {"enabled": True}}, directory))
        jinja_flag = {"maintenance": {"enabled": "{{ true }}"}}
        self.assertIn(mount, self.render(jinja_flag, directory, lambda _: True))
        for services in (
            {},
            {"maintenance": {"enabled": False}},
            {"store": {"enabled": True}},
        ):
            with self.subTest(services=services):
                self.assertNotIn(directory, self.render(services, directory))
        with self.assertRaises(container_volumes_plugin.AnsibleFilterError):
            self.render({"maintenance": {"enabled": True}}, None)

    def test_the_lookup_hands_the_directory_to_every_consumer(self):
        directory = _maintenance_dir()
        lookup = container_volumes_plugin.LookupModule()
        lookup._loader = mock.MagicMock()
        lookup._templar = mock.MagicMock()
        lookup._templar.template.side_effect = lambda value, **_kw: value
        applications = {
            "web-app-store": {"services": {"maintenance": {"enabled": True}}}
        }
        variables = {"application_id": "web-app-store", "DIR_MAINTENANCE": directory}
        with mock.patch.object(container_volumes_plugin, "lookup_loader") as loader:
            loader.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            rendered = lookup.run(["store"], variables=variables)[0]
            self.assertIn(f"- {directory}:{directory}:ro", rendered)
            with self.assertRaises(container_volumes_plugin.AnsibleFilterError):
                lookup.run(["store"], variables={"application_id": "web-app-store"})

    def test_no_core_role_mounts_the_signal_today(self):
        consumers = []
        roles = PROJECT_ROOT / "roles"
        for services_file in sorted(roles.glob(f"*/{ROLE_FILE_META_SERVICES}")):
            services = load_yaml_any(str(services_file)) or {}
            if isinstance(services, dict) and "maintenance" in services:
                consumers.append(services_file.parent.parent.name)
        self.assertEqual(consumers, [])

    def test_no_vhost_serves_the_signal(self):
        self.assertEqual(
            signal_references(PROJECT_ROOT / "roles", SIGNAL_OWNERS, role_files()), []
        )

    def test_negative_control_a_planted_vhost_is_caught(self):
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            vhost = root / "web-app-leak" / "templates" / "nginx" / "locations.conf.j2"
            vhost.parent.mkdir(parents=True)
            vhost.write_text(
                "location /maintenance/ { alias /run/infinito/maintenance/; }\n",
                encoding="utf-8",
            )
            owned = root / "svc-bkp-volume-2-local" / "templates" / "leak.conf.j2"
            owned.parent.mkdir(parents=True)
            owned.write_text("root {{ DIR_MAINTENANCE }};\n", encoding="utf-8")
            self.assertEqual(
                signal_references(root, SIGNAL_OWNERS, [vhost, owned]),
                sorted([vhost, owned]),
            )


if __name__ == "__main__":
    unittest.main()
