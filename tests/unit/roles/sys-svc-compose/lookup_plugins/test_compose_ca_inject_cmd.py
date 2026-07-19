import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.filter.ca_trust_paths import ca_cert_host
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

_CA_TRUST = load_yaml(str(PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"))[
    "CA_TRUST"
]
CA_CERT_CONTAINER = _CA_TRUST["inject_cert_container"]
CA_WRAPPER_CONTAINER = _CA_TRUST["inject_wrapper_container"]


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _FakeDockerLookup:
    """
    Mimics lookup('container', application_id, key).
    """

    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def run(self, terms, variables=None, **kwargs):
        if not isinstance(terms, list) or len(terms) != 2:
            raise AnsibleError(
                f"Fake container lookup: expected [application_id, key], got {terms}"
            )
        _application_id, key = terms
        if key not in self._mapping:
            raise AnsibleError(f"Fake container lookup: missing key '{key}'")
        return [self._mapping[key]]


class _FakeComposeFArgsLookup:
    """
    Mimics lookup('compose_file_args', application_id, include_ca=False).
    """

    def __init__(self, result: str):
        self._result = result
        self.calls: list[dict] = []

    def run(self, terms, variables=None, **kwargs):
        self.calls.append({"terms": terms, "kwargs": kwargs})
        if kwargs.get("include_ca") is not False:
            raise AnsibleError(
                "Fake compose_file_args lookup: expected include_ca=False"
            )
        return [self._result]


class ComposeCaInjectCmdLookupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module(
            "roles/sys-svc-compose/lookup_plugins/compose_ca_inject_cmd.py",
            "compose_ca_inject_cmd",
        )

    def _mk_lookup_module(self):
        lk = self.mod.LookupModule()
        lk._loader = object()
        lk._templar = object()
        return lk

    def test_builds_command_includes_env_file_when_exists(self):
        with tempfile.TemporaryDirectory() as td:
            instance_dir = Path(td)
            env_path = instance_dir / ".env"
            env_path.write_text("X=1\n", encoding="utf-8")

            docker_map = {
                "directories.instance": str(instance_dir),
                "files.env": ".env",
                "files.compose_ca_override": str(
                    instance_dir / "compose.ca.override.yml"
                ),
            }

            compose_file_args = _FakeComposeFArgsLookup(
                "-f compose.yml -f compose.override.yml"
            )

            variables = {
                "CA_TRUST": {
                    "inject_script": "/usr/local/bin/compose_ca.py",
                    "cert_host": ca_cert_host("infinito.nexus"),
                    "wrapper_host": "/usr/local/bin/with-ca-trust.sh",
                    "inject_cert_container": CA_CERT_CONTAINER,
                    "inject_wrapper_container": CA_WRAPPER_CONTAINER,
                    "trust_name": "infinito-root-ca",
                }
            }

            def _fake_get(name, _loader, _templar):
                if name == "container":
                    return _FakeDockerLookup(docker_map)
                if name == "compose_file_args":
                    return compose_file_args
                raise AssertionError(f"Unexpected lookup requested: {name}")

            with (
                patch.object(self.mod.lookup_loader, "get", side_effect=_fake_get),
                patch.object(
                    self.mod,
                    "render_ansible_strict",
                    side_effect=lambda **kw: kw["raw"],
                ),
                patch.object(
                    self.mod, "get_entity_name", side_effect=lambda _x: "myproj"
                ),
            ):
                lk = self._mk_lookup_module()
                out = lk.run(["web-app-test"], variables=variables)

                self.assertIsInstance(out, list)
                self.assertEqual(len(out), 1)

                cmd = out[0]

                self.assertIn("python3", cmd)
                self.assertIn("--chdir", cmd)
                self.assertIn(str(instance_dir), cmd)
                self.assertIn("--project", cmd)
                self.assertIn("myproj", cmd)
                self.assertIn("--compose-files", cmd)
                self.assertIn("compose.yml", cmd)

                self.assertIn("--env-file", cmd)
                self.assertIn(str(env_path), cmd)

                self.assertIn("--out", cmd)
                self.assertIn("compose.ca.override.yml", cmd)
                self.assertNotIn(
                    str(instance_dir / "compose.ca.override.yml"),
                    cmd,
                )

                self.assertTrue(compose_file_args.calls)
                self.assertEqual(
                    compose_file_args.calls[0]["kwargs"].get("include_ca"), False
                )

    def test_builds_command_omits_env_file_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            instance_dir = Path(td)

            docker_map = {
                "directories.instance": str(instance_dir),
                "files.env": ".env",
                "files.compose_ca_override": str(
                    instance_dir / "compose.ca.override.yml"
                ),
            }

            compose_file_args = _FakeComposeFArgsLookup("-f compose.yml")

            variables = {
                "CA_TRUST": {
                    "inject_script": "/usr/local/bin/compose_ca.py",
                    "cert_host": ca_cert_host("infinito.nexus"),
                    "wrapper_host": "/usr/local/bin/with-ca-trust.sh",
                    "inject_cert_container": CA_CERT_CONTAINER,
                    "inject_wrapper_container": CA_WRAPPER_CONTAINER,
                    "trust_name": "infinito-root-ca",
                }
            }

            def _fake_get(name, _loader, _templar):
                if name == "container":
                    return _FakeDockerLookup(docker_map)
                if name == "compose_file_args":
                    return compose_file_args
                raise AssertionError(f"Unexpected lookup requested: {name}")

            with (
                patch.object(self.mod.lookup_loader, "get", side_effect=_fake_get),
                patch.object(
                    self.mod,
                    "render_ansible_strict",
                    side_effect=lambda **kw: kw["raw"],
                ),
                patch.object(
                    self.mod, "get_entity_name", side_effect=lambda _x: "myproj"
                ),
            ):
                lk = self._mk_lookup_module()
                out = lk.run(["web-app-test"], variables=variables)
                cmd = out[0]

                self.assertNotIn("--env-file", cmd)

    def test_raises_when_missing_ca_trust(self):
        lk = self._mk_lookup_module()

        docker_map = {
            "directories.instance": "/opt/compose/app",
            "files.env": ".env",
            "files.compose_ca_override": "/opt/compose/app/compose.ca.override.yml",
        }

        compose_file_args = _FakeComposeFArgsLookup("-f compose.yml")

        def _fake_get(name, _loader, _templar):
            if name == "container":
                return _FakeDockerLookup(docker_map)
            if name == "compose_file_args":
                return compose_file_args
            raise AssertionError(f"Unexpected lookup requested: {name}")

        variables = {}

        with (
            patch.object(self.mod.lookup_loader, "get", side_effect=_fake_get),
            patch.object(
                self.mod, "render_ansible_strict", side_effect=lambda **kw: kw["raw"]
            ),
            patch.object(self.mod, "get_entity_name", side_effect=lambda _x: "myproj"),
            self.assertRaises(AnsibleError) as ctx,
        ):
            lk.run(["web-app-test"], variables=variables)

        self.assertIn("missing required variable 'CA_TRUST'", str(ctx.exception))

    def _run_with_wrapper_kwarg(self, **run_kwargs):
        docker_map = {
            "directories.instance": "/opt/compose/app",
            "files.env": ".env",
            "files.compose_ca_override": "/opt/compose/app/compose.ca.override.yml",
        }
        compose_file_args = _FakeComposeFArgsLookup("-f compose.yml")

        def _fake_get(name, _loader, _templar):
            if name == "container":
                return _FakeDockerLookup(docker_map)
            if name == "compose_file_args":
                return compose_file_args
            raise AssertionError(f"Unexpected lookup requested: {name}")

        variables = {
            "CA_TRUST": {
                "inject_script": "/usr/local/bin/compose_ca.py",
                "cert_host": ca_cert_host("infinito.nexus"),
                "wrapper_host": "/usr/local/bin/with-ca-trust.sh",
                "inject_cert_container": CA_CERT_CONTAINER,
                "inject_wrapper_container": CA_WRAPPER_CONTAINER,
                "trust_name": "infinito-root-ca",
            }
        }

        with (
            patch.object(self.mod.lookup_loader, "get", side_effect=_fake_get),
            patch.object(
                self.mod, "render_ansible_strict", side_effect=lambda **kw: kw["raw"]
            ),
            patch.object(self.mod, "get_entity_name", side_effect=lambda _x: "myproj"),
        ):
            lk = self._mk_lookup_module()
            return lk.run(["web-app-test"], variables=variables, **run_kwargs)[0]

    def test_no_wrapper_flag_appended_when_wrapper_false(self):
        cmd = self._run_with_wrapper_kwarg(wrapper=False)
        self.assertIn("--no-wrapper", cmd)

    def test_no_wrapper_flag_absent_by_default(self):
        cmd = self._run_with_wrapper_kwarg()
        self.assertNotIn("--no-wrapper", cmd)

    def test_wrapper_must_be_bool(self):
        with self.assertRaises(AnsibleError) as ctx:
            self._run_with_wrapper_kwarg(wrapper="yes")
        self.assertIn("wrapper must be a bool", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
