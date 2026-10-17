from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.roles.applications.services.wazuh import (
    PROVIDER_ENTITY,
    SELFTEST_TAG,
    decoder_name,
)
from utils.roles.entity.name import get_entity_name

RULESET_KINDS = ("decoders", "rules")


class LookupModule(LookupBase):
    """Return the Wazuh ruleset of every inventory role that opts in.

    A role opts in through ``services.wazuh.enabled``, the same flag
    ``sys-svc-container/templates/base.yml.j2`` reads for the journald tag.
    The Wazuh role itself is skipped, because its ``wazuh`` entry is the
    provider, not an opt-in.

    Returns:
        ``{selftest, entities, files}``. ``selftest`` is ``{program, decoder}``
        of the reserved self-test tag. ``entities`` is
        ``[{entity, program, decoder, rule_block}]`` sorted by ``entity``, one
        per opted-in role, tag-only roles included: ``program`` is the
        journald tag and ``decoder`` its base parent decoder.
        ``files`` is ``[{src, kind, name}]`` sorted by ``kind`` and ``name``:
        ``src`` is ``roles/<role>/files/wazuh/<kind>.xml``, ``kind`` is
        ``decoders`` or ``rules``, and ``name`` is ``<entity>_<kind>.xml``.
        A role without one or both files contributes only the files it has.

    Raises:
        AnsibleError: two opted-in roles share an entity name, so their
            files would overwrite each other, or an opted-in role sets no
            ``services.wazuh.rule_block``.
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=vars_)[0]
        config = lookup_loader.get("config", loader=self._loader, templar=templar)

        groups = vars_.get("groups") or {}
        inventory_roles = sorted(
            name for name, hosts in groups.items() if hosts and name in applications
        )

        owners: dict[str, str] = {}
        entities: list[dict[str, Any]] = []
        files: list[dict[str, str]] = []
        for role in inventory_roles:
            entity = get_entity_name(role)
            if entity == PROVIDER_ENTITY:
                continue
            enabled = config.run(
                [role, "services.wazuh.enabled", False], variables=vars_
            )[0]
            if not bool(enabled):
                continue
            if entity in owners:
                raise AnsibleError(
                    f"wazuh_ruleset: roles '{owners[entity]}' and '{role}' share "
                    f"the entity name '{entity}', so their Wazuh rule files collide."
                )
            owners[entity] = role
            rule_block = config.run(
                [role, "services.wazuh.rule_block", None], variables=vars_
            )[0]
            if rule_block is None:
                raise AnsibleError(
                    f"wazuh_ruleset: role '{role}' opts in to Wazuh but sets no "
                    "services.wazuh.rule_block."
                )
            entities.append(
                {
                    "entity": entity,
                    "program": entity,
                    "decoder": decoder_name(entity),
                    "rule_block": int(rule_block),
                }
            )
            for kind in RULESET_KINDS:
                src = ROLES_DIR / role / "files" / "wazuh" / f"{kind}.xml"
                if src.is_file():
                    files.append(
                        {"src": str(src), "kind": kind, "name": f"{entity}_{kind}.xml"}
                    )

        entities.sort(key=lambda e: e["entity"])
        files.sort(key=lambda f: (f["kind"], f["name"]))
        return [
            {
                "selftest": {"program": SELFTEST_TAG, "decoder": SELFTEST_TAG},
                "entities": entities,
                "files": files,
            }
        ]
