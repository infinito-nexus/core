"""Build execution for :class:`infinito_docs.library.Library`.

``Builder`` is a mixin: it owns the sphinx runs, the checkout and the atomic
publish, and reaches the queue, state and path helpers through ``self``. The
constants live here so the import runs one way, from ``library`` to ``builder``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading

from infinito_docs.catalogs import translated_languages
from infinito_docs.commands import generate_commands, progress_of

LATEST = "latest"
DEPLOYED = "deployed"
LOG_TAIL = 40
QUEUE_SEPARATOR = ":"


def write_json(path, payload):
    staging = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}")
    staging.write_text(json.dumps(payload), encoding="utf-8")
    staging.replace(path)


class Builder:
    def _append_log(self, state, line):
        state["log"] = [*state["log"][-(LOG_TAIL - 1) :], line]

    def _ready(self, marker):
        self._save_state(marker, state="ready", phase="", progress=100, log=[])

    def _failed(self, marker, state, exc, ref):
        self._append_log(state, str(exc))
        self._save_state(marker, **{**state, "state": "failed", "ref": ref})
        print(f"build {marker} failed: {exc}", file=sys.stderr, flush=True)

    def _failed_at(self, marker):
        """Return the ref whose build of ``marker`` last failed, else empty.

        Args:
            marker: queue file name, ``version`` or ``version:code``.
        """
        state = self._state(marker)
        if state.get("state") != "failed":
            return ""
        return str(state.get("ref", ""))

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
                self._append_log(state, line.rstrip())
                if progress != state["progress"]:
                    state["progress"] = progress
                    self._save_state(version, **state)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)

    def _generate(self, marker, state, src, work):
        """Write the generated sources of a checkout before Sphinx reads it.

        Args:
            marker: queue marker the progress is saved under.
            state: build state, advanced to the generate phase in place.
            src: checkout the generators read and write.
            work: directory the generators run in.
        """
        generators = generate_commands(src)
        if not generators:
            return
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(src), str(self.package_dir.parent)]),
        }
        state["phase"] = "generate"
        for step, command in enumerate(generators, start=1):
            self._run(marker, state, command, env, work)
            state["progress"] = 10 * step // len(generators)
            self._save_state(marker, **state)

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
        ref = self._wanted_ref(version, head)
        work = self.scratch / version
        src, conf, out = work / "src", work / "conf", work / "out"
        state = {"state": "building", "phase": "checkout", "progress": 0, "log": []}
        try:
            self._save_state(version, **state)
            self._prepare(version, state, version, ref, work)

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
            self._ready(version)
            for code in translated:
                self.request(version, code, background=True)
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            self._failed(version, state, exc, ref)
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

    def _prepared_dir(self, version, ref):
        """Return where the prepared tree of ``version`` at ``ref`` is kept.

        Args:
            version: ``latest``, ``deployed`` or a release tag.
            ref: the commit or digest the version resolves to.
        """
        key = hashlib.sha256(f"{ref}\0{self.tooling_ref()}".encode()).hexdigest()[:16]
        return self.prepared / f"{version}.{key}"

    @staticmethod
    def _clone_tree(source, target):
        """Copy ``source`` to ``target``, hardlinking the files where it can.

        A prepared tree is the size of a checkout plus its generated output,
        so copying it twice per build would spend more disk writes than the
        reuse saves.

        Args:
            source: tree to clone.
            target: destination, must not exist.
        """
        try:
            shutil.copytree(source, target, copy_function=os.link)
        except OSError:
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(source, target)

    def _seal(self, tree):
        """Drop write permission from every file under ``tree``.

        The reused copies share inodes with it, so a build that writes a
        source file in place would rewrite the cache for every later build.
        Read-only turns that into a loud failure on the first attempt.

        Args:
            tree: the prepared tree to seal.
        """
        for path in tree.rglob("*"):
            if path.is_file():
                path.chmod(path.stat().st_mode & ~0o222)

    def _publish_prepared(self, work, target):
        """Hardlink ``work`` to ``target``, dropping the version's older trees.

        Args:
            work: the scratch tree to clone.
            target: destination from :meth:`_prepared_dir`.
        """
        self.prepared.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.{os.getpid()}")
        shutil.rmtree(staging, ignore_errors=True)
        self._clone_tree(work, staging)
        self._seal(staging)
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
        for stale in self.prepared.glob(f"{target.name.split('.')[0]}.*"):
            if stale != target:
                shutil.rmtree(stale, ignore_errors=True)

    def _prepare(self, marker, state, version, ref, work):
        """Lay out a generated ``work`` tree for ``ref``, reusing a prepared one.

        The generators read and write the checkout and take no language, so
        the same ref yields the same tree for the version's own site and for
        every translated one. Without the reuse each language repeats the
        whole checkout and generation.

        Args:
            marker: queue marker the progress is saved under.
            state: build state, advanced in place.
            version: ``latest``, ``deployed`` or a release tag.
            ref: the commit or digest the version resolves to.
            work: scratch directory to fill.
        """
        cached = self._prepared_dir(version, ref)
        if cached.is_dir():
            state["phase"] = "reuse"
            self._save_state(marker, **state)
            shutil.rmtree(work, ignore_errors=True)
            self._clone_tree(cached, work)
            return
        self._checkout(version, ref, work)
        self._generate(marker, state, work / "src", work)
        self._publish_prepared(work, cached)

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
        if not self.translates(version, code):
            self._dequeue(marker)
            return
        if not self._current(version, head):
            self._dequeue(marker)
            self.request(version)
            self.request(version, code, background=True)
            return
        ref = self._wanted_ref(version, head)
        work = self.scratch / f"{version}-{code}"
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
            self._prepare(marker, state, version, ref, work)
            state["phase"] = f"translate {code}"
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
            self._ready(marker)
        except (OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
            self._failed(marker, state, exc, ref)
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
