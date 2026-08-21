"""Lookup `container_healthcheck`: emit a service's healthcheck block.

Single SPOT for every container probe in the repo. The service name is the
only positional argument, everything else comes from the service's
``meta/services.yml`` entry:

    myservice:
      ports:
        internal:
          http: 8080
      healthcheck:
        flavor: curl
        path: health/ready
        start_period: 20m

``flavor`` picks the probe shape (see utils/docker/healthcheck/); each
flavor brings its own interval, timeout, retries and start_period, and any
of those may be overridden next to it. Without a ``flavor`` the entry must
carry an explicit ``test`` argv. ``port_key`` selects another entry below
``ports.internal`` for services that expose their probe on a second port.

Examples:

    {{ lookup('container_healthcheck', service_name) | indent(4) }}
    {{ lookup('container_healthcheck', service_name, samples=3) | indent(4) }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.docker.healthcheck.compose import build, known_flavors, resolve_flavors
from utils.docker.healthcheck.prefixes import PREFIXES
from utils.docker.healthcheck.probes import PROBES


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or not str(terms[0] or "").strip():
            raise AnsibleError(
                "container_healthcheck: pass the service name as the first argument, "
                "e.g. lookup('container_healthcheck', service_name)"
            )
        service = str(terms[0]).strip()

        self._vars = (
            variables or getattr(self._templar, "available_variables", {}) or {}
        )
        self._application_id = self._render(
            kwargs.get("application_id") or self._vars.get("application_id")
        )
        if not self._application_id:
            raise AnsibleError(
                "container_healthcheck: no application_id in the play vars; "
                "pass application_id= explicitly"
            )

        config = self._config(f"services.{service}.healthcheck", {})
        config = config if isinstance(config, dict) else {}
        declared = config.get("flavor", "")
        flavor: str | list[str] = (
            [str(name).strip() for name in declared if str(name).strip()]
            if isinstance(declared, list)
            else str(declared or "").strip()
        )
        where = f"'{self._application_id}' service '{service}'"

        if not flavor and not config.get("test"):
            raise AnsibleError(
                f"container_healthcheck: {where} declares no healthcheck.flavor, so "
                f"healthcheck.test is required. Known flavors: {known_flavors()}."
            )
        unknown = [
            name
            for name in (resolve_flavors(flavor) if flavor else [])
            if name not in PROBES and name not in PREFIXES
        ]
        if unknown:
            raise AnsibleError(
                f"container_healthcheck: unknown flavor '{unknown[0]}' for {where}. "
                f"Known flavors: {known_flavors()}."
            )

        return [build(flavor, config, **self._context(service, flavor, config, kwargs))]

    def _context(
        self,
        service: str,
        flavor: str,
        config: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Collect what the chosen flavor's probe asks for.

        Args:
            service: service key inside the application's services.yml.
            flavor: the selected probe shape, empty for an explicit test.
            config: that service's healthcheck entry.
            kwargs: the call site's keyword arguments.
        """
        hostname = self._render(config.get("hostname"))
        port_key = str(config.get("port_key", "http") or "http")
        context = {
            "test": config.get("test"),
            "port": self._config(f"services.{service}.ports.internal.{port_key}", "")
            or "",
            "path": str(config.get("path", "") or ""),
            "hostname": str(hostname) if hostname else None,
            "samples": int(kwargs.get("samples", config.get("samples", 1)) or 1),
        }
        if "msmtp" in resolve_flavors(flavor):
            context.update(
                email_enabled=bool(self._config("services.email.enabled", False)),
                domain=self._lookup("domain", self._application_id),
                blackhole=(self._lookup("users", "blackhole") or {}).get("email", ""),
            )
        return context

    def _render(self, value: Any) -> Any:
        """Template a value read straight out of the play vars.

        Args:
            value: raw var value; ``include_role: vars:`` hands these over
                unrendered, e.g. ``application_id: "{{ sys_stk_full_application_id }}"``.

        Raises:
            AnsibleError: the value stayed a template. ansible-core only
                renders strings tagged trusted and returns the rest verbatim,
                which would bake ``{{ ... }}`` into the compose file.
        """
        templar = getattr(self, "_templar", None)
        if templar is None or not isinstance(value, str) or "{{" not in value:
            return value
        rendered = templar.template(value)
        if isinstance(rendered, str) and "{{" in rendered:
            raise AnsibleError(
                f"container_healthcheck: '{value}' did not render; it reached the "
                "lookup untrusted as a template."
            )
        return rendered

    def _config(self, path: str, default: Any) -> Any:
        """Read one services.yml value through the config SPOT, templated.

        Args:
            path: dotted config path below the application.
            default: value returned when the path is absent.
        """
        return self._lookup("config", self._application_id, path, default)

    def _lookup(self, name: str, *terms: Any) -> Any:
        return lookup_loader.get(
            name, loader=self._loader, templar=getattr(self, "_templar", None)
        ).run(list(terms), variables=self._vars)[0]
