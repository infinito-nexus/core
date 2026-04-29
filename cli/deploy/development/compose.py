from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .coredns import CoreDNSCorefileRenderer
from .network import detect_outer_network_mtu
from .proc import run_streaming
from .profile import Profile


class Compose:
    """
    Small wrapper around:
      INFINITO_DISTRO=<distro> docker compose --profile ci [--profile cache] ...
    """

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
        if self.profile.registry_cache_active():
            env["INFINITO_REGISTRY_CACHE_PROXY_CONF"] = (
                "./compose/registry-cache/proxy.conf"
            )
            env["INFINITO_PACKAGE_CACHE_PIP_CONF"] = "./compose/package-cache/pip.conf"
            env["INFINITO_PACKAGE_CACHE_NPMRC"] = "./compose/package-cache/npmrc"
            env["INFINITO_PACKAGE_CACHE_APT_LIST"] = "./compose/package-cache/apt.list"
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
        cmd = ["docker", "compose", *self.profile.args(), *args]
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
                check=False,  # handle check ourselves for consistent behavior
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
        """
        Retry the underlying `docker compose ... up` to mitigate transient registry errors
        (e.g., Docker Hub 500 while pulling coredns).
        """
        last_exc: Exception | None = None

        for i in range(1, int(attempts) + 1):
            try:
                self.run(args, check=True)
                return
            except Exception as exc:
                last_exc = exc

                if i >= int(attempts):
                    # Re-raise the last error to keep previous behavior (fail CI).
                    raise

                print(
                    f">>> WARNING: compose up failed (attempt {i}/{attempts}): {exc}\n"
                    f">>> Retrying in {int(delay_s)}s..."
                )
                time.sleep(int(delay_s))

        # Should be unreachable, but keep mypy happy.
        if last_exc is not None:
            raise last_exc

    def _bootstrap_package_cache(self, env: dict[str, str]) -> None:
        """Run the host-side Nexus 3 OSS bootstrap helper. The script is
        idempotent and exits 0 once the blobstore and proxy repos are
        in place. Failure here MUST NOT abort the up() flow because the
        rest of the stack is already healthy and a manual re-run via
        `scripts/docker/cache/package.sh` is the standard
        recovery path."""
        helper = self.repo_root / "scripts" / "docker" / "cache" / "package.sh"
        print(">>> Bootstrapping package-cache proxy repos")
        r = subprocess.run(
            [str(helper)],
            cwd=self.repo_root,
            env=env,
            check=False,
            text=True,
        )
        if r.returncode != 0:
            print(
                f">>> WARNING: package-cache bootstrap exited rc={r.returncode}; "
                f"re-run {helper} manually or inspect docker logs infinito-package-cache"
            )

    def _render_coredns_corefile(self) -> None:
        renderer = CoreDNSCorefileRenderer(repo_root=self.repo_root)
        out = renderer.render(show_preview=True, preview_lines=25)
        print(f"[compose] Corefile generated at: {out}")
        print(
            f"[compose] Corefile exists={out.exists()} "
            f"size={out.stat().st_size if out.exists() else 'n/a'}"
        )

    def up(self, *, run_entry_init: bool = True) -> None:
        print(">>> Rendering CoreDNS Corefile from template")
        self._render_coredns_corefile()

        print(">>> Starting compose stack (coredns + infinito)")
        env = self._base_env()
        keys = [
            "INFINITO_DISTRO",
            "INFINITO_IMAGE",
            "INFINITO_IMAGE_TAG",
            "INFINITO_PULL_POLICY",
            "INFINITO_NO_BUILD",
            "GITHUB_SHA",
        ]
        print(">>> env:", {k: env.get(k) for k in keys})
        print(">>> NIX_CONFIG:", "<set>" if env.get("NIX_CONFIG") else "<empty>")

        # IMPORTANT: use the same env snapshot that docker compose will use
        no_build = env.get("INFINITO_NO_BUILD", "0") == "1"
        # Compose env-file precedence: later files override earlier ones.
        # So env.local should come AFTER env.ci to override CI defaults locally.
        args = ["--env-file", "env.ci"]

        env_local = self.repo_root / "env.development"
        if env_local.exists():
            print(f">>> Using local env override: {env_local}")
            args += ["--env-file", "env.development"]
        else:
            print(">>> No env.local found (skipping)")

        args += ["up", "-d"]
        if no_build:
            args.append("--no-build")
        # Cache services are profile-gated AND `required: false` on the
        # infinito depends_on, so they would NOT auto-start from the
        # named-services list alone. List them explicitly when the cache
        # profile is active so the proxies come up before infinito.
        if self.profile.registry_cache_active():
            args += ["registry-cache", "package-cache"]
        args += ["coredns", "infinito"]

        # Retry to avoid transient registry/HTTP 5xx errors when pulling images.
        self._compose_up_with_retries(args, attempts=6, delay_s=30)

        self.wait_for_healthy()

        # Bootstrap Nexus proxies once the stack is healthy. Idempotent;
        # re-runs no-op once the blobstore + repos exist. See
        # docs/requirements/012-package-cache-nexus3-oss.md.
        if self.profile.registry_cache_active():
            self._bootstrap_package_cache(env)

        if run_entry_init:
            print(">>> Running infinito entry.sh init")
            r = self.exec(
                ["sh", "-lc", "/opt/src/infinito/scripts/docker/entry.sh true"],
                workdir="/opt/src/infinito",
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

    def down(self) -> None:
        """
        Tear down the infinito docker compose stack for this repo/distro.
        """
        # IMPORTANT:
        # Keep the same behavior as cli.deploy.development.down (volumes + CI cleanup).
        # Local import avoids runtime import cycles.
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
        """
        Execute inside infinito container.

        TTY behavior:
          - tty=None  -> auto (local: True, CI: False)
          - tty=True  -> allocate TTY (colors, interactive)
          - tty=False -> -T (CI safe)

        Streaming:
          - live=True streams stdout/stderr to terminal.
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
        """
        Resolve infinito container ID via docker compose.
        Works independent of project name.
        """
        r = self.run(["ps", "-q", "infinito"], capture=True, check=True)
        cid = (r.stdout or "").strip()

        if not cid:
            raise RuntimeError(
                "infinito container not found (docker compose ps -q infinito returned empty)"
            )

        return cid

    def wait_for_healthy(self, *, timeout_s: int | None = None) -> None:
        """
        Wait until infinito container is marked healthy by Docker.
        On timeout: print last 200 log lines for debugging.
        """
        if timeout_s is None:
            timeout_s = int(os.environ.get("INFINITO_WAIT_HEALTH_TIMEOUT_S", "200"))

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
