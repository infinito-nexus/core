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
    pull_policy,
    registry_cache_max_size,
    rescue_diagnostics_dir,
)
from .infinito.dir import backups as dir_backups
from .infinito.dir import secrets as dir_secrets
from .infinito.dir import var_lib as dir_var_lib
from .infinito.fork import account as fork_account
from .infinito.fork import repository_url as fork_repository_url
from .infinito.package_cache import admin_password as package_cache_admin_password
from .infinito.package_cache import blobstore_max as package_cache_blobstore_max
from .infinito.package_cache import direct_mem as package_cache_direct_mem
from .infinito.package_cache import heap as package_cache_heap
from .infinito.playwright import reports_base_dir as playwright_reports_base_dir
from .infinito.playwright import stage_base_dir as playwright_stage_base_dir
from .infinito.running_on import act as running_on_act
from .infinito.running_on import github as running_on_github
from .infinito.swarm_nfs import export_base as swarm_nfs_export_base
from .infinito.swarm_nfs import state_path as swarm_nfs_state_path
from .infinito.variant_bundle import size as variant_bundle_size
from .infinito.worker import cpu as worker_cpu
from .infinito.worker import fetch as worker_fetch

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
    fork_account,
    fork_repository_url,
    nix_config,
    registry_cache_max_size,
    package_cache_heap,
    package_cache_direct_mem,
    package_cache_blobstore_max,
    package_cache_admin_password,
]

PASSTHROUGH_STATIC_KEYS = passthrough.STATIC_KEYS
GHA_STATIC_KEYS = gha_passthrough.STATIC_KEYS
