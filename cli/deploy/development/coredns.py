from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CoreDNSCorefileRenderer:
    """
    Render compose/coredns/Corefile from compose/coredns/Corefile.tmpl using envsubst.

    What this does:
      - Reads variables from env file (default: env.ci)
      - Runs `envsubst` to substitute variables into the Corefile template
      - Writes the output atomically (tmp -> rename)
      - Optionally prints a preview of the first N lines

    Hard guarantees:
      - Fails if template/env files are missing
      - Fails if output path exists and is a directory
      - Fails if output directory cannot be created or is not writable
      - Fails if envsubst is missing
      - Fails if rendered file is empty
    """

    repo_root: Path
    env_filename: str = "env.ci"
    template_relpath: str = "compose/coredns/Corefile.tmpl"
    output_relpath: str = "compose/coredns/Corefile"

    def _log(self, msg: str) -> None:
        print(f"[coredns-corefile] {msg}")

    def _paths(self) -> tuple[Path, Path, Path]:
        env_file = self.repo_root / self.env_filename
        tmpl_file = self.repo_root / self.template_relpath
        out_file = self.repo_root / self.output_relpath
        return env_file, tmpl_file, out_file

    def _require_file(self, path: Path, *, label: str) -> None:
        if not path.exists():
            raise RuntimeError(f"{label} not found: {path}")
        if not path.is_file():
            raise RuntimeError(f"{label} is not a file: {path}")

    def _require_envsubst(self) -> str:
        p = shutil.which("envsubst")
        if not p:
            raise RuntimeError(
                "envsubst not found. Install gettext-base (Ubuntu/Debian) or gettext (Arch)."
            )
        self._log(f"Using envsubst: {p}")
        return p

    def _ensure_output_parent(self, out_file: Path) -> None:
        parent = out_file.parent

        if parent.exists() and not parent.is_dir():
            raise RuntimeError(f"Output parent is not a directory: {parent}")

        if not parent.exists():
            self._log(f"Creating output directory: {parent}")
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RuntimeError(
                    f"Failed to create output directory: {parent}"
                ) from exc

        if not os.access(parent, os.W_OK):
            raise RuntimeError(f"Output directory is not writable: {parent}")

    def _require_output_target(self, out_file: Path) -> None:
        if out_file.exists() and out_file.is_dir():
            raise RuntimeError(f"Output path is a directory: {out_file}")

    def _load_env_file(self, env_file: Path) -> dict[str, str]:
        self._log(f"Loading env file: {env_file}")

        env = dict(os.environ)
        loaded = 0

        with env_file.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k not in env:
                    env[k] = v
                    loaded += 1

        self._log(f"Loaded {loaded} variables from env file")
        return env

    def _preview(self, path: Path, *, max_lines: int) -> None:
        if not path.exists() or not path.is_file():
            self._log(f"Preview skipped: {path}")
            return

        self._log(f"Preview (first {max_lines} lines): {path}")
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in itertools.islice(f, max_lines):
                self._log(f"  {line.rstrip()}")

    def render(self, *, show_preview: bool = True, preview_lines: int = 25) -> Path:
        env_file, tmpl_file, out_file = self._paths()

        self._log(f"Repo root : {self.repo_root}")
        self._log(f"Template  : {tmpl_file}")
        self._log(f"Output    : {out_file}")

        self._require_file(env_file, label="env file")
        self._require_file(tmpl_file, label="template file")
        self._require_output_target(out_file)
        self._ensure_output_parent(out_file)
        envsubst = self._require_envsubst()

        env = self._load_env_file(env_file)

        tmp_file = out_file.with_suffix(out_file.suffix + ".tmp")

        self._log("Rendering Corefile via envsubst (atomic write)")
        try:
            with (
                tmpl_file.open("r", encoding="utf-8") as fin,
                tmp_file.open("w", encoding="utf-8") as fout,
            ):
                subprocess.check_call(
                    [envsubst],
                    stdin=fin,
                    stdout=fout,
                    env=env,
                    cwd=self.repo_root,
                )
        except OSError as exc:
            raise RuntimeError(
                f"Failed to write temporary Corefile: {tmp_file}"
            ) from exc

        if not tmp_file.exists():
            raise RuntimeError("envsubst did not produce an output file")

        size = tmp_file.stat().st_size
        if size == 0:
            raise RuntimeError(f"Rendered Corefile is empty: {tmp_file}")

        tmp_file.replace(out_file)
        self._log(f"Rendered successfully ({size} bytes)")

        if show_preview:
            self._preview(out_file, max_lines=int(preview_lines))

        return out_file
