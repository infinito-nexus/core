from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from utils.cache import pin
from utils.cache.render import render_artifacts
from utils.env.handlers.infinito.cache.conf import KEY as CACHE_CONF_KEY
from utils.env.handlers.infinito.cache.conf import RELATIVE as CACHE_CONF

from .coredns import CoreDNSCorefileRenderer
from .network import detect_outer_network_mtu
from .proc import run_streaming
from .profile import Profile
from .runner_mirror import env_image
from .stack import compose_argv
from .target import reset_stack_target

CACHE_APPLY = Path("scripts") / "system" / "cache" / "apply.sh"
CACHE_PIN_DOC = "docs/requirements/096-cache-stack-pin.md"

INIT_IMAGE_KEY = "INFINITO_CACHE_PACKAGE_FRONTEND_INIT_IMAGE"

PACMAN_CACHE_SCRIPT = "/usr/local/bin/pacman-cache.sh"
PACMAN_CONF = "/etc/pacman.conf"


class Compose:
    """Wrapper around `docker compose` for the dev/CI stack."""

    def __init__(self, repo_root: Path, distro: str) -> None:
        self.repo_root = repo_root
        self.distro = distro
        self.profile = Profile()

    def _base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["INFINITO_DISTRO"] = self.distro
        outer_network_mtu = detect_outer_network_mtu(env)
        if outer_network_mtu:
            env["INFINITO_OUTER_NETWORK_MTU"] = outer_network_mtu
        if not env.get("INFINITO_IMAGE"):
            local_image_script = (
                self.repo_root / "scripts" / "meta" / "resolve" / "image" / "local.sh"
            )
            result = subprocess.run(
                [str(local_image_script)],
                cwd=self.repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            env["INFINITO_IMAGE"] = result.stdout.strip()
        return env

    def run(
        self,
        args: list[str],
        *,
        check: bool = True,
        capture: bool = False,
        live: bool = False,
        text: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        cmd = [*compose_argv(self.repo_root), *args]
        env = self._base_env()
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})

        if live:
            r = run_streaming(cmd, cwd=self.repo_root, env=env, text=text)
        else:
            r = subprocess.run(
                cmd,
                cwd=self.repo_root,
                env=env,
                check=False,
                capture_output=capture,
                text=text,
            )

        if check and int(r.returncode) != 0:
            raise subprocess.CalledProcessError(
                int(r.returncode), cmd, output=r.stdout, stderr=r.stderr
            )

        return r

    def _compose_up_with_retries(
        self,
        args: list[str],
        *,
        attempts: int = 6,
        delay_s: int = 30,
    ) -> None:
        """Retry compose up to mitigate transient registry errors."""
        last_exc: Exception | None = None

        for i in range(1, int(attempts) + 1):
            try:
                self.run(args, check=True)
            except Exception as exc:
                last_exc = exc

                if i >= int(attempts):
                    raise

                print(
                    f">>> WARNING: compose up failed (attempt {i}/{attempts}): {exc}\n"
                    f">>> Retrying in {int(delay_s)}s..."
                )
                time.sleep(int(delay_s))
            else:
                return

        if last_exc is not None:
            raise last_exc

    def _cache_apply_helper(self) -> Path:
        return self.repo_root / CACHE_APPLY

    def _cache_apply_env(self, env: dict[str, str]) -> dict[str, str]:
        if not self.profile.image_mirror_enabled():
            return env
        return {**env, INIT_IMAGE_KEY: env_image(self.repo_root, INIT_IMAGE_KEY)}

    def _prepare_pinned_cache(self, env: dict[str, str]) -> None:
        """
        Raises:
            SystemExit: no pin exists yet, `.env` predates the pin, or the
                pinned commit cannot be materialized; the stack does not start.
        """
        print(">>> Preparing the cache stack from the pinned commit")
        r = subprocess.run(
            ["bash", str(self._cache_apply_helper()), "prepare"],
            cwd=self.repo_root,
            env=self._cache_apply_env(env),
            check=False,
            text=True,
        )
        if r.returncode != 0:
            raise SystemExit(
                ">>> ERROR: the cache stack does not start without its pin "
                f"(apply.sh prepare exited rc={r.returncode}, reason above). "
                "Run `make dotenv` if it names an unset key; before the first "
                "pin the declarer runs `make cache-declare ref=<commit>`. "
                f"See {CACHE_PIN_DOC}."
            )

    def _apply_pinned_cache(self, env: dict[str, str]) -> None:
        helper = self._cache_apply_helper()
        print(">>> Applying the pinned cache declarations to the cache stack")
        r = subprocess.run(
            ["bash", str(helper)],
            cwd=self.repo_root,
            env=self._cache_apply_env(env),
            check=False,
            text=True,
        )
        if r.returncode != 0:
            print(
                f">>> WARNING: cache apply exited rc={r.returncode}; the cache "
                "frontend keeps serving the map it already had. See the message "
                f"above, then re-run `make cache-apply` ({helper})."
            )

    def _install_package_frontend_ca_in_runner(self) -> None:
        """Install the frontend CA in the runner trust store. Idempotent."""
        print(">>> Installing package-cache-frontend CA into runner trust store")
        r = self.exec(
            ["sh", "-lc", "/usr/local/bin/package-frontend-ca.sh"],
            check=False,
            live=False,
        )
        if r.returncode != 0:
            print(
                ">>> WARNING: package-frontend-ca installer exited "
                f"rc={r.returncode}; cache TLS via DNS-hijack may fail. "
                "Re-run /usr/local/bin/package-frontend-ca.sh inside the "
                "runner manually."
            )

    def _layer_pacman_cache_in_runner(self) -> None:
        """Point the runner's pacman at the host cache and the shared folder."""
        print(">>> Layering the pacman caches in the runner")
        self.exec(
            [
                PACMAN_CACHE_SCRIPT,
                PACMAN_CONF,
                self.profile.shared_package_cache(),
                self.profile.host_pacman_cache(),
            ],
            live=False,
        )

    def _render_coredns_corefile(self) -> None:
        renderer = CoreDNSCorefileRenderer(repo_root=self.repo_root)
        out = renderer.render(show_preview=True, preview_lines=25)
        print(f"[compose] Corefile generated at: {out}")
        print(
            f"[compose] Corefile exists={out.exists()} "
            f"size={out.stat().st_size if out.exists() else 'n/a'}"
        )

    def _render_cache_artifacts(self) -> None:
        """Render the generated cache files the overrides mount.

        `make dotenv` renders them too, but `scripts/meta/env/load.sh` only
        auto-generates `.env` — it runs on the bare bootstrap python, which
        has no Jinja. Without this, a checkout that never ran `make dotenv`
        reaches `extends: compose.cache-consumer.yml` with the file absent.
        """
        conf = Path(os.environ.get(CACHE_CONF_KEY, "") or (self.repo_root / CACHE_CONF))
        served = pin.served_hosts(os.environ)
        for path in render_artifacts(self.repo_root, conf, served):
            print(f"[compose] cache file generated at: {path}")

    def up(self, *, run_entry_init: bool = True) -> None:
        print(">>> Rendering the derived cache files from the cache: declarations")
        self._render_cache_artifacts()

        print(">>> Rendering CoreDNS Corefile from template")
        self._render_coredns_corefile()

        print(">>> Starting compose stack (coredns + infinito)")
        env = self._base_env()
        keys = [
            "INFINITO_BUILD",
            "INFINITO_DISTRO",
            "INFINITO_IMAGE",
            "INFINITO_IMAGE_TAG",
            "INFINITO_PULL_POLICY",
            "GITHUB_SHA",
        ]
        print(">>> env:", {k: env.get(k) for k in keys})
        print(">>> NIX_CONFIG:", "<set>" if env.get("NIX_CONFIG") else "<empty>")

        no_build = env["INFINITO_BUILD"] != "1"
        args: list[str] = ["up", "-d"]
        if no_build:
            args.append("--no-build")
        if self.profile.owns_cache_stack():
            self._prepare_pinned_cache(env)
            args += ["registry-cache", "package-cache", "package-cache-frontend"]
        args += ["coredns", "infinito"]

        self._compose_up_with_retries(args, attempts=6, delay_s=30)

        self.wait_for_healthy()

        if self.profile.cache_stack_enabled():
            self._apply_pinned_cache(env)
            self._install_package_frontend_ca_in_runner()
            if self.profile.shared_package_cache():
                self._layer_pacman_cache_in_runner()

        if run_entry_init:
            print(">>> Running infinito entry.sh init")
            src_dir = os.environ["INFINITO_SRC_DIR"]
            r = self.exec(
                ["sh", "-lc", f"{src_dir}/scripts/docker/entry.sh true"],
                workdir=src_dir,
                check=False,
                live=True,
                extra_env={
                    "ANSIBLE_FORCE_COLOR": "1",
                    "PY_COLORS": "1",
                    "TERM": "xterm-256color",
                },
            )

            if r.returncode != 0:
                raise RuntimeError(f"entry.sh init failed (rc={r.returncode})")

        self.reset_target()

    def reset_target(self) -> None:
        reset_stack_target(self)

    def down(self) -> None:
        """Tear down the stack."""
        from .down import down_stack

        down_stack(repo_root=self.repo_root, distro=self.distro)

    def exec(
        self,
        cmd: list[str],
        *,
        check: bool = True,
        workdir: str | None = None,
        capture: bool = False,
        live: bool = False,
        tty: bool | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        """Execute inside the infinito container.

        tty=None auto-selects (local: True, CI: False).
        live=True streams stdout/stderr.
        """
        if tty is None:
            tty = not self.profile.is_ci()

        args = ["exec"]
        if not tty:
            args.append("-T")

        if workdir:
            args += ["-w", workdir]

        if extra_env:
            for k, v in extra_env.items():
                args += ["-e", f"{k}={v}"]

        args += ["infinito", *cmd]

        return self.run(
            args,
            check=check,
            capture=capture,
            live=live,
        )

    def _get_infinito_container_id(self) -> str:
        r = self.run(["ps", "-q", "infinito"], capture=True, check=True)
        cid = (r.stdout or "").strip()

        if not cid:
            raise RuntimeError(
                "infinito container not found (docker compose ps -q infinito returned empty)"
            )

        return cid

    def wait_for_healthy(self, *, timeout_s: int | None = None) -> None:
        """Wait for the infinito container's healthcheck."""
        if timeout_s is None:
            timeout_s = int(os.environ["INFINITO_WAIT_HEALTH_TIMEOUT_S"])

        print(">>> Waiting for infinito container to become healthy")

        cid = self._get_infinito_container_id()
        start = time.time()

        while True:
            r = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", cid],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )

            status = r.stdout.strip() if r.returncode == 0 else ""

            if status == "healthy":
                print(">>> infinito container is healthy")
                return

            if status == "unhealthy":
                print(">>> infinito container is unhealthy")

            if (time.time() - start) > timeout_s:
                print(
                    ">>> ERROR: infinito container not healthy, dumping last 200 log lines\n"
                )

                logs = self.exec(
                    ["sh", "-lc", "journalctl -n 200 --no-pager || true"],
                    check=False,
                    capture=True,
                )

                print("===== journalctl (last 200 lines) =====")
                print(logs.stdout or "<no output>")
                print("======================================\n")

                docker_logs = subprocess.run(
                    ["docker", "logs", "--tail", "200", cid],
                    cwd=self.repo_root,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                print("===== docker logs (last 200 lines) =====")
                print(docker_logs.stdout or "<no output>")
                print("=======================================\n")

                raise RuntimeError(
                    f"infinito container not healthy after {timeout_s}s "
                    f"(last status: {status})"
                )

            time.sleep(2)
