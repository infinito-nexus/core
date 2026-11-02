"""Filters for the OpenLDAP HA form, thin wrappers over ``utils.roles.openldap_ha``."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.openldap_ha import (
    OpenLDAPHAError,
    batch_result_codes,
    forbidden_bind_writes,
    render_cn_config,
    schema_drops,
    server_ids,
)


def openldap_server_ids(host_ids):
    try:
        return server_ids(list(host_ids))
    except OpenLDAPHAError as exc:
        raise AnsibleFilterError(str(exc)) from exc


def openldap_cn_config(host_id, host_ids, peer_template, suffix, root_dn, schemas):
    try:
        return render_cn_config(
            host_id=host_id,
            host_ids=list(host_ids),
            peer_template=peer_template,
            suffix=suffix,
            root_dn=root_dn,
            schemas=list(schemas),
        )
    except OpenLDAPHAError as exc:
        raise AnsibleFilterError(str(exc)) from exc


class FilterModule:
    def filters(self):
        return {
            "openldap_server_ids": openldap_server_ids,
            "openldap_cn_config": openldap_cn_config,
            "openldap_forbidden_bind_writes": forbidden_bind_writes,
            "openldap_schema_drops": schema_drops,
            "openldap_batch_result_codes": batch_result_codes,
        }
