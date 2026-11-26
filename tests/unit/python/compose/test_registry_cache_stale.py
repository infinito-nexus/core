"""The registry cache answers from its cached copy while an upstream registry returns 503."""

from __future__ import annotations

import importlib
import shlex
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

role = importlib.import_module("tests.unit.python.roles.svc-registry-cache._render")

TARGET = "/etc/nginx/nginx.manifest.stale.conf"
COMMON = "/etc/nginx/nginx.manifest.common.conf"
OVERRIDE = (
    PROJECT_ROOT
    / "roles"
    / "svc-registry-cache"
    / "files"
    / "nginx.manifest.stale.conf"
)
UPSTREAM = (
    "    # Just like the common block, but adds proxy_cache_use_stale\n"
    '    include "/etc/nginx/nginx.manifest.common.conf";\n'
    "    proxy_cache_use_stale  error timeout http_500 http_502 http_504 http_429;\n"
)


def _parse_directives(conf: str) -> list[list[str]]:
    """
    Args:
        conf: text of an nginx config fragment.

    Returns:
        Every directive, as its name followed by its arguments, quotes and
        comments dropped.
    """
    lexer = shlex.shlex(conf, posix=True, punctuation_chars=";")
    lexer.whitespace_split = True
    directives: list[list[str]] = []
    current: list[str] = []
    for token in lexer:
        if token == ";":
            directives.append(current)
            current = []
        else:
            current.append(token)
    return directives


def _stale_conditions(conf: str) -> set[str]:
    """
    Args:
        conf: text of an nginx config fragment.

    Returns:
        The conditions every ``proxy_cache_use_stale`` directive names.
    """
    return {
        condition
        for directive in _parse_directives(conf)
        if directive[:1] == ["proxy_cache_use_stale"]
        for condition in directive[1:]
    }


def _bridges_503(conf: str) -> bool:
    """Whether *conf* serves a cached copy while the upstream answers 503.

    Args:
        conf: text of an nginx config fragment.
    """
    return "http_503" in _stale_conditions(conf)


def _registry_cache() -> dict:
    """Returns:
    The role volumes the multi-proxy flavor mounts into its cache service.
    """
    volumes = role.load_yaml(str(role.VOLUMES))
    return {
        "volumes": [
            {**volume, "target": mount["target"]}
            for volume in volumes.values()
            for mount in volume["mounts"]
            if mount["service"] == "cache" and "'multi-proxy'" in mount.get("when", "")
        ]
    }


def _bind_at(service: dict, target: str) -> dict | None:
    """Args:
        service: the mounts of one compose service.
        target: container path of the mount.

    Returns:
        The bind *service* mounts at *target*, if any.
    """
    for entry in service.get("volumes", []):
        if isinstance(entry, dict) and entry.get("target") == target:
            return entry
    return None


def _shipped(source: str) -> dict | None:
    """Args:
        source: the bind source of a mount.

    Returns:
        The role file the multi-proxy tasks ship to *source*, if any.
    """
    volume = next(
        key
        for key, entry in role.load_yaml(str(role.VOLUMES)).items()
        if entry.get("source") == source
    )
    for entry in role.multi_proxy_files():
        if f"'{volume}').source" in entry["dest"]:
            return entry
    return None


class TestStaleConfig(unittest.TestCase):
    def test_upstream_file_does_not_bridge_a_503(self) -> None:
        self.assertFalse(_bridges_503(UPSTREAM))

    def test_override_bridges_a_503(self) -> None:  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        self.assertTrue(_bridges_503(read_text(str(OVERRIDE))))

    def test_override_keeps_every_upstream_condition(self) -> None:
        upstream = _stale_conditions(UPSTREAM)
        override = _stale_conditions(read_text(str(OVERRIDE)))
        self.assertTrue(upstream)
        self.assertEqual(upstream - override, set())
        self.assertEqual(override - upstream, {"http_503"})

    def test_override_still_includes_the_common_block(self) -> None:  # nocheck: test.text-presence -- tokenizes the file into commands or directives; the rule taints tokenizer output  # fmt: skip
        self.assertIn(["include", COMMON], _parse_directives(read_text(str(OVERRIDE))))


class TestRegistryCacheMount(unittest.TestCase):
    def test_the_override_is_bound_read_only_over_the_image_file(self) -> None:
        bind = _bind_at(_registry_cache(), TARGET)
        self.assertIsNotNone(bind)
        self.assertEqual(bind["type"], "bind")
        self.assertTrue(bind["read_only"])
        shipped = _shipped(bind["source"])
        self.assertIsNotNone(shipped)
        self.assertEqual((role.ROLE / "files" / shipped["src"]).resolve(), OVERRIDE)
        self.assertTrue(OVERRIDE.is_file())

    def test_a_service_without_the_bind_is_detected(self) -> None:
        service = dict(_registry_cache())
        service["volumes"] = [
            v for v in service["volumes"] if _bind_at({"volumes": [v]}, TARGET) is None
        ]
        self.assertIsNone(_bind_at(service, TARGET))


if __name__ == "__main__":
    unittest.main()
