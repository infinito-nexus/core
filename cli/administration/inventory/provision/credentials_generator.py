from __future__ import annotations

import concurrent.futures
import subprocess
import sys
from typing import TYPE_CHECKING

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .role_resolver import resolve_role_path

if TYPE_CHECKING:
    from pathlib import Path


def _fatal(msg: str) -> None:
    raise SystemExit(f"[FATAL] {msg}")


def _ensure_ruamel_map(node: CommentedMap, key: str) -> CommentedMap:
    if key not in node or not isinstance(node.get(key), CommentedMap):
        node[key] = CommentedMap()
    return node[key]


def _generate_credentials_snippet_for_app(
    app_id: str,
    roles_dir: Path,
    host_vars_file: Path,
    vault_password_file: Path,
    project_root: Path,
    env: dict[str, str] | None,
    variant: int | None = None,
) -> CommentedMap | None:
    role_path = resolve_role_path(app_id, roles_dir, project_root, env=env)
    if role_path is None:
        return None

    cmd = [
        # Use current interpreter so utils + deps match the runtime
        sys.executable,
        "-m",
        "cli.administration.inventory.credentials",
        "--role-path",
        str(role_path),
        "--inventory-file",
        str(host_vars_file),
        "--vault-password-file",
        str(vault_password_file),
        "--snippet",
        "--allow-empty-plain",
    ]
    if variant is not None:
        cmd += ["--variant", str(variant)]

    result = subprocess.run(cmd, text=True, capture_output=True, env=env, check=False)
    if result.returncode != 0:
        _fatal(
            f"Command failed ({result.returncode}): {' '.join(cmd)}\n"
            f"STDOUT:\n{result.stdout or ''}\nSTDERR:\n{result.stderr or ''}"
        )

    snippet_text = (result.stdout or "").strip()
    if not snippet_text:
        return None

    yaml_rt = YAML(typ="rt")
    try:
        data = yaml_rt.load(snippet_text)
    except Exception as exc:
        raise SystemExit(
            f"Failed to parse credentials snippet for {app_id}: {exc}"
        ) from exc

    if data is None:
        return None
    if not isinstance(data, CommentedMap):
        cm = CommentedMap()
        for k, v in dict(data).items():
            cm[k] = v
        return cm

    return data


def generate_credentials_for_roles(
    application_ids: list[str],
    roles_dir: Path,
    host_vars_file: Path,
    vault_password_file: Path,
    project_root: Path,
    env: dict[str, str] | None,
    workers: int = 4,
    app_variants: dict[str, int] | None = None,
) -> None:
    if not application_ids:
        return

    max_workers = max(1, workers)
    snippets: list[CommentedMap] = []
    variants = app_variants or {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_app: dict[concurrent.futures.Future, str] = {}
        for app_id in application_ids:
            future = executor.submit(
                _generate_credentials_snippet_for_app,
                app_id,
                roles_dir,
                host_vars_file,
                vault_password_file,
                project_root,
                env,
                variants.get(app_id),
            )
            future_to_app[future] = app_id

        for future in concurrent.futures.as_completed(future_to_app):
            app_id = future_to_app[future]
            try:
                snippet = future.result()
            except Exception as exc:
                _fatal(f"Worker for {app_id} failed with exception: {exc}")
            if snippet is not None:
                snippets.append(snippet)

    if not snippets:
        return

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True

    if host_vars_file.exists():
        with host_vars_file.open("r", encoding="utf-8") as f:
            doc = yaml_rt.load(f)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()

    if not isinstance(doc, CommentedMap):
        tmp = CommentedMap()
        for k, v in dict(doc).items():
            tmp[k] = v
        doc = tmp

    for snippet in snippets:
        apps_snip = snippet.get("applications", {}) or {}
        if isinstance(apps_snip, dict):
            apps_doc = _ensure_ruamel_map(doc, "applications")
            for app_id, app_block_snip in apps_snip.items():
                if not isinstance(app_block_snip, dict):
                    continue
                app_doc = _ensure_ruamel_map(apps_doc, app_id)
                creds_doc = _ensure_ruamel_map(app_doc, "credentials")

                creds_snip = app_block_snip.get("credentials", {}) or {}
                if not isinstance(creds_snip, dict):
                    continue

                for key, val in creds_snip.items():
                    if key not in creds_doc or (
                        creds_doc.get(key) == "" and val not in ("", None)
                    ):
                        creds_doc[key] = val

        if (
            "ansible_become_password" in snippet
            and "ansible_become_password" not in doc
        ):
            doc["ansible_become_password"] = snippet["ansible_become_password"]

    host_vars_file.parent.mkdir(parents=True, exist_ok=True)
    with host_vars_file.open("w", encoding="utf-8") as f:
        yaml_rt.dump(doc, f)
