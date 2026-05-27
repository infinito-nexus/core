from ansible.errors import AnsibleFilterError


class FilterModule:
    def filters(self):
        return {"generate_all_domains": self.generate_all_domains}

    def generate_all_domains(self, domains_dict, include_www: bool = True):
        """
        Transform a dict of domains (values: str, list, dict) into a flat list,
        optionally add 'www.' prefixes, dedupe and sort alphabetically.
        """

        def _add(flat, item):
            """Append strings or recurse into lists/dicts; ignore unsupported types."""
            if item is None:
                return
            if isinstance(item, str):
                if item.strip():
                    flat.append(item)
                return
            if isinstance(item, list):
                for x in item:
                    _add(flat, x)
                return
            if isinstance(item, dict):
                for x in item.values():
                    _add(flat, x)
                return
            # Any other type is ignored on purpose (keeps behavior tolerant)

        def _flatten(domains):
            flat = []
            for v in (domains or {}).values():
                _add(flat, v)
            return flat

        try:
            flat = _flatten(domains_dict)
            if include_www:
                original = list(flat)
                flat.extend([f"www.{d}" for d in original])
            return sorted(set(flat))
        except Exception as exc:
            raise AnsibleFilterError(f"generate_all_domains failed: {exc}") from exc
