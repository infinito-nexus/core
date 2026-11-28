"""Handler registry. ``ORDERED_HANDLERS`` is iterated by ``build_env()``.

Each handler module exposes ``apply(eb, ctx) -> None``. Cross-handler
data flows via :class:`utils.env.context.EnvBuilder`; handlers must not
import each other.
"""

from __future__ import annotations

from . import (
    act_platform_image,
    docker_platform,
    gha_passthrough,
    github_repository_owner,
    nix_config,
    passthrough,
)
from .infinito import (
    build,
    container,
    distro,
    distros,
    domain,
    ghcr_mirror,
    git_identity,
    image,
    image_repository,
    infra,
    inventory,
    is_wsl2,
    lifecycles,
    lint_runner,
    memory,
    outer_network_mtu,
    parent_image,
    pull_policy,
    tor_socks_port,
)
from .infinito import (
    ip_range as ip_range,
)
from .infinito import (
    target_ip as target_ip,
)
from .infinito.ca import bundle_candidates as ca_bundle_candidates
from .infinito.ca import cert_host as ca_cert_host
from .infinito.cache import artefact_base as cache_artefact_base
from .infinito.cache import hosts as cache_hosts
from .infinito.cache import http_hosts as cache_http_hosts
from .infinito.cache import paths as cache_paths
from .infinito.cache import pin as cache_pin
from .infinito.cache import registries as cache_registries
from .infinito.cache import stack as cache_stack
from .infinito.cache import tls as cache_tls
from .infinito.cache import upstreams as cache_upstreams
from .infinito.cache.host import pacman_path as cache_host_pacman_path
from .infinito.cache.host import sync as cache_host_sync
from .infinito.dir import backups as dir_backups
from .infinito.dir import secrets as dir_secrets
from .infinito.dir import var_lib as dir_var_lib
from .infinito.docker import embedded_dns as docker_embedded_dns
from .infinito.docker import volume as docker_volume
from .infinito.fork import account as fork_account
from .infinito.fork import repository_url as fork_repository_url
from .infinito.gpu import count as gpu_count
from .infinito.gpu import only_tests as gpu_only_tests
from .infinito.i18n import tuning as i18n_tuning
from .infinito.package_cache import admin_password as package_cache_admin_password
from .infinito.package_cache import direct_mem as package_cache_direct_mem
from .infinito.package_cache import heap as package_cache_heap
from .infinito.package_cache import url as package_cache_url
from .infinito.playwright import reports_base_dir as playwright_reports_base_dir
from .infinito.playwright import stage_base_dir as playwright_stage_base_dir
from .infinito.rescue import diagnostics_dir as rescue_diagnostics_dir
from .infinito.rescue import dns53_sampler_log as rescue_dns53_sampler_log
from .infinito.rescue import local_dumps_dir as rescue_local_dumps_dir
from .infinito.running_on import act as running_on_act
from .infinito.running_on import github as running_on_github
from .infinito.swarm_nfs import export_base as swarm_nfs_export_base
from .infinito.swarm_nfs import state_path as swarm_nfs_state_path
from .infinito.tools import idle as tools_idle
from .infinito.tools import libretranslate as tools_libretranslate
from .infinito.tools import litellm as tools_litellm
from .infinito.tools import models as tools_models
from .infinito.tools import s1 as tools_s1
from .infinito.tools import translate as tools_translate
from .infinito.worker import cpu as worker_cpu
from .infinito.worker import fetch as worker_fetch

ORDERED_HANDLERS = [
    passthrough,
    infra,
    distro,
    docker_platform,
    distros,
    lifecycles,
    dir_var_lib,
    dir_backups,
    dir_secrets,
    rescue_diagnostics_dir,
    rescue_dns53_sampler_log,
    rescue_local_dumps_dir,
    swarm_nfs_export_base,
    swarm_nfs_state_path,
    playwright_reports_base_dir,
    playwright_stage_base_dir,
    worker_cpu,
    worker_fetch,
    container,
    domain,
    running_on_act,
    running_on_github,
    cache_pin,
    cache_hosts,
    cache_http_hosts,
    cache_tls,
    cache_upstreams,
    cache_registries,
    cache_stack,
    cache_artefact_base,
    cache_paths,
    cache_host_pacman_path,
    cache_host_sync,
    ghcr_mirror,
    tor_socks_port,
    is_wsl2,
    ca_bundle_candidates,
    ca_cert_host,
    outer_network_mtu,
    memory,
    inventory,
    gha_passthrough,
    pull_policy,
    build,
    lint_runner,
    docker_embedded_dns,
    docker_volume,
    github_repository_owner,
    image_repository,
    image,
    parent_image,
    act_platform_image,
    fork_account,
    fork_repository_url,
    nix_config,
    git_identity,
    gpu_count,
    gpu_only_tests,
    tools_idle,
    tools_libretranslate,
    tools_litellm,
    tools_models,
    tools_s1,
    tools_translate,
    i18n_tuning,
    package_cache_heap,
    package_cache_direct_mem,
    package_cache_admin_password,
    package_cache_url,
]

PASSTHROUGH_STATIC_KEYS = passthrough.STATIC_KEYS + passthrough.PER_CALL_KEYS
GHA_STATIC_KEYS = gha_passthrough.STATIC_KEYS
