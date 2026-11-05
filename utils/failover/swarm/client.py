"""Suite clients of the Swarm lab adapter: the checker and probe services on the spare."""

from __future__ import annotations

import secrets
import shlex

from utils.cache.files import read_text
from utils.failover.checker import parse_probe_output
from utils.failover.swarm import shell
from utils.failover.swarm.commands import (
    CHECKER_SCRIPT,
    PROBE_PATH,
    PROBE_SCRIPT,
    checker_service_argv,
    config_name,
    oneshot_service_argv,
    probe_service_name,
    service_name,
)


class Clients:
    """Mixin of ``SwarmLabBase``: checker and probe runs on the spare worker."""

    def _client_image(self) -> str:
        try:
            image = self._engine_image()
        except RuntimeError:
            image = self._endpoint_image()
        self._seed_spare(image)
        return image

    def _image_volumes(self, image: str) -> list[str]:
        return shell.run(
            [
                "docker",
                "exec",
                self.client_node,
                "docker",
                "image",
                "inspect",
                image,
                "--format",
                "{{range $path, $_ := .Config.Volumes}}{{$path}} {{end}}",
            ]
        ).split()

    def _seed_spare(self, image: str) -> None:
        present = shell.execute(
            ["docker", "exec", self.client_node, "docker", "image", "inspect", image]
        )
        if present.returncode == 0:
            return
        shell.run(
            [
                "sh",
                "-c",
                (
                    f"docker exec {shlex.quote(self._manager())} docker save {shlex.quote(image)}"
                    f" | docker exec -i {shlex.quote(self.client_node)} docker load"  # nocheck: raw-docker  lab nodes are DinD containers on a controller without the container wrapper
                ),
            ],
            timeout=600,
        )

    def start_checker(self, run_id: str, duration_s: int) -> None:
        self.stop_checker(run_id)
        self._on_manager(
            "docker",
            "config",
            "create",
            config_name(run_id),
            "-",
            stdin=read_text(str(CHECKER_SCRIPT)),
        )
        image = self._client_image()
        argv = checker_service_argv(
            engine=self.engine,
            manager=self._manager(),
            spare=self.client_node,
            image=image,
            network=self.engine,
            run_id=run_id,
            duration_s=duration_s,
            scratch_dirs=self._image_volumes(image),
        )
        self._checker_id = shell.run(argv).strip()

    def checker_log(self) -> str:
        """Return the checker's log; raise once its task is gone without one."""
        log = self._spare_logs(self._checker_id)
        if not log:
            lost, errors = self._checker_task_lost()
            if lost:
                raise RuntimeError(
                    f"the checker task on {self.client_node} ended without a container"
                    f" ({'; '.join(errors) or 'no task error'})"
                )
        return log

    def _task_rows(self, service: str) -> list[list[str]]:
        rows = self._on_manager(
            "docker",
            "service",
            "ps",
            service,
            "--no-trunc",
            "--format",
            "{{.CurrentState}}\t{{.Error}}",
            check=False,
        ).split("\n")
        return [r.split("\t", 1) for r in rows if r.strip()]

    @staticmethod
    def _task_errors(rows: list[list[str]]) -> list[str]:
        return sorted({r[1].strip() for r in rows if len(r) > 1 and r[1].strip()})

    def _checker_task_lost(self) -> tuple[bool, list[str]]:
        rows = self._task_rows(self._checker_id)
        lost = bool(rows) and all(
            r[0].startswith(("Failed", "Rejected", "Shutdown", "Orphaned", "Remove"))
            for r in rows
        )
        return lost, self._task_errors(rows)

    def _spare_containers(self, service_id: str, *, exited: bool) -> list[str]:
        return shell.run(
            [
                "docker",
                "exec",
                self.client_node,
                "docker",
                "ps",
                *(["-aq"] if exited else ["-q"]),
                "--filter",
                f"label=com.docker.swarm.service.id={service_id}",
            ],
            check=False,
        ).split()

    def _spare_logs(self, service_id: str) -> str:
        cids = self._spare_containers(service_id, exited=True)
        return "".join(
            shell.run(
                [
                    "docker",
                    "exec",
                    self.client_node,
                    "sh",
                    "-c",
                    f"docker logs {shlex.quote(cid)} 2>&1",
                ],
                check=False,
            )
            for cid in cids
        )

    def finish_checker(self) -> None:
        for cid in self._spare_containers(self._checker_id, exited=False):
            shell.run(
                [
                    "docker",
                    "exec",
                    self.client_node,
                    "docker",
                    "kill",
                    "--signal",
                    "USR1",
                    cid,
                ],
                check=False,
            )

    def stop_checker(self, run_id: str) -> None:
        self._on_manager(
            "docker", "service", "rm", service_name(self.engine), check=False
        )
        self._on_manager("docker", "config", "rm", config_name(run_id), check=False)

    def run_probe(
        self, mode: str, arg: str = "", *, timeout_s: int = 300
    ) -> dict[str, str]:
        """Run ``probe.sh`` once through the write endpoint and return its records.

        Args:
            mode: probe mode (``ddl``, ``marker-write``, ``marker-read``,
                ``idle``, ``memberof-seed``).
            arg: the mode's argument.
            timeout_s: seconds to wait for ``probe-done``.
        """
        name = probe_service_name(self.engine)
        config = f"failover-probe-{secrets.token_hex(4)}"
        self._on_manager("docker", "service", "rm", name, check=False)
        self._on_manager(
            "docker",
            "config",
            "create",
            config,
            "-",
            stdin=read_text(str(PROBE_SCRIPT)),
        )
        try:
            image = self._client_image()
            service_id = shell.run(
                oneshot_service_argv(
                    name=name,
                    manager=self._manager(),
                    spare=self.client_node,
                    image=image,
                    network=self.engine,
                    engine=self.engine,
                    config=config,
                    script_path=PROBE_PATH,
                    env={"ENGINE": self.engine, "MODE": mode, "ARG": arg},
                    scratch_dirs=self._image_volumes(image),
                )
            ).strip()
            records: dict[str, str] = {}

            def finished() -> bool:
                done, found = parse_probe_output(self._spare_logs(service_id))
                records.update(found)
                return done

            if not shell.wait_until(finished, timeout_s=timeout_s, interval_s=5):
                errors = self._task_errors(self._task_rows(service_id))
                tail = [
                    line.strip()
                    for line in self._spare_logs(service_id).splitlines()
                    if line.strip()
                ][-3:]
                raise RuntimeError(
                    f"probe {mode} did not finish in {timeout_s}s"
                    f" ({'; '.join(errors) or 'no task error'};"
                    f" log: {' | '.join(tail) or 'empty'})"
                )
            return records
        finally:
            self._on_manager("docker", "service", "rm", name, check=False)
            self._on_manager("docker", "config", "rm", config, check=False)
