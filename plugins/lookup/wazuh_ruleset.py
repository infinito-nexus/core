from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.roles.applications.services.wazuh import (
    CONTAINER_COMM,
    DEPLOY_TAG,
    FIM_TAG,
    JOURNALD_DECODER,
    JOURNALD_PROGRAM,
    OWN_TAGS,
    PROVIDER_ENTITY,
    SAMPLES_FILE,
    SELFTEST_TAG,
    SYSTEM_TAGS,
    WATCH_TAG,
    decoder_name,
    docker_rule_ids,
    load_samples,
)
from utils.roles.entity.name import get_entity_name

RULESET_KINDS = ("decoders", "rules")


class LookupModule(LookupBase):
    """Return the Wazuh ruleset of every inventory role that opts in.

    A role opts in through ``services.wazuh.enabled``, the same flag
    ``sys-svc-container/templates/base.yml.j2`` reads for the journald tag.
    The Wazuh role itself is skipped, because its ``wazuh`` entry is the
    provider, not an opt-in.

    Args:
        scope: ``deployment`` covers every role with hosts in ``groups``, which
            is what the manager loads rules for; ``host`` covers the roles in
            this host's ``group_names``, which is what its agent collects.

    Returns:
        ``{selftest, deploy, fim, watch, own, journald, system_tags,
        container_comm, entities, files, samples}``. ``system_tags`` lists the
        host programs the agent collects as root, ``container_comm`` the
        ``_COMM`` of container log lines.
        ``selftest``, ``deploy``, ``fim`` and ``watch`` are ``{program,
        decoder}`` of the reserved tags for the self-test, the deploy markers,
        the FIM who-data state and the log collector freeze; ``own`` lists the
        four in that order. ``journald``
        is ``{program, decoder}`` of journald's own messages, which report
        rate-limit suppression. ``entities`` is
        ``[{entity, role, program, decoder, rule_block, docker}]`` sorted by
        ``entity``, one per opted-in role, tag-only roles included: ``program``
        is the journald tag, ``decoder`` its base parent decoder, and
        ``docker`` the ``{oom, healthcheck, swarm, compose}`` IDs of its central
        Docker attribution rules.
        ``files`` is ``[{src, kind, name}]`` sorted by ``kind`` and ``name``:
        ``src`` is ``roles/<role>/files/wazuh/<kind>.xml``, ``kind`` is
        ``decoders`` or ``rules``, and ``name`` is ``<entity>_<kind>.xml``.
        A role without one or both files contributes only the files it has.
        ``samples`` is ``[{role, program, decoder, lines, rule, level}]``:
        the Wazuh role's samples first (self-test unless the sample names
        another own tag or ``systemd-journald`` in ``program``), then each opted-in role's
        ``files/wazuh/samples.yml`` in entity order.

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

        scope = kwargs.get("scope")
        if scope == "deployment":
            groups = vars_.get("groups") or {}
            in_scope = [name for name, hosts in groups.items() if hosts]
        elif scope == "host":
            in_scope = list(vars_.get("group_names") or [])
        else:
            raise AnsibleError(
                f"wazuh_ruleset: scope must be 'host' or 'deployment', got {scope!r}."
            )
        inventory_roles = sorted(name for name in in_scope if name in applications)

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
                    "role": role,
                    "program": entity,
                    "decoder": decoder_name(entity),
                    "rule_block": int(rule_block),
                    "docker": docker_rule_ids(int(rule_block)),
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
        own = {tag: {"program": tag, "decoder": tag} for tag in OWN_TAGS}
        journald = {"program": JOURNALD_PROGRAM, "decoder": JOURNALD_DECODER}
        sample_sources = {**own, JOURNALD_PROGRAM: journald}
        sources = [
            (role, own[SELFTEST_TAG])
            for role in sorted(applications)
            if get_entity_name(role) == PROVIDER_ENTITY
        ] + [(owners[e["entity"]], e) for e in entities]
        samples = []
        for role, source in sources:
            for sample in load_samples(
                ROLES_DIR / role / "files" / "wazuh" / SAMPLES_FILE
            ):
                program = sample.pop("program", None)
                tagged = sample_sources[program] if program else source
                samples.append(
                    {
                        "role": role,
                        "program": tagged["program"],
                        "decoder": tagged["decoder"],
                        **sample,
                    }
                )
        return [
            {
                "selftest": own[SELFTEST_TAG],
                "deploy": own[DEPLOY_TAG],
                "fim": own[FIM_TAG],
                "watch": own[WATCH_TAG],
                "own": [own[tag] for tag in OWN_TAGS],
                "journald": journald,
                "system_tags": list(SYSTEM_TAGS),
                "container_comm": CONTAINER_COMM,
                "entities": entities,
                "files": files,
                "samples": samples,
            }
        ]
