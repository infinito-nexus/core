"""OpenLDAP HA form: serverID derivation and per-instance ``cn=config`` LDIF."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.roles.db.instances import DbInstancesError, host_hash, host_hash_map

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

SERVER_ID_MAX = 4095
CORE_SCHEMAS = ("core", "cosine", "inetorgperson", "nis")
SCHEMA_DIR = "/etc/ldap/schema"
MODULE_PATH = "/usr/lib/ldap"
DATA_DIR = "/var/lib/ldap"
DATA_DATABASE_DN = "olcDatabase={1}mdb,cn=config"
ROOT_PEERCRED = "gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth"
ELECTOR_PEERCRED = (
    "gidNumber=@OPENLDAP_GID@+uidNumber=@OPENLDAP_UID@,cn=peercred,cn=external,cn=auth"
)


class OpenLDAPHAError(ValueError):
    pass


def server_id(host_id: str) -> int:
    """Map a host-id to an ``olcServerID`` in 1..4095.

    Args:
        host_id: sanitized inventory hostname of the instance.
    """
    if not host_id:
        raise OpenLDAPHAError("openldap_ha: host_id must be non-empty")
    return host_hash(host_id, SERVER_ID_MAX)


def server_ids(host_ids: Iterable[str]) -> dict[str, int]:
    """Return ``{host_id: serverID}`` and fail on any collision in the group.

    Args:
        host_ids: host-ids of every instance in the engine group.
    """
    try:
        return host_hash_map(host_ids, server_id)
    except DbInstancesError as exc:
        raise OpenLDAPHAError(f"openldap_ha olcServerID: {exc}") from exc


def _entry(dn: str, *lines: str) -> str:
    return "\n".join((f"dn: {dn}", *lines))


def _schema_entry(schema: Mapping) -> str:
    name = schema["name"]
    return _entry(
        f"cn={name},cn=schema,cn=config",
        "objectClass: olcSchemaConfig",
        f"cn: {name}",
        *(f"olcAttributeTypes: {at}" for at in schema.get("attribute_types") or []),
        *(f"olcObjectClasses: {oc}" for oc in schema.get("object_classes") or []),
    )


def _syncrepl(index: int, rid: int, provider: str, suffix: str, root_dn: str) -> str:
    return (
        f"olcSyncrepl: {{{index}}}rid={rid:03d} provider={provider} "
        f'bindmethod=simple binddn="{root_dn}" credentials=@ROOT_PW@ '
        f'searchbase="{suffix}" type=refreshAndPersist '
        'retry="2 10 10 +" timeout=1 network-timeout=1 keepalive=10:3:5 '
        "exattrs=memberOf"
    )


def render_cn_config(
    *,
    host_id: str,
    host_ids: Sequence[str],
    peer_template: str,
    suffix: str,
    root_dn: str,
    schemas: Sequence[Mapping],
    uid_max_length: int,
) -> str:
    """Render one instance's complete ``cn=config`` as LDIF.

    Args:
        host_id: the instance this configuration belongs to.
        host_ids: every instance's host-id; peers get a syncrepl each, and
            the replica id is the 1-based position in the sorted list, so
            every instance names the same provider with the same rid.
        peer_template: provider URL with ``{host}``, e.g.
            ``ldap://openldap-{host}:1389``.
        suffix: data tree suffix.
        root_dn: data tree root DN; also the syncrepl bind DN.
        schemas: custom schemas, each ``{name, attribute_types, object_classes}``.
        uid_max_length: longest ``uid`` the constraint overlay accepts.
    """
    ids = server_ids(host_ids)
    if host_id not in ids:
        raise OpenLDAPHAError(f"openldap_ha: '{host_id}' is not in the instance group")
    peers = [
        (rid, peer) for rid, peer in enumerate(sorted(ids), start=1) if peer != host_id
    ]
    syncrepls = [
        _syncrepl(index, rid, peer_template.format(host=peer), suffix, root_dn)
        for index, (rid, peer) in enumerate(peers)
    ]

    entries = [
        _entry(
            "cn=config",
            "objectClass: olcGlobal",
            "cn: config",
            f"olcServerID: {ids[host_id]}",
            "olcPidFile: /run/slapd/slapd.pid",
            "olcArgsFile: /run/slapd/slapd.args",
            "olcPasswordHash: {SSHA}",
        ),
        _entry(
            "cn=module{0},cn=config",
            "objectClass: olcModuleList",
            "cn: module{0}",
            f"olcModulePath: {MODULE_PATH}",
            "olcModuleLoad: {0}back_mdb",
            "olcModuleLoad: {1}memberof",
            "olcModuleLoad: {2}refint",
            "olcModuleLoad: {3}syncprov",
            "olcModuleLoad: {4}constraint",
        ),
        _entry("cn=schema,cn=config", "objectClass: olcSchemaConfig", "cn: schema"),
        "\n\n".join(
            f"include: file://{SCHEMA_DIR}/{name}.ldif" for name in CORE_SCHEMAS
        ),
        *(_schema_entry(schema) for schema in schemas),
        _entry(
            "olcDatabase={-1}frontend,cn=config",
            "objectClass: olcDatabaseConfig",
            "objectClass: olcFrontendConfig",
            "olcDatabase: {-1}frontend",
        ),
        _entry(
            "olcDatabase={0}config,cn=config",
            "objectClass: olcDatabaseConfig",
            "olcDatabase: {0}config",
            f'olcAccess: {{0}}to * by dn.exact="{ROOT_PEERCRED}" manage '
            f'by dn.exact="{ELECTOR_PEERCRED}" manage by * none',
        ),
        _entry(
            DATA_DATABASE_DN,
            "objectClass: olcDatabaseConfig",
            "objectClass: olcMdbConfig",
            "olcDatabase: {1}mdb",
            f"olcSuffix: {suffix}",
            f"olcRootDN: {root_dn}",
            "olcRootPW: @ROOT_PW_HASH@",
            f"olcDbDirectory: {DATA_DIR}",
            "olcDbMaxSize: 1073741824",
            "olcDbIndex: objectClass eq",
            "olcDbIndex: entryCSN,entryUUID eq",
            "olcReadOnly: TRUE",
            'olcLimits: {0}dn.exact="' + root_dn + '" time=unlimited size=unlimited',
            f'olcAccess: {{0}}to attrs=userPassword by dn.exact="{root_dn}" manage '
            f'by dn.exact="{ROOT_PEERCRED}" manage by self write by anonymous auth '
            "by * none",
            f'olcAccess: {{1}}to * by dn.exact="{root_dn}" manage '
            f'by dn.exact="{ROOT_PEERCRED}" manage by * read',
            *syncrepls,
            "olcMultiProvider: TRUE",
        ),
        _entry(
            f"olcOverlay={{0}}syncprov,{DATA_DATABASE_DN}",
            "objectClass: olcOverlayConfig",
            "objectClass: olcSyncProvConfig",
            "olcOverlay: {0}syncprov",
            "olcSpCheckpoint: 100 10",
            "olcSpSessionLog: 1000",
        ),
        _entry(
            f"olcOverlay={{1}}memberof,{DATA_DATABASE_DN}",
            "objectClass: olcOverlayConfig",
            "objectClass: olcMemberOf",
            "olcOverlay: {1}memberof",
            "olcMemberOfDangling: ignore",
            "olcMemberOfRefInt: TRUE",
            "olcMemberOfGroupOC: groupOfNames",
            "olcMemberOfMemberAD: member",
            "olcMemberOfMemberOfAD: memberOf",
            "olcMemberOfAddCheck: TRUE",
        ),
        _entry(
            f"olcOverlay={{2}}refint,{DATA_DATABASE_DN}",
            "objectClass: olcOverlayConfig",
            "objectClass: olcRefintConfig",
            "olcOverlay: {2}refint",
            "olcRefintAttribute: memberOf member manager owner",
        ),
        _entry(
            f"olcOverlay={{3}}constraint,{DATA_DATABASE_DN}",
            "objectClass: olcOverlayConfig",
            "objectClass: olcConstraintConfig",
            "olcOverlay: {3}constraint",
            f"olcConstraintAttribute: uid size {uid_max_length}",
        ),
    ]
    return "\n\n".join(entries) + "\n"


_BATCH_RESULT = re.compile(r"^ldap_(?:add|modify): .*\((\d+)\)\s*$", re.MULTILINE)


def batch_result_codes(stderr: str) -> list[int]:
    """Return the LDAP result code of every entry an ``ldapadd -c`` or
    ``ldapmodify -c`` batch refused, in order.

    Args:
        stderr: the batch's standard error.
    """
    return [int(code) for code in _BATCH_RESULT.findall(stderr or "")]


def forbidden_bind_writes(ldif: str) -> list[str]:
    """Return the bind-time write features present in a ``cn=config`` dump.

    Args:
        ldif: ``ldapsearch`` output of ``cn=config`` (or a rendered config).

    Returns:
        ``ppolicy`` and/or ``olcLastBind`` when enabled; both turn binds into
        writes that bypass ``olcReadOnly``.
    """
    found = []
    if re.search(
        r"^olcOverlay:\s*(\{\d+\})?ppolicy\s*$", ldif, re.MULTILINE | re.IGNORECASE
    ):
        found.append("ppolicy")
    if re.search(r"^olcLastBind:\s*TRUE\s*$", ldif, re.MULTILINE | re.IGNORECASE):
        found.append("olcLastBind")
    return found


def _schema_name(dn: str) -> str:
    first = dn.split(",", 1)[0]
    value = first.split("=", 1)[-1]
    return re.sub(r"^\{\d+\}", "", value).strip()


def schema_drops(live_schema_dns: Iterable[str], rendered: str) -> list[str]:
    """Return live schema names the rendered configuration would drop.

    Args:
        live_schema_dns: DNs of the live ``cn=schema,cn=config`` children.
        rendered: output of :func:`render_cn_config`.
    """
    kept = set(CORE_SCHEMAS)
    kept.update(
        _schema_name(line[4:])
        for line in rendered.splitlines()
        if line.startswith("dn: ") and line.endswith(",cn=schema,cn=config")
    )
    return sorted(
        {
            name
            for name in (_schema_name(dn) for dn in live_schema_dns if dn.strip())
            if name and name.lower() not in {k.lower() for k in kept}
        }
    )
