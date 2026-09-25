"""Build execution for :class:`infinito_docs.library.Library`.

Split out of ``library.py`` to keep both files under the repository's Python
line cap. ``Builder`` is a mixin: it owns the sphinx runs, the checkout and the
atomic publish, and reaches the queue, state and path helpers through ``self``.
The constants and the two catalog helpers live here so the import runs one way,
from ``library`` to ``builder``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import threading

from babel.messages.pofile import read_po

from infinito_docs.commands import generate_commands, progress_of
from utils.cache.yaml import load_yaml_str

LATEST = "latest"
DEPLOYED = "deployed"
LOG_TAIL = 40
QUEUE_SEPARATOR = ":"


def translated_languages(src):
    """Return the languages of ``src`` and those its ``docs`` catalogs translate.

    Args:
        src: checkout of the version to document.

    Returns:
        ``(known, translated)``: every language of ``meta/languages.yml``
        mapped to its native name, and the codes whose ``docs.po`` holds at
        least one translation.
    """
    languages_file = src / "meta" / "languages.yml"
    if not languages_file.is_file():
        return {}, []
    known = {
        str(code): str((entry or {}).get("native", code))
        for code, entry in (
            load_yaml_str(languages_file.read_text(encoding="utf-8")) or {}
        ).items()
    }
    translated = []
    for code in sorted(known):
        catalog = src / "locale" / code / "LC_MESSAGES" / "docs.po"
        if not catalog.is_file():
            continue
        with catalog.open("rb") as handle:
            if any(m.id and m.string and not m.fuzzy for m in read_po(handle)):
                translated.append(code)
    return known, translated


def write_json(path, payload):
    staging = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    staging.write_text(json.dumps(payload), encoding="utf-8")
    staging.replace(path)


class Builder:
    def _run(self, version, state, command, env, cwd):
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as process:
            for line in process.stdout:
                progress = progress_of(line, state["progress"])
                state["log"] = [*state["log"][-(LOG_TAIL - 1) :], line.rstrip()]
                if progress != state["progress"]:
                    state["progress"] = progress
                    self._save_state(version, **state)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)

    def build(self, version):
        """Build ``version`` into its site, replacing an older site atomically.

        Args:
            version: ``latest`` or a release tag.
        """
        self._forget_refs()
        head, _ = self.refs()
        if version not in self.versions():
            self._dequeue(version)
            return
        if self._current(version, head):
            self._dequeue(version)
            return
        ref = {LATEST: head, DEPLOYED: self.snapshot_ref()}.get(version, version)
        work = self.scratch / version
        src, conf, out = work / "src", work / "conf", work / "out"
        tooling = str(self.package_dir.parent)
        state = {"state": "building", "phase": "checkout", "progress": 0, "log": []}
        try:
            self._save_state(version, **state)
            self._checkout(version, ref, work)

            generators = generate_commands(src)
            env = {**os.environ, "PYTHONPATH": tooling}
            state["phase"] = "generate"
            for step, command in enumerate(generators, start=1):
                self._run(version, state, command, env, work)
                state["progress"] = 10 * step // len(generators)
                self._save_state(version, **state)

            state["phase"] = "sphinx"
            sphinx_env = self._sphinx_env(version, src)
            self._run(
                version,
                state,
                [
                    "sphinx-build",
                    "-M",
                    "html",
                    str(src),
                    str(out),
                    "-c",
                    str(conf),
                    "-j",
                    str(self.jobs),
                ],
                sphinx_env,
                work,
            )
            known, translated = translated_languages(src)
            (self.translations / version).mkdir(parents=True, exist_ok=True)
            write_json(
                self.translations / version / "languages.json",
                {"known": known, "translated": translated},
            )
            self._publish(version, out / "html", ref)
            self._save_state(version, state="ready", phase="", progress=100, log=[])
            for code in translated:
                self.request(version, code, background=True)
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            state["log"] = [*state["log"][-(LOG_TAIL - 1) :], str(exc)]
            self._save_state(version, **{**state, "state": "failed"})
        finally:
            self._dequeue(version)
            shutil.rmtree(work, ignore_errors=True)

    def _checkout(self, version, ref, work):
        """Lay out ``src`` and ``conf`` of ``ref`` under a fresh ``work``.

        Args:
            version: ``latest`` or a release tag.
            ref: the commit or digest the version resolves to.
            work: scratch directory to replace.
        """
        src, conf = work / "src", work / "conf"
        shutil.rmtree(work, ignore_errors=True)
        if version == DEPLOYED:
            shutil.copytree(self.snapshot, src)
        else:
            src.mkdir(parents=True)
            archive = work / "src.tar"
            self._git("archive", "--format=tar", "-o", str(archive), ref)
            with tarfile.open(archive) as tar:
                tar.extractall(src, filter="data")
        shutil.copytree(self.package_dir, conf)
        if (src / "assets" / "img").is_dir():
            shutil.copytree(
                src / "assets" / "img", conf / "assets" / "img", dirs_exist_ok=True
            )

    def _sphinx_env(self, version, src):
        return {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(src), str(self.package_dir.parent)]),
            "PYTHONUNBUFFERED": "1",
            "DOCS_VERSION": version,
        }

    def build_language(self, version, code):
        """Build one translated site of ``version`` into its own scratch.

        Args:
            version: ``latest`` or a release tag.
            code: ISO 639-1 code of a language the version's catalogs translate.
        """
        marker = f"{version}{QUEUE_SEPARATOR}{code}"
        self._forget_refs()
        head, _ = self.refs()
        if not self._current(version, head) or not self.translates(version, code):
            self._dequeue(marker)
            self.request(version)
            return
        ref = {LATEST: head, DEPLOYED: self.snapshot_ref()}.get(version, version)
        work = self.scratch / f"{version}{QUEUE_SEPARATOR}{code}"
        src, conf = work / "src", work / "conf"
        target = work / "out"
        state = {
            "state": "building",
            "phase": f"translate {code}",
            "progress": 0,
            "log": [],
        }
        try:
            self._save_state(marker, **state)
            self._checkout(version, ref, work)
            self._run(
                marker,
                state,
                [
                    "sphinx-build",
                    "-M",
                    "html",
                    str(src),
                    str(target),
                    "-c",
                    str(conf),
                    "-j",
                    str(self.jobs),
                    "-D",
                    f"language={code}",
                    "-D",
                    "html_copy_source=0",
                ],
                self._sphinx_env(version, src),
                work,
            )
            self._publish_site(self.translations / version, code, target / "html", ref)
            self._save_state(marker, state="ready", phase="", progress=100, log=[])
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            state["log"] = [*state["log"][-(LOG_TAIL - 1) :], str(exc)]
            self._save_state(marker, **{**state, "state": "failed"})
        finally:
            shutil.rmtree(work, ignore_errors=True)
            self._dequeue(marker)

    def _publish(self, version, html, ref):
        self._publish_site(self.sites, version, html, ref)

    def _publish_site(self, parent, name, html, ref):
        staging = parent / f".{name}.new"
        retired = parent / f".{name}.old"
        target = parent / name
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(retired, ignore_errors=True)
        staging.mkdir(parents=True)
        html.rename(staging / "html")
        (staging / "ref").write_text(ref, encoding="utf-8")
        if target.exists():
            target.rename(retired)
        staging.rename(target)
        shutil.rmtree(retired, ignore_errors=True)
