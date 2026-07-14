"""Handler registry. ``ORDERED_HANDLERS`` is iterated by ``build_env()``.

Each handler module exposes ``apply(eb, ctx) -> None``. Cross-handler
data flows via :class:`utils.env.builder.EnvBuilder`; handlers must not
import each other.
"""

from __future__ import annotations

from . import (
    gha_passthrough,
    github_repository_owner,
    nix_config,
    passthrough,
)
from .infinito import (
    ca_cert_host,
    container,
    docker_volume,
    image,
    image_repository,
    inventory,
    is_wsl2,
    outer_network_mtu,
    parent_image,
    playwright_reports_base_dir,
    playwright_stage_base_dir,
    pull_policy,
    registry_cache_max_size,
    rescue_diagnostics_dir,
    running_on_act,
    running_on_github,
    swarm_nfs_export_base,
    swarm_nfs_state_path,
    variant_bundle_size,
    worker_cpu,
    worker_fetch,
)
from .infinito.dir import backups as dir_backups
from .infinito.dir import secrets as dir_secrets
from .infinito.dir import var_lib as dir_var_lib
from .infinito.package_cache import admin_password as package_cache_admin_password
from .infinito.package_cache import blobstore_max as package_cache_blobstore_max
from .infinito.package_cache import direct_mem as package_cache_direct_mem
from .infinito.package_cache import heap as package_cache_heap

ORDERED_HANDLERS = [
    passthrough,
    dir_var_lib,
    dir_backups,
    dir_secrets,
    rescue_diagnostics_dir,
    swarm_nfs_export_base,
    swarm_nfs_state_path,
    playwright_reports_base_dir,
    playwright_stage_base_dir,
    worker_cpu,
    worker_fetch,
    container,
    running_on_act,
    running_on_github,
    variant_bundle_size,
    is_wsl2,
    ca_cert_host,
    outer_network_mtu,
    inventory,
    gha_passthrough,
    pull_policy,
    docker_volume,
    github_repository_owner,
    image_repository,
    image,
    parent_image,
    nix_config,
    registry_cache_max_size,
    package_cache_heap,
    package_cache_direct_mem,
    package_cache_blobstore_max,
    package_cache_admin_password,
]

PASSTHROUGH_STATIC_KEYS = passthrough.STATIC_KEYS
GHA_STATIC_KEYS = gha_passthrough.STATIC_KEYS
