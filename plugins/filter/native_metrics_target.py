from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.entity_name_utils import get_entity_name


def native_metrics_target(app_id: str, applications: dict) -> str:
    """Return the container-to-container Prometheus scrape target for a native-metrics app.

    Prometheus connects to the app's Docker network (declared in prometheus's
    compose.yml.j2 via the native_metrics_apps loop) and scrapes by container
    name and internal port — no host port binding required, no nginx/OAuth2 in
    the path.

    Usage in a per-app prometheus.yml.j2 fragment:
      targets: ["{{ native_prometheus_application_id | native_metrics_target(lookup('applications')) }}"]

    When the service key differs from the app's entity name (e.g. matrix
    uses service key "synapse"), set services.prometheus.native_metrics.service_key
    in the app's meta/services.yml to override.
    """
    app_conf = applications.get(app_id, {})
    services = app_conf.get("services", {}) if isinstance(app_conf, dict) else {}
    native_metrics_conf = (
        services.get("prometheus", {}) if isinstance(services, dict) else {}
    ).get("native_metrics", {})
    service_key = native_metrics_conf.get("service_key") or get_entity_name(app_id)

    container = (
        services.get(service_key, {}).get("name")
        if isinstance(services, dict)
        else None
    )
    if not container:
        raise AnsibleFilterError(
            f"native_metrics_target: no services.{service_key}.name for '{app_id}'"
        )

    port = native_metrics_conf.get("port")
    if port is None:
        raise AnsibleFilterError(
            f"native_metrics_target: no services.prometheus.native_metrics.port for '{app_id}'"
        )

    return f"{container}:{port}"


class FilterModule:
    def filters(self):
        return {"native_metrics_target": native_metrics_target}
