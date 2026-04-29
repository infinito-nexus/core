import glob
import unittest
import yaml
from pathlib import Path


PROMETHEUS_APP_ID = "web-app-prometheus"


def _load_config(file_path: str) -> dict:
    return yaml.safe_load(Path(file_path).read_text(encoding="utf-8")) or {}


class TestPrometheusServicePresence(unittest.TestCase):
    """
    All web-app-* and web-svc-* roles (except web-app-prometheus itself) must
    declare the shared prometheus service in their services section:

        prometheus:
          enabled: true
          shared: true

    This enables the prometheus role to discover them via the
    service_should_load lookup plugin.
    """

    def _web_role_configs(self):
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        pattern = str(roles_dir / "*" / "meta" / "services.yml")
        return [
            p
            for p in sorted(glob.glob(pattern))
            if (
                Path(p).parts[-3].startswith(("web-app-", "web-svc-"))
                and Path(p).parts[-3] != PROMETHEUS_APP_ID
            )
        ]

    def test_all_web_roles_have_prometheus_service(self):
        """Every web-app-* and web-svc-* role must have services.prometheus."""
        configs = self._web_role_configs()
        self.assertTrue(configs, "No web-app-*/web-svc-* config/main.yml files found")

        errors = []
        for file_path in configs:
            role_name = Path(file_path).parts[-3]
            try:
                cfg = _load_config(file_path)
            except yaml.YAMLError as exc:
                errors.append(f"{role_name}: YAML parse error: {exc}")
                continue

            services = cfg or {}
            prom = services.get("prometheus")

            if prom is None:
                errors.append(
                    f"{role_name}: services.prometheus is missing. "
                    f"Add:\n    prometheus:\n      enabled: true\n      shared: true"
                )
                continue

            if not isinstance(prom, dict):
                errors.append(
                    f"{role_name}: services.prometheus must be a mapping, got {type(prom).__name__}"
                )
                continue

            if prom.get("enabled") is not True:
                errors.append(
                    f"{role_name}: services.prometheus.enabled must be true, "
                    f"got {prom.get('enabled')!r}"
                )

            if prom.get("shared") is not True:
                errors.append(
                    f"{role_name}: services.prometheus.shared must be true, "
                    f"got {prom.get('shared')!r}"
                )

        if errors:
            self.fail(
                f"Prometheus service configuration violations ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    def test_prometheus_role_has_image_config(self):
        """web-app-prometheus must define image, version, and name for its service."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        config_path = roles_dir / PROMETHEUS_APP_ID / "meta" / "services.yml"

        self.assertTrue(config_path.exists(), f"Missing: {config_path}")

        cfg = _load_config(str(config_path))
        svc = cfg or {}
        prom = svc.get("prometheus") or {}

        for key in ("image", "version", "name"):
            with self.subTest(key=key):
                self.assertIn(
                    key,
                    prom,
                    f"web-app-prometheus: services.prometheus.{key} is not set",
                )
                self.assertTrue(
                    prom[key],
                    f"web-app-prometheus: services.prometheus.{key} must not be empty",
                )

    def test_blackbox_exporter_image_is_pinned(self):
        """web-app-prometheus compose must use a pinned blackbox-exporter image, not :latest."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        compose_path = roles_dir / PROMETHEUS_APP_ID / "templates" / "compose.yml.j2"
        content = compose_path.read_text(encoding="utf-8")
        self.assertNotIn(
            "prom/blackbox-exporter:latest",
            content,
            "compose.yml.j2 must not use :latest for blackbox-exporter — pin to a version "
            "via config/main.yml (services.blackbox-exporter.version)",
        )
        self.assertIn(
            "BLACKBOX_VERSION",
            content,
            "compose.yml.j2 must reference BLACKBOX_VERSION for a reproducible image tag",
        )

    def test_alert_rules_mounted_in_prometheus_container(self):
        """compose.yml.j2 must bind-mount the alert rules file into the Prometheus container."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        compose_path = roles_dir / PROMETHEUS_APP_ID / "templates" / "compose.yml.j2"
        content = compose_path.read_text(encoding="utf-8")
        self.assertIn(
            "ALERT_RULES_CONFIG_HOST",
            content,
            "compose.yml.j2 must mount ALERT_RULES_CONFIG_HOST into the Prometheus container "
            "otherwise alert_rules.yml.j2 is rendered on disk but never loaded — all alerts are dead",
        )


class TestPrometheusNginxEndpoints(unittest.TestCase):
    """
    The shared nginx vhost template must expose /healthz/live and /healthz/ready.

    Two prometheus templates are conditionally included to follow SRP:
    - location.conf.j2  — log_by_lua_block for per-request metrics; on every app vhost
                          with services.prometheus.enabled = true
    - metricz.conf   — location = /metricz scrape endpoint; ONLY on the prometheus
                          domain (services.prometheus.name is set)
                          Restricting /metricz to one domain prevents leaking the full
                          metrics payload from every app's public hostname.
    """

    def _basic_conf_path(self):
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "sys-svc-proxy"
            / "templates"
            / "vhost"
            / "basic.conf.j2"
        )

    def _location_conf_path(self):
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "nginx"
            / "location.conf.j2"
        )

    def _metricz_conf_path(self):
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "files"
            / "nginx"
            / "metricz.conf"
        )

    def _healthz_conf_path(self):
        # Health-check locations live in web-app-prometheus/templates/nginx/healthz.conf.j2
        # — moved from sys-svc-proxy so all monitoring templates belong in one role (SRP).
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "nginx"
            / "healthz.conf.j2"
        )

    def test_basic_conf_has_health_endpoints(self):
        """healthz.conf.j2 must define /healthz/live and /healthz/ready (included by basic.conf.j2)."""
        conf_path = self._healthz_conf_path()
        self.assertTrue(conf_path.exists(), f"Missing: {conf_path}")
        content = conf_path.read_text(encoding="utf-8")

        for endpoint in ("/healthz/live", "/healthz/ready"):
            with self.subTest(endpoint=endpoint):
                self.assertIn(
                    f"location = {endpoint}",
                    content,
                    f"healthz.conf.j2 is missing 'location = {endpoint}'",
                )

    def test_basic_conf_live_probe_uses_lua(self):
        """healthz.conf.j2 /healthz/live must use Lua to check backend health, not a static return."""
        content = self._healthz_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "content_by_lua_block",
            content,
            "/healthz/live must use content_by_lua_block to check backend reachability",
        )
        self.assertNotIn(
            'return 200 "live',
            content,
            "/healthz/live must NOT be a static return 200 — it must check backend health",
        )

    def _prometheus_conf_path(self):
        # locations.conf.j2 is the single SPOT for all prometheus-related nginx includes.
        # basic.conf.j2 and synapse.conf.j2 both delegate to this shared include.
        # Moved from sys-svc-proxy to web-app-prometheus so all monitoring templates
        # are co-located in the monitoring role (SRP).
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "nginx"
            / "locations.conf.j2"
        )

    def test_basic_conf_delegates_prometheus_to_shared_include(self):
        """basic.conf.j2 must include prometheus.conf.j2 (the shared monitoring SPOT).

        All prometheus-related includes (healthz, location, metricz) live in
        prometheus.conf.j2 to eliminate duplication across vhost templates (DRY/SRP).
        """
        content = self._basic_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "roles/web-app-prometheus/templates/nginx/locations.conf.j2",
            content,
            "basic.conf.j2 must delegate prometheus monitoring to the shared "
            "roles/web-app-prometheus/templates/nginx/locations.conf.j2 include",
        )

    def test_prometheus_conf_includes_location_conf_for_all_prometheus_apps(self):
        """locations.conf.j2 must include location.conf.j2 and delegate the guard to
        the prometheus_integration_active lookup plugin.

        The outer guard was refactored from an inline Jinja2 condition into the
        reusable lookup('prometheus_integration_active') call. The actual logic
        (group_names + is_docker_service_enabled) lives in the lookup plugin and is
        covered by its own unit tests.
        """
        content = self._prometheus_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "roles/web-app-prometheus/templates/nginx/location.conf.j2",
            content,
            "locations.conf.j2 must include nginx/location.conf.j2 for prometheus-enabled apps",
        )
        self.assertIn(
            "lookup('prometheus_integration_active', application_id)",
            content,
            "locations.conf.j2 outer guard must call lookup('prometheus_integration_active', application_id) "
            "with application_id as term 0; applications is read from available_variables",
        )

    def test_prometheus_conf_includes_metricz_only_on_prometheus_domain(self):
        """locations.conf.j2 must include metricz.conf ONLY on the prometheus domain.

        /metricz must not be exposed on every app vhost — that would leak the full
        metrics payload from 60+ public hostnames. Only the prometheus domain serves it.
        """
        content = self._prometheus_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "roles/web-app-prometheus/files/nginx/metricz.conf",
            content,
            "locations.conf.j2 must include files/nginx/metricz.conf for the prometheus domain "
            "(no Jinja2 expressions — lives in files/, not templates/)",
        )
        # metricz is guarded by application_id == 'web-app-prometheus' so it only
        # appears on the prometheus domain vhost, not on every app vhost.
        self.assertIn(
            "application_id == 'web-app-prometheus'",
            content,
            "locations.conf.j2 must guard metricz.conf with application_id == 'web-app-prometheus' "
            "so /metricz only appears on the prometheus domain vhost",
        )

    def test_metricz_conf_has_metricz_endpoint(self):
        """/metricz must be defined in metricz.conf, not in location.conf.j2 or basic.conf.j2."""
        metricz_path = self._metricz_conf_path()
        self.assertTrue(metricz_path.exists(), f"Missing: {metricz_path}")
        content = metricz_path.read_text(encoding="utf-8")
        self.assertIn(
            "location = /metricz",
            content,
            "metricz.conf must define 'location = /metricz'",
        )
        # Verify it is NOT in location.conf.j2 (that would put it on every vhost)
        loc_content = self._location_conf_path().read_text(encoding="utf-8")
        self.assertNotIn(
            "location = /metricz",
            loc_content,
            "location = /metricz must NOT be in location.conf.j2 — it belongs only in "
            "metricz.conf (included only on the prometheus domain)",
        )

    def test_metricz_conf_exposes_stack_up_gauge(self):
        """/metricz must update the stack_up gauge before collecting metrics."""
        content = self._metricz_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "metric_stack_up",
            content,
            "/metricz in metricz.conf must set metric_stack_up gauge",
        )

    def test_metricz_conf_stack_up_checks_docker_health(self):
        """/metricz stack_up gauge must reflect Docker HEALTHCHECK, not just HTTP reachability."""
        content = self._metricz_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "health_containers",
            content,
            "/metricz in metricz.conf must check health_containers shared dict "
            "so metric_stack_up reflects Docker HEALTHCHECK state",
        )

    def test_location_conf_has_lua_metrics_collection(self):
        """location.conf.j2 must collect per-request metrics via log_by_lua_block."""
        content = self._location_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "log_by_lua_block",
            content,
            "location.conf.j2 must include log_by_lua_block for per-request nginx metrics",
        )

    def test_location_conf_metrics_have_app_label(self):
        """All nginx metrics in location.conf.j2 must carry the 'app' label (task AC: labels MUST include app)."""
        content = self._location_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "app_id",
            content,
            "location.conf.j2 must use ngx.var.app_id so all metrics carry the 'app' label "
            "(required by task AC: labels MUST include app, domain/vhost)",
        )

    def test_location_conf_collects_tls_metrics(self):
        """location.conf.j2 must collect TLS handshake metrics (task AC: TLS/HTTPS metrics if available)."""
        content = self._location_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "ssl_protocol",
            content,
            "location.conf.j2 must collect TLS metrics via ngx.var.ssl_protocol "
            "(task AC: TLS/HTTPS-related metrics if available)",
        )

    def test_basic_conf_sets_app_id_variable(self):
        """locations.conf.j2 must set $app_id so Lua blocks can attach the 'app' label.

        $app_id was moved from basic.conf.j2 into locations.conf.j2 so that it is set
        in a single place for all vhosts that include the prometheus monitoring block.
        """
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        locations_conf = (
            roles_dir / PROMETHEUS_APP_ID / "templates" / "nginx" / "locations.conf.j2"
        )
        content = locations_conf.read_text(encoding="utf-8")
        self.assertIn(
            "$app_id",
            content,
            "locations.conf.j2 must set the $app_id nginx variable (used by location.conf.j2 "
            "to attach the 'app' label to all metrics)",
        )

    def test_alertmanager_templates_exist(self):
        """web-app-prometheus must have alertmanager.yml.j2 and alert_rules.yml.j2."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        for template in ("alertmanager.yml.j2", "alert_rules.yml.j2"):
            with self.subTest(template=template):
                path = (
                    roles_dir
                    / PROMETHEUS_APP_ID
                    / "templates"
                    / "configuration"
                    / template
                )
                self.assertTrue(
                    path.exists(),
                    f"Missing alertmanager template: {path}",
                )

    def test_alertmanager_supports_telegram(self):
        """alertmanager.yml.j2 must support Telegram notifications (task AC: communication channels)."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        content = (
            roles_dir
            / PROMETHEUS_APP_ID
            / "templates"
            / "configuration"
            / "alertmanager.yml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "telegram_configs",
            content,
            "alertmanager.yml.j2 must include telegram_configs for Telegram notifications "
            "(task AC: Telegram or preferred Matrix Message)",
        )

    def test_alertmanager_supports_mattermost(self):
        """alertmanager.yml.j2 must support Mattermost webhook notifications (task AC: communication channels)."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        content = (
            roles_dir
            / PROMETHEUS_APP_ID
            / "templates"
            / "configuration"
            / "alertmanager.yml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ALERTMANAGER_MATTERMOST_WEBHOOK_URL",
            content,
            "alertmanager.yml.j2 must include Mattermost webhook config (task AC: Mattermost notification)",
        )

    def test_alert_rules_has_communication_channel_rule(self):
        """alert_rules.yml.j2 must have a rule targeting communication-channel apps specifically.

        The task AC requires alert rules for communication channels (Mattermost, Matrix, Mailu).
        Generic AppDown alone is insufficient — a dedicated rule makes intent explicit and allows
        different routing/escalation for communication-critical apps.

        Channel list is discovered dynamically via the active_alertmanager_channels lookup plugin.
        Each app self-declares communication.channel: true in its own config (SPOT per app —
        no hardcoded list anywhere).
        """
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        content = (
            roles_dir
            / PROMETHEUS_APP_ID
            / "templates"
            / "configuration"
            / "alert_rules.yml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "CommunicationChannelDown",
            content,
            "alert_rules.yml.j2 must define a CommunicationChannelDown alert rule "
            "(task AC: alert rules for communication channels — Mattermost, Matrix, Mailu)",
        )
        # Channel list is discovered by the plugin, not read from a hardcoded config key.
        self.assertIn(
            "active_alertmanager_channels",
            content,
            "CommunicationChannelDown must use the active_alertmanager_channels lookup plugin "
            "for dynamic channel discovery (no hardcoded list)",
        )
        # Each communication-channel app self-declares
        # services.prometheus.communication.channel: true.
        # Mailu is excluded — it is an email server, not a webhook channel.
        for app_id in ("web-app-mattermost", "web-app-matrix"):
            with self.subTest(app_id=app_id):
                cfg = _load_config(str(roles_dir / app_id / "meta" / "services.yml"))
                prometheus_cfg = cfg.get("prometheus", {})
                self.assertTrue(
                    (prometheus_cfg.get("communication") or {}).get("channel") is True,
                    f"{app_id}/meta/services.yml must declare "
                    f"services.prometheus.communication.channel: true "
                    f"so the active_alertmanager_channels plugin discovers it",
                )

    def test_blackbox_tls_is_templated(self):
        """blackbox.yml.j2 must use TLS_ENABLED to set insecure_skip_verify, not hardcode false.

        Hardcoding insecure_skip_verify: false breaks all blackbox probes in
        development/staging environments that use self-signed TLS certificates.
        """
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        content = (
            roles_dir
            / PROMETHEUS_APP_ID
            / "templates"
            / "configuration"
            / "blackbox.yml.j2"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "TLS_ENABLED",
            content,
            "blackbox.yml.j2 must template insecure_skip_verify from TLS_ENABLED "
            "(hardcoding false breaks self-signed TLS environments)",
        )
        self.assertNotIn(
            "insecure_skip_verify: false",
            content,
            "blackbox.yml.j2 must not hardcode insecure_skip_verify: false",
        )


class TestDockerHealthCheck(unittest.TestCase):
    """
    /healthz/live must check Docker container health in addition to HTTP reachability.
    HTTP-reachability alone is insufficient — a container can be "running" in Docker
    while its HEALTHCHECK has flipped to "unhealthy".
    """

    def _nginx_conf_path(self):
        # Prometheus Lua blocks (lua_shared_dict, init_worker, Docker health timer)
        # live in web-app-prometheus/templates/nginx/prometheus.conf.j2 — monitoring
        # config belongs in the monitoring role, not in sys-svc-webserver-core (SRP).
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "nginx"
            / "prometheus.conf.j2"
        )

    def _basic_conf_path(self):
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "sys-svc-proxy"
            / "templates"
            / "vhost"
            / "basic.conf.j2"
        )

    def _healthz_conf_path(self):
        # Health-check locations live in web-app-prometheus/templates/nginx/healthz.conf.j2
        # — moved from sys-svc-proxy so all monitoring templates belong in one role (SRP).
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "nginx"
            / "healthz.conf.j2"
        )

    def _openresty_compose_path(self):
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "svc-prx-openresty"
            / "templates"
            / "compose.yml.j2"
        )

    def test_nginx_conf_has_health_containers_dict(self):
        """prometheus.conf.j2 must declare lua_shared_dict health_containers for Docker state caching."""
        content = self._nginx_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "lua_shared_dict health_containers",
            content,
            "prometheus.conf.j2 must declare lua_shared_dict health_containers "
            "(used by /healthz/live to cache Docker container health state)",
        )

    def test_nginx_conf_polls_docker_socket(self):
        """prometheus.conf.j2 must poll the Docker Unix socket to populate health_containers."""
        content = self._nginx_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "docker.sock",
            content,
            "prometheus.conf.j2 must connect to /var/run/docker.sock to query container health",
        )
        self.assertIn(
            "poll_docker_health",
            content,
            "prometheus.conf.j2 must define a poll_docker_health timer function",
        )

    def test_nginx_conf_timer_runs_at_startup_and_periodically(self):
        """prometheus.conf.j2 must seed the dict immediately (timer.at) and refresh periodically (timer.every)."""
        content = self._nginx_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "ngx.timer.at",
            content,
            "prometheus.conf.j2 must use ngx.timer.at(0, ...) to seed health_containers at startup",
        )
        self.assertIn(
            "ngx.timer.every",
            content,
            "prometheus.conf.j2 must use ngx.timer.every to refresh health_containers periodically",
        )

    def test_basic_conf_has_container_name_variable(self):
        """locations.conf.j2 must set $container_name so /healthz/live can look up Docker state."""
        # $container_name was moved from basic.conf.j2 into locations.conf.j2 so every
        # custom vhost template (synapse.conf.j2, etc.) gets it automatically.
        locations_path = (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "nginx"
            / "locations.conf.j2"
        )
        content = locations_path.read_text(encoding="utf-8")
        self.assertIn(
            "$container_name",
            content,
            "locations.conf.j2 must set the $container_name nginx variable "
            "(used by /healthz/live to consult the health_containers shared dict)",
        )

    def test_basic_conf_live_probe_checks_docker_health(self):
        """/healthz/live must consult health_containers before the HTTP sub-request."""
        # Health-check locations live in healthz.conf.j2 (extracted from basic.conf.j2);
        # basic.conf.j2 includes it conditionally.
        content = self._healthz_conf_path().read_text(encoding="utf-8")
        self.assertIn(
            "health_containers",
            content,
            "/healthz/live in healthz.conf.j2 must read health_containers shared dict "
            "(Docker health alone is insufficient — HTTP sub-request is also required)",
        )

    def test_openresty_compose_mounts_docker_socket(self):
        """OpenResty compose must mount /var/run/docker.sock read-only for the Lua health timer."""
        content = self._openresty_compose_path().read_text(encoding="utf-8")
        self.assertIn(
            "/var/run/docker.sock",
            content,
            "svc-prx-openresty compose.yml.j2 must mount /var/run/docker.sock:ro "
            "so the Lua background timer can query Docker container health",
        )


class TestNativeAppMetrics(unittest.TestCase):
    """
    Applications that provide native Prometheus metrics MUST have a scrape job
    in prometheus.yml.j2 (task AC: expose /metrics for apps that support it).
    The jobs are guarded by native_metrics.enabled in each app's own config
    (NOT by services.prometheus.enabled which is the nginx integration flag).
    """

    def _prometheus_yml_path(self):
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / "web-app-prometheus"
            / "templates"
            / "configuration"
            / "prometheus.yml.j2"
        )

    def _scrape_fragment_path(self, app_id: str) -> "Path":
        return (
            Path(__file__).resolve().parent.parent.parent
            / "roles"
            / app_id
            / "templates"
            / "prometheus.yml.j2"
        )

    def test_prometheus_yml_uses_native_metrics_apps_lookup(self):
        """prometheus.yml.j2 must use the native_metrics_apps lookup to auto-discover scrape targets.

        Hardcoding per-app {% if %} blocks in prometheus.yml.j2 violates DRY —
        every new app requires editing the prometheus role. The factory pattern
        uses native_metrics_apps lookup + per-app prometheus.yml.j2 fragments.
        """
        content = self._prometheus_yml_path().read_text(encoding="utf-8")
        self.assertIn(
            "native_metrics_apps",
            content,
            "prometheus.yml.j2 must use the native_metrics_apps lookup plugin "
            "to auto-discover apps with native metrics (no hardcoded per-app blocks)",
        )

    def test_gitea_has_scrape_fragment(self):
        """web-app-gitea must have a prometheus.yml.j2 fragment with a 'gitea' job."""
        path = self._scrape_fragment_path("web-app-gitea")
        self.assertTrue(
            path.exists(),
            "web-app-gitea must have roles/web-app-gitea/templates/prometheus.yml.j2 "
            "(task AC: apps that support metrics MUST expose /metrics)",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn(
            'job_name: "gitea"',
            content,
            'web-app-gitea/templates/prometheus.yml.j2 must define job_name: "gitea"',
        )

    def test_mattermost_has_scrape_fragment(self):
        """web-app-mattermost must have a prometheus.yml.j2 fragment with a 'mattermost' job."""
        path = self._scrape_fragment_path("web-app-mattermost")
        self.assertTrue(
            path.exists(),
            "web-app-mattermost must have roles/web-app-mattermost/templates/prometheus.yml.j2 "
            "(task AC: Mattermost supports Prometheus metrics via MM_METRICSSETTINGS_ENABLE=true)",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn(
            'job_name: "mattermost"',
            content,
            'web-app-mattermost/templates/prometheus.yml.j2 must define job_name: "mattermost"',
        )

    def test_matrix_has_scrape_fragment(self):
        """web-app-matrix must have a prometheus.yml.j2 fragment with a 'matrix-synapse' job."""
        path = self._scrape_fragment_path("web-app-matrix")
        self.assertTrue(
            path.exists(),
            "web-app-matrix must have roles/web-app-matrix/templates/prometheus.yml.j2 "
            "(task AC: Matrix/Synapse supports Prometheus metrics via enable_metrics: true)",
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn(
            'job_name: "matrix-synapse"',
            content,
            'web-app-matrix/templates/prometheus.yml.j2 must define job_name: "matrix-synapse"',
        )

    def test_native_metrics_guard_uses_native_metrics_flag(self):
        """native_metrics_apps lookup must filter by native_metrics.enabled, not the nginx integration flag.

        services.prometheus.enabled is the nginx monitoring integration flag —
        it controls whether log_by_lua_block is added to the vhost. The lookup plugin
        must use native_metrics.enabled so only apps with an active metrics endpoint
        get a scrape job (otherwise all 70+ apps appear as DOWN targets in Prometheus).
        """
        plugin_path = (
            Path(__file__).resolve().parent.parent.parent
            / "plugins"
            / "lookup"
            / "native_metrics_apps.py"
        )
        content = plugin_path.read_text(encoding="utf-8")
        self.assertIn(
            "native_metrics.enabled",
            content,
            "native_metrics_apps lookup plugin must filter on native_metrics.enabled "
            "from each app's own config, not on services.prometheus.enabled",
        )

    def test_native_metrics_apps_have_enabled_flag_in_config(self):
        """Apps with native metrics support must have native_metrics.enabled in their config."""
        roles_dir = Path(__file__).resolve().parent.parent.parent / "roles"
        for app_id in ("web-app-gitea", "web-app-mattermost", "web-app-matrix"):
            with self.subTest(app_id=app_id):
                cfg = _load_config(str(roles_dir / app_id / "meta" / "services.yml"))
                native_metrics_cfg = cfg.get("prometheus", {}).get("native_metrics", {})
                self.assertTrue(
                    bool(native_metrics_cfg),
                    f"{app_id}/meta/services.yml must have a "
                    f"services.prometheus.native_metrics section "
                    f"(guards the Prometheus scrape job; set enabled: true in inventory to activate)",
                )
                self.assertIn(
                    "enabled",
                    native_metrics_cfg,
                    f"{app_id}/meta/services.yml services.prometheus.native_metrics "
                    f"must have an 'enabled' key",
                )

    def test_gitea_scrape_fragment_uses_metrics_path(self):
        """The Gitea scrape fragment must use metrics_path: /metrics."""
        content = self._scrape_fragment_path("web-app-gitea").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "metrics_path: /metrics",
            content,
            "web-app-gitea/templates/prometheus.yml.j2 must set metrics_path: /metrics",
        )

    def test_matrix_scrape_fragment_uses_synapse_metrics_path(self):
        """The Synapse scrape fragment must use the correct /_synapse/metrics path."""
        content = self._scrape_fragment_path("web-app-matrix").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "metrics_path: /_synapse/metrics",
            content,
            "web-app-matrix/templates/prometheus.yml.j2 must set metrics_path: /_synapse/metrics",
        )


if __name__ == "__main__":
    unittest.main()
