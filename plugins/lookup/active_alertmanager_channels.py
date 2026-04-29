from __future__ import annotations

from typing import Any, Dict, List, Optional

from ansible.plugins.lookup import LookupBase

from utils.applications.config import get as get_app_conf
from utils.cache.applications import get_merged_applications


class LookupModule(LookupBase):
    """
    Return a sorted list of communication-channel app IDs that are deployed on
    this host.

    Deployment check  : app ID must appear in group_names.
    Channel check     : app must declare services.prometheus.communication.channel: true
                        in its own role config — the self-declaration pattern (SPOT per app,
                        no hardcoded list anywhere).

    Usage in a template:
      {% set _comm_channels = lookup('active_alertmanager_channels') %}

    'applications' is obtained via get_merged_applications — the same merged view
    that backs lookup('applications').
    """

    def run(
        self,
        terms: List[Any],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[List[str]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        group_names: List[str] = vars_.get("group_names", [])

        result: List[str] = []
        for app_id in sorted(applications.keys()):
            if app_id not in group_names:
                continue

            is_channel = get_app_conf(
                applications=applications,
                application_id=app_id,
                config_path="services.prometheus.communication.channel",
                strict=False,
                default=False,
                skip_missing_app=True,
            )
            if is_channel:
                result.append(app_id)

        return [result]
