from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli.administration.roles import declaration
from cli.contributing.changelog.extract import jumps
from utils import digests
from utils.agents import vm_template
from utils.cache import artefacts as manifest
from utils.cache.files import read_text
from utils.cache.hosts import (
    HTTP_PORT,
    HTTPS_PORT,
    CachedHost,
    CachedRepo,
    Declarations,
)
from utils.orchestrator import webhook
from utils.update import repository
from utils.yaml_bootstrap import BootstrapYamlError

HUB = manifest.HUB
RAW = manifest.GITHUB_RAW
GITHUB = manifest.GITHUB
RELEASE_URL = f"https://{GITHUB}/owner/repo/releases/download/v0.0.1/en.onnx"
ARGOS = manifest.ARGOS_NET
ARGOS_URL = f"https://{ARGOS}/v1/translate-sq_en-1_9.argosmodel"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "f7ede42862ceca07ad1c88a97b67520019c4ac7e5ced250d2e696fa62ab189af"
COMMIT_MESSAGE = "not a 40-digit lowercase hex commit"
NO_ROUTE = "no cache: hosts: route"
HF_URL = f"https://{HUB}/org/repo/resolve/{COMMIT}/model.gguf"
RAW_URL = f"https://{RAW}/owner/repo/{COMMIT}/model.bin"
OTHER_RAW_URL = f"https://{RAW}/other/repo/{COMMIT}/model.bin"
SERVED = Declarations(
    repos=[
        CachedRepo("raw-example", "raw", "https://files.example.org/"),
        CachedRepo("raw-githubusercontent", "raw", f"https://{RAW}/"),
        CachedRepo("raw-huggingface", "raw", f"https://{HUB}/"),
    ],
    hosts=[
        CachedHost("files.example.org", repo="raw-example"),
        CachedHost(HUB, repo="raw-huggingface"),
        CachedHost(RAW, repo="raw-githubusercontent"),
    ],
)
ROOT_AND_OWNER = [
    CachedRepo("raw-root", "raw", f"https://{RAW}/"),
    CachedRepo("raw-owner", "raw", f"https://{RAW}/owner/"),
]

SERVING_ROLE = f"""\
cache:
  repos:
    raw-huggingface:
      flavor: raw
      upstream: https://{HUB}/
    raw-github-owner:
      flavor: raw
      upstream: https://{RAW}/owner
  hosts:
    {HUB}:
      repo: raw-huggingface
"""


def _artefact(**fields: str) -> manifest.Artefact:
    values = {
        "name": "model",
        "url": HF_URL,
        "revision": COMMIT,
        "sha256": DIGEST,
        "size": "807690688",
        "role": "svc-test",
    }
    values.update(fields)
    return manifest.Artefact(**values)


def _block(name: str, url: str, revision: str, sha256: str, size: str) -> str:
    return (
        "cache:\n"
        "  artefacts:\n"
        f"    {name}:\n"
        f"      url: {url}\n"
        f'      revision: "{revision}"\n'
        f'      sha256: "{sha256}"\n'
        f'      bytes: "{size}"\n'
    )


class _RolesTree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.roles = Path(self._tmp.name) / "roles"
        self._role("svc-cache-test", SERVING_ROLE)
        patcher = patch("utils.cache.hosts.ROLES_DIR", self.roles)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _role(self, name: str, networks: str) -> None:
        meta = self.roles / name / "meta"
        meta.mkdir(parents=True)
        (meta / "networks.yml").write_text(networks, encoding="utf-8")


class TestProblems(unittest.TestCase):
    def _assert_reports(self, needle: str, **fields: str) -> None:
        found = manifest.problems(_artefact(**fields), SERVED)
        self.assertTrue(any(needle in problem for problem in found), found)

    def test_a_pinned_artefact_on_the_hub_passes(self) -> None:
        self.assertEqual(manifest.problems(_artefact(), SERVED), [])

    def test_a_hub_dataset_or_space_binds_the_segment_after_resolve(self) -> None:
        for kind in ("datasets", "spaces"):
            with self.subTest(kind=kind):
                url = f"https://{HUB}/{kind}/org/repo/resolve/{COMMIT}/data.bin"
                self.assertEqual(manifest.problems(_artefact(url=url), SERVED), [])

    def test_a_commit_in_the_github_raw_ref_segment_passes(self) -> None:
        self.assertEqual(manifest.problems(_artefact(url=RAW_URL), SERVED), [])

    def test_a_branch_name_is_refused(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/main/model.gguf"
        self._assert_reports(COMMIT_MESSAGE, url=url, revision="main")

    def test_a_tag_is_refused_on_every_host(self) -> None:
        cases = {
            "hub": f"https://{HUB}/org/repo/resolve/v1.2/model.gguf",
            "github raw": f"https://{RAW}/owner/repo/v1.2/model.bin",
        }
        for label, url in cases.items():
            with self.subTest(host=label):
                self._assert_reports(COMMIT_MESSAGE, url=url, revision="v1.2")

    def test_a_revision_that_is_not_40_lowercase_hex_digits_is_refused(self) -> None:
        for revision in (COMMIT[:39], COMMIT + "0", COMMIT.upper(), "20241107"):
            urls = (
                f"https://{HUB}/org/repo/resolve/{revision}/model.gguf",
                f"https://{RAW}/owner/repo/{revision}/model.bin",
            )
            for url in urls:
                with self.subTest(url=url):
                    self._assert_reports(COMMIT_MESSAGE, url=url, revision=revision)

    def test_a_percent_encoded_ref_is_refused(self) -> None:
        for ref in ("ma%69n", "%6c%61%74%65%73%74", "%48EAD"):
            with self.subTest(ref=ref):
                url = f"https://{RAW}/owner/repo/{ref}/model.bin"
                self._assert_reports("percent escape", url=url, revision=ref)

    def test_the_revision_must_be_the_ref_segment(self) -> None:
        cases = {
            "hub": f"https://{HUB}/org/repo/resolve/main/{COMMIT}/m.gguf",
            "github raw": f"https://{RAW}/owner/repo/main/{COMMIT}/m.bin",
        }
        for label, url in cases.items():
            with self.subTest(layout=label):
                self._assert_reports("ref segment", url=url)

    def test_an_unknown_layout_is_refused(self) -> None:
        cases = {
            "hub blob page": f"https://{HUB}/org/repo/blob/{COMMIT}/m.gguf",
            "github raw without a file": f"https://{RAW}/owner/repo/{COMMIT}",
        }
        for label, url in cases.items():
            with self.subTest(layout=label):
                self._assert_reports("file layout", url=url)

    def test_a_hub_repo_without_an_org_or_with_two_resolves_is_refused(self) -> None:
        cases = {
            "model": f"https://{HUB}/gpt2/resolve/resolve/{COMMIT}/m.gguf",
            "dataset": f"https://{HUB}/datasets/squad/resolve/resolve/{COMMIT}/f.bin",
            "file": f"https://{HUB}/org/repo/resolve/{COMMIT}/resolve/m.gguf",
        }
        for label, url in cases.items():
            with self.subTest(layout=label):
                self._assert_reports("file layout", url=url)

    def test_a_hub_url_short_of_its_layout_is_refused(self) -> None:
        cases = {
            "no file": f"https://{HUB}/org/repo/resolve/{COMMIT}",
            "no org": f"https://{HUB}/gpt2/resolve/{COMMIT}/m.gguf",
            "dataset without a file": f"https://{HUB}/datasets/org/repo/resolve/{COMMIT}",
            "no ref": f"https://{HUB}/org/repo/resolve",
        }
        for label, url in cases.items():
            with self.subTest(layout=label):
                self._assert_reports("file layout", url=url)

    def test_a_host_without_a_ref_layout_is_refused(self) -> None:
        url = f"https://files.example.org/{COMMIT}/model.bin"
        self._assert_reports("no known ref layout", url=url)

    def test_unsafe_url_shapes_are_refused(self) -> None:
        base = f"https://{RAW}/owner/repo/{COMMIT}"
        cases = {
            f"{base}/../model.bin": "all-dot segment",
            f"{base}/./model.bin": "all-dot segment",
            f"{base}//model.bin": "empty",
            f"{base}/%2e%2e/model.bin": "percent escape",
            f"{base}/%252e/model.bin": "percent escape",
            f"{base}/a b.bin": "whitespace",
            f"{base}/a\nb.bin": "whitespace",
            f"{base}/a;$(id).bin": "outside A-Z",
            f"{base}/a`id`.bin": "outside A-Z",
            f"{base}/a|b.bin": "outside A-Z",
            f"{base}/model.bin?token=x": "query",
            f"{base}/model.bin#main": "fragment",
            f"https://user@{RAW}/owner/repo/{COMMIT}/model.bin": "userinfo",
            f"https://{RAW}:443/owner/repo/{COMMIT}/model.bin": "explicit port",
        }
        for url, needle in cases.items():
            with self.subTest(url=url):
                self._assert_reports(needle, url=url)

    def test_a_malformed_digest_is_refused(self) -> None:
        for digest in (DIGEST.upper(), DIGEST[:-1], DIGEST + "0", ""):
            with self.subTest(digest=digest):
                found = manifest.problems(_artefact(sha256=digest), SERVED)
                self.assertIn("sha256 is not 64 lowercase hex digits", found)

    def test_the_hex_patterns_have_one_definition(self) -> None:
        imported = {
            manifest: ("COMMIT", "SHA256"),
            vm_template: ("SHA256",),
            repository: ("COMMIT",),
            declaration: ("COMMIT", "SHA256"),
            webhook: ("COMMIT",),
            jumps: ("COMMIT",),
        }
        for module, names in imported.items():
            source = read_text(str(module.__file__))
            for name in names:
                with self.subTest(module=module.__name__, name=name):
                    self.assertIs(getattr(module, name), getattr(digests, name))
            for pattern in (digests.COMMIT, digests.SHA256):
                with self.subTest(module=module.__name__, pattern=pattern.pattern):
                    self.assertFalse(
                        pattern.pattern in source,
                        f"{module.__name__} restates {pattern.pattern}",
                    )

    def test_a_name_outside_the_lowercase_charset_is_refused(self) -> None:
        for name in ("Model", "-model", ".model", "_model", "model name", "m/x", ""):
            with self.subTest(name=name):
                self._assert_reports("does not match", name=name)

    def test_a_lowercase_dotted_name_passes(self) -> None:
        artefact = _artefact(name="llama-3.2-1b_q4.gguf")
        self.assertEqual(manifest.problems(artefact, SERVED), [])

    def test_a_size_that_is_not_a_positive_decimal_is_refused(self) -> None:
        for size in ("0", "", "1.5", "-3", "042", "٤٢", "²"):
            with self.subTest(size=size):
                self._assert_reports("bytes", size=size)

    def test_plain_http_is_refused(self) -> None:
        url = HF_URL.replace("https://", "http://")
        self._assert_reports("absolute https URL", url=url)

    def test_a_host_no_repository_proxies_is_refused(self) -> None:
        url = f"https://elsewhere.example.net/{COMMIT}/model.gguf"
        self._assert_reports("no cache: repository upstream", url=url)


class TestArgosVersionRule(unittest.TestCase):
    _SERVED = Declarations(
        repos=[CachedRepo("raw-argos-net", "raw", f"https://{ARGOS}/")],
        hosts=[CachedHost(ARGOS, repo="raw-argos-net")],
    )

    def _problems(self, **fields: str) -> list[str]:
        values = {"url": ARGOS_URL, "revision": "1_9", "unpacked": "900"} | fields
        return manifest.problems(_artefact(**values), self._SERVED)

    def test_a_package_without_its_unpacked_size_is_refused(self) -> None:
        for unpacked in ("", "0", "1.5"):
            with self.subTest(unpacked=unpacked):
                found = self._problems(unpacked=unpacked)
                self.assertTrue(any("unpacked_bytes" in p for p in found), found)

    def test_an_unpacked_size_outside_an_argos_package_is_refused(self) -> None:
        found = manifest.problems(_artefact(unpacked="900"), SERVED)
        self.assertTrue(any("only an Argos package" in p for p in found), found)

    def test_a_versioned_package_with_digest_and_size_passes(self) -> None:
        for version in ("1_9", "1_0_1"):
            with self.subTest(version=version):
                url = f"https://{ARGOS}/v1/translate-sq_en-{version}.argosmodel"
                self.assertEqual(self._problems(url=url, revision=version), [])

    def test_an_unversioned_package_is_refused(self) -> None:
        url = f"https://{ARGOS}/v1/translate-sq_en.argosmodel"
        self.assertTrue(any("file layout" in p for p in self._problems(url=url)), url)

    def test_a_revision_other_than_the_file_version_is_refused(self) -> None:
        found = self._problems(revision="1_8")
        self.assertTrue(any("ref segment" in p for p in found), found)

    def test_a_commit_or_a_dotted_version_is_no_package_version(self) -> None:
        for revision in (COMMIT, "1.9", "v1_9", "1"):
            with self.subTest(revision=revision):
                found = self._problems(revision=revision)
                self.assertTrue(any("package version" in p for p in found), found)

    def test_a_versioned_package_without_its_digest_is_refused(self) -> None:
        found = self._problems(sha256="")
        self.assertIn("sha256 is not 64 lowercase hex digits", found)

    def test_a_versioned_package_without_its_size_is_refused(self) -> None:
        found = self._problems(size="")
        self.assertTrue(any("bytes" in p for p in found), found)

    def test_every_other_host_keeps_the_commit_rule(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/1_9/model.gguf"
        found = manifest.problems(_artefact(url=url, revision="1_9"), SERVED)
        self.assertTrue(any(COMMIT_MESSAGE in p for p in found), found)

    def test_a_package_roots_at_its_directory(self) -> None:
        self.assertEqual(manifest.tree_root(ARGOS_URL), f"{manifest.TREE}/{ARGOS}/v1")


class TestGithubReleaseRule(unittest.TestCase):
    _SERVED = Declarations(
        repos=[CachedRepo("raw-github", "raw", f"https://{GITHUB}/")],
        hosts=[CachedHost(GITHUB, repo="raw-github")],
    )

    def _problems(self, **fields: str) -> list[str]:
        values = {"url": RELEASE_URL, "revision": "v0.0.1"} | fields
        return manifest.problems(_artefact(**values), self._SERVED)

    def test_a_release_asset_at_its_tag_passes(self) -> None:
        self.assertEqual(self._problems(), [])

    def test_any_other_github_path_is_refused(self) -> None:
        for path in (
            f"owner/repo/raw/{COMMIT}/en.onnx",
            "owner/repo/archive/v0.0.1/en.onnx",
            "owner/repo/releases/download/v0.0.1/sub/en.onnx",
            "owner/repo/releases/latest/download/en.onnx",
        ):
            with self.subTest(path=path):
                found = self._problems(url=f"https://{GITHUB}/{path}")
                self.assertTrue(any("file layout" in p for p in found), found)

    def test_a_revision_other_than_the_tag_is_refused(self) -> None:
        found = self._problems(revision="v0.0.2")
        self.assertTrue(any("ref segment" in p for p in found), found)

    def test_a_release_asset_without_its_digest_is_refused(self) -> None:
        self.assertIn(
            "sha256 is not 64 lowercase hex digits", self._problems(sha256="")
        )

    def test_a_release_asset_roots_at_its_tag(self) -> None:
        self.assertEqual(
            manifest.tree_root(RELEASE_URL),
            f"{manifest.TREE}/{GITHUB}/owner/repo/releases/download/v0.0.1",
        )


class TestRepository(unittest.TestCase):
    def _problems(self, url: str, cache: Declarations) -> list[str]:
        return manifest.problems(_artefact(url=url), cache)

    def _assert_reports(self, needle: str, url: str, cache: Declarations) -> None:
        found = self._problems(url, cache)
        self.assertTrue(any(needle in problem for problem in found), found)

    def test_a_url_under_two_repositories_alike_is_refused(self) -> None:
        cache = Declarations(
            repos=[
                CachedRepo("raw-a", "raw", f"https://{HUB}/"),
                CachedRepo("raw-b", "raw", f"https://{HUB}"),
            ],
            hosts=[CachedHost(HUB, repo="raw-a")],
        )
        self._assert_reports("raw-a, raw-b alike", HF_URL, cache)

    def test_a_paths_route_does_not_reach_the_tls_listener(self) -> None:
        cache = Declarations(
            repos=ROOT_AND_OWNER,
            hosts=[
                CachedHost(RAW, paths=(("/", "raw-root"), ("/owner/", "raw-owner")))
            ],
        )
        self._assert_reports(f"{NO_ROUTE} of {RAW} serves raw-owner", RAW_URL, cache)
        self.assertEqual(self._problems(OTHER_RAW_URL, cache), [])

    def test_a_host_without_a_tls_listener_is_refused(self) -> None:
        root = ROOT_AND_OWNER[0]
        plain = Declarations(
            repos=[root], hosts=[CachedHost(RAW, repo=root.name, listen=(HTTP_PORT,))]
        )
        self._assert_reports(
            f"cache: hosts: {RAW} lists no {HTTPS_PORT} under ports", RAW_URL, plain
        )
        both = Declarations(
            repos=[root],
            hosts=[CachedHost(RAW, repo=root.name, listen=(HTTP_PORT, HTTPS_PORT))],
        )
        self.assertEqual(self._problems(RAW_URL, both), [])

    def test_a_route_serving_a_broader_repository_is_refused(self) -> None:
        cache = Declarations(
            repos=ROOT_AND_OWNER, hosts=[CachedHost(RAW, repo="raw-root")]
        )
        self._assert_reports(f"{NO_ROUTE} of {RAW} serves raw-owner", RAW_URL, cache)
        self.assertEqual(self._problems(OTHER_RAW_URL, cache), [])

    def test_a_repository_without_a_host_route_is_refused(self) -> None:
        cache = Declarations(repos=SERVED.repos, hosts=[])
        self._assert_reports(f"{NO_ROUTE} of {HUB}", HF_URL, cache)

    def test_a_route_whose_path_is_not_the_upstream_path_is_refused(self) -> None:
        cache = Declarations(
            repos=[ROOT_AND_OWNER[1]], hosts=[CachedHost(RAW, repo="raw-owner")]
        )
        self._assert_reports("whose upstream is not", RAW_URL, cache)


class TestUrlFor(unittest.TestCase):
    def test_an_empty_base_keeps_the_upstream(self) -> None:
        self.assertEqual(manifest.url_for(HF_URL, ""), HF_URL)

    def test_the_shell_default_base_is_the_upstream(self) -> None:
        self.assertEqual(manifest.url_for(HF_URL, "https:/"), HF_URL)

    def test_a_base_prefixes_host_and_path(self) -> None:
        self.assertEqual(
            manifest.url_for(HF_URL, "http://cache.test:8080"),
            f"http://cache.test:8080/{HUB}/org/repo/resolve/{COMMIT}/model.gguf",
        )

    def test_a_base_with_a_path_prefix_keeps_it(self) -> None:
        self.assertEqual(
            manifest.url_for(RAW_URL, "https://cache.test/artefacts"),
            f"https://cache.test/artefacts/{RAW}/owner/repo/{COMMIT}/model.bin",
        )

    def test_a_malformed_base_is_refused(self) -> None:
        cases = (
            "http://cache.test/",
            "http://",
            "http://cache.test ",
            "http://cache test",
            "http://cache.test\n",
            "http://cache.test?x=1",
            "http://cache.test#x",
            "cache.test",
            "ftp://cache.test",
        )
        for base in cases:
            with (
                self.subTest(base=base),
                self.assertRaisesRegex(ValueError, "INFINITO_ARTEFACT_BASE"),
            ):
                manifest.url_for(HF_URL, base)

    def test_a_base_is_refused_naming_the_reason(self) -> None:
        cases = {
            "https:///x": "is not an http or https URL with a host",
            "http://user@cache.test": "carries userinfo",
            "http://user:pw@cache.test": "carries userinfo",
            "http://cache.test:http": "carries a port outside 1 to 65535",
            "http://cache.test:99999": "carries a port outside 1 to 65535",
            "http://cache.test:0": "carries a port outside 1 to 65535",
            "http://cache.test/a%2fb": "carries a percent escape",
        }
        refusers = {
            "url_for": lambda base: manifest.url_for(HF_URL, base),
            "records": manifest.records,
        }
        for base, reason in cases.items():
            for name, refuser in refusers.items():
                with (
                    self.subTest(base=base, refuser=name),
                    self.assertRaisesRegex(
                        ValueError, f"INFINITO_ARTEFACT_BASE '.*' {reason}"
                    ),
                ):
                    refuser(base)


class TestStoreBytes(unittest.TestCase):
    def test_one_digest_counts_once(self) -> None:
        shared = [_artefact(name="a"), _artefact(name="b", role="svc-other")]
        other = _artefact(name="c", sha256="a" * 64, size="10")
        self.assertEqual(manifest.store_bytes([*shared, other]), 807690688 + 10)

    def test_one_digest_with_two_sizes_is_refused(self) -> None:
        declared = [_artefact(name="a"), _artefact(name="b", size="10")]
        with self.assertRaisesRegex(ValueError, "different sizes"):
            manifest.store_bytes(declared)

    def test_only_an_argos_package_unpacks_under_its_digest(self) -> None:
        self.assertEqual(
            [
                manifest.unpack_path(ARGOS_URL, DIGEST),
                manifest.unpack_path(HF_URL, DIGEST),
            ],
            [f"{manifest.UNPACKED}/{DIGEST}", ""],
        )

    def test_unpacked_bytes_count_each_package_digest_once_exactly(self) -> None:
        package = {"url": ARGOS_URL, "revision": "1_9", "sha256": "b" * 64}
        declared = [
            _artefact(name="model"),
            _artefact(name="a", size="41", unpacked="57", **package),
            _artefact(name="b", size="41", unpacked="57", role="svc-x", **package),
        ]
        self.assertEqual(manifest.unpacked_bytes(declared), 57)

    def test_one_package_digest_with_two_unpacked_sizes_is_refused(self) -> None:
        package = {"url": ARGOS_URL, "revision": "1_9", "sha256": "b" * 64}
        declared = [
            _artefact(name="a", size="41", unpacked="57", **package),
            _artefact(name="b", size="41", unpacked="58", **package),
        ]
        with self.assertRaisesRegex(ValueError, "different sizes"):
            manifest.store_bytes(declared)


class TestDeclarations(_RolesTree):
    def test_a_declared_artefact_is_collected_and_rewritten(self) -> None:
        self._role("svc-model", _block("model", HF_URL, COMMIT, DIGEST, "42"))
        found = manifest.records("http://cache.test")
        self.assertEqual(found["model"]["upstream"], HF_URL)
        self.assertEqual(
            found["model"]["url"],
            f"http://cache.test/{HUB}/org/repo/resolve/{COMMIT}/model.gguf",
        )
        self.assertEqual(found["model"]["bytes"], 42)
        self.assertEqual(found["model"]["role"], "svc-model")

    def test_a_record_names_its_per_file_layout_path_by_the_upstream(self) -> None:
        self._role("svc-model", _block("model", HF_URL, COMMIT, DIGEST, "42"))
        found = manifest.records("http://cache.test")
        self.assertEqual(
            [found["model"]["tree"], found["model"]["root"]],
            [
                f"{manifest.TREE}/{HUB}/org/repo/resolve/{COMMIT}/model.gguf",
                f"{manifest.TREE}/{HUB}/org/repo/resolve/{COMMIT}",
            ],
        )

    def test_a_github_raw_url_roots_at_its_commit(self) -> None:
        self.assertEqual(
            manifest.tree_root(RAW_URL), f"{manifest.TREE}/{RAW}/owner/repo/{COMMIT}"
        )

    def test_records_refuse_a_malformed_base_without_any_artefact(self) -> None:
        with self.assertRaisesRegex(ValueError, "ends in a slash"):
            manifest.records("http://cache.test/")

    def test_a_repository_without_a_host_route_is_refused(self) -> None:
        self._role("svc-model", _block("model", RAW_URL, COMMIT, DIGEST, "42"))
        with self.assertRaisesRegex(ValueError, f"{NO_ROUTE} of {RAW}"):
            manifest.checked()

    def test_a_served_host_outside_every_upstream_is_refused(self) -> None:
        url = f"https://{RAW}/intruder/repo/{COMMIT}/model.bin"
        self._role("svc-model", _block("model", url, COMMIT, DIGEST, "42"))
        with self.assertRaisesRegex(ValueError, "no cache: repository upstream"):
            manifest.checked()

    def test_an_upstream_prefix_ends_at_a_segment(self) -> None:
        url = f"https://{RAW}/owner-evil/repo/{COMMIT}/model.bin"
        self._role("svc-model", _block("model", url, COMMIT, DIGEST, "42"))
        with self.assertRaisesRegex(ValueError, "no cache: repository upstream"):
            manifest.checked()

    def test_a_broken_artefact_refuses_the_whole_set(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/main/model.gguf"
        self._role("svc-model", _block("model", url, "main", DIGEST, "42"))
        with self.assertRaisesRegex(ValueError, "svc-model/model"):
            manifest.records("")

    def test_breaches_judge_only_the_artefacts_handed_in(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/main/model.gguf"
        self._role("svc-model", _block("broken", url, "main", DIGEST, "42"))
        self._role("svc-list", "cache:\n  artefacts:\n    - model\n")
        self.assertEqual(manifest.breaches([_artefact()]), [])
        self.assertTrue(manifest.breaches(manifest.artefacts()))

    def test_two_roles_claiming_one_name_differently_raise(self) -> None:
        self._role("svc-a", _block("model", HF_URL, COMMIT, DIGEST, "42"))
        self._role("svc-b", _block("model", HF_URL, COMMIT, DIGEST, "43"))
        with self.assertRaisesRegex(ValueError, "artefact model"):
            manifest.artefacts()

    def test_two_roles_declaring_one_name_identically_raise(self) -> None:
        self._role("svc-a", _block("model", HF_URL, COMMIT, DIGEST, "42"))
        self._role("svc-b", _block("model", HF_URL, COMMIT, DIGEST, "42"))
        with self.assertRaises(ValueError) as raised:
            manifest.artefacts()
        message = str(raised.exception)
        self.assertRegex(message, "declared by svc-a and again by svc-b")
        self.assertNotIn("differently", message)

    def test_a_list_shaped_section_is_a_breach(self) -> None:
        self._role("svc-list", "cache:\n  artefacts:\n    - model\n")
        self.assertEqual(
            manifest.shape_breaches(),
            ["svc-list: cache: artefacts: is a list, not a mapping"],
        )
        with self.assertRaisesRegex(ValueError, "svc-list: cache: artefacts: is a"):
            manifest.checked()

    def test_an_entry_that_is_no_mapping_is_a_breach(self) -> None:
        self._role("svc-scalar", 'cache:\n  artefacts:\n    model: "x"\n')
        with self.assertRaisesRegex(ValueError, "svc-scalar/model: the entry is a"):
            manifest.checked()

    def test_a_key_beyond_the_four_is_a_breach(self) -> None:
        block = _block("model", HF_URL, COMMIT, DIGEST, "42") + '      mirror: "x"\n'
        self._role("svc-model", block)
        with self.assertRaisesRegex(
            ValueError, "svc-model/model: key 'mirror' is not one of url, revision"
        ):
            manifest.checked()

    def test_one_digest_with_two_sizes_is_a_breach(self) -> None:
        self._role("svc-a", _block("model-a", HF_URL, COMMIT, DIGEST, "42"))
        self._role("svc-b", _block("model-b", HF_URL, COMMIT, DIGEST, "43"))
        with self.assertRaisesRegex(ValueError, "different sizes: svc-a/model-a 42"):
            manifest.checked()

    def test_a_plain_url_with_a_tilde_is_refused_by_the_reader(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/{COMMIT}/m~1.gguf"
        self._role("svc-model", _block("model", url, COMMIT, DIGEST, "42"))
        with self.assertRaises(BootstrapYamlError):
            manifest.artefacts()

    def test_a_quoted_url_with_a_tilde_keeps_the_contract(self) -> None:
        url = f"https://{HUB}/org/repo/resolve/{COMMIT}/m~1.gguf"
        self._role("svc-model", _block("model", f'"{url}"', COMMIT, DIGEST, "42"))
        self.assertEqual([item.url for item in manifest.checked()], [url])


if __name__ == "__main__":
    unittest.main()
