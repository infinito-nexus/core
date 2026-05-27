import json
from collections.abc import Iterable
from copy import deepcopy


class FilterModule:
    """Custom Jinja2 filters for LDAP related rendering."""

    def filters(self):
        return {
            "ldap_groups_filter": self.ldap_groups_filter,
            "ldap_roles_mapper_payload": self.ldap_roles_mapper_payload,
        }

    def ldap_groups_filter(self, flavors, default="groupOfNames") -> str:
        """
        Build an LDAP objectClass filter for groups based on available flavors.

        Args:
            flavors: list/tuple/set of enabled flavors (e.g. ["groupOfNames","organizationalUnit"])
            default: fallback objectClass if nothing matches

        Returns:
            A *single-line* LDAP filter string suitable for JSON, e.g.:
            (|(objectClass=groupOfNames)(objectClass=organizationalUnit))

        Rules:
          - If both groupOfNames and organizationalUnit are present -> OR them.
          - If one of them is present -> use that one.
          - Otherwise -> use `default`.
        """
        if flavors is None:
            flavors = []
        if isinstance(flavors, str):
            # be forgiving if someone passes a comma-separated string
            flavors = [f.strip() for f in flavors.split(",") if f.strip()]
        if not isinstance(flavors, Iterable):
            raise TypeError(
                "ldap_groups_filter: 'flavors' must be an iterable or comma-separated string"
            )

        have_gon = "groupOfNames" in flavors
        have_ou = "organizationalUnit" in flavors

        if have_gon and have_ou:
            classes = ["groupOfNames", "organizationalUnit"]
            return f"(|{''.join(f'(objectClass={c})' for c in classes)})"
        if have_gon:
            return "(objectClass=groupOfNames)"
        if have_ou:
            return "(objectClass=organizationalUnit)"
        # fallback
        return f"(objectClass={default})"

    def ldap_roles_mapper_payload(self, desired_group_mapper, ldap_cmp_id) -> str:
        """
        Render the JSON payload for the canonical ``ldap-roles`` mapper that
        kcadm consumes via ``create components ... -f -``.

        Args:
            desired_group_mapper: dict, the cleaned mapper template extracted
                from KEYCLOAK_DICTIONARY_REALM (no ``id`` / ``subComponents``).
            ldap_cmp_id: str, the parent LDAP component id (will be ``.strip()``ed).

        Returns:
            A compact JSON string ready for ``printf '%s'`` piping into kcadm.
        """
        if not isinstance(desired_group_mapper, dict):
            raise TypeError(
                "ldap_roles_mapper_payload: 'desired_group_mapper' must be a dict"
            )
        if not isinstance(ldap_cmp_id, str):
            raise TypeError("ldap_roles_mapper_payload: 'ldap_cmp_id' must be a string")

        payload = deepcopy(desired_group_mapper)
        payload.update(
            {
                "name": "ldap-roles",
                "parentId": ldap_cmp_id.strip(),
                "providerType": "org.keycloak.storage.ldap.mappers.LDAPStorageMapper",
                "providerId": "group-ldap-mapper",
            },
        )
        return json.dumps(payload)
