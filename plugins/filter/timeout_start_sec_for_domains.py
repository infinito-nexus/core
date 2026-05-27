from ansible.errors import AnsibleFilterError


class FilterModule:
    def filters(self):
        return {
            "timeout_start_sec_for_domains": self.timeout_start_sec_for_domains,
        }

    def timeout_start_sec_for_domains(
        self,
        domains_dict,
        include_www=True,
        per_domain_seconds=25,
        overhead_seconds=30,
        min_seconds=120,
        max_seconds=3600,
    ):
        """
        Args:
            domains_dict (dict | list[str] | str): Either the domain mapping dict
                (values can be str | list[str] | dict[str,str]) or an already
                flattened list of domains, or a single domain string.
            include_www (bool): If true, add 'www.<domain>' for non-www entries.
            ...
        """
        try:
            # Local flattener for dict inputs (like your generate_all_domains source)
            def _flatten_from_dict(domains_map):
                flat = []
                for v in (domains_map or {}).values():
                    if isinstance(v, str):
                        flat.append(v)
                    elif isinstance(v, list):
                        flat.extend(v)
                    elif isinstance(v, dict):
                        flat.extend(v.values())
                return flat

            # Accept dict | list | str
            if isinstance(domains_dict, dict):
                flat = _flatten_from_dict(domains_dict)
            elif isinstance(domains_dict, list):
                flat = list(domains_dict)
            elif isinstance(domains_dict, str):
                flat = [domains_dict]
            else:
                # nocheck (TRY301 below): re-raised verbatim by the
                # AnsibleFilterError handler — intentional pass-through.
                raise AnsibleFilterError(  # noqa: TRY301
                    "Expected 'domains_dict' to be dict | list | str."
                )

            if include_www:
                base_unique = sorted(set(flat))
                www_variants = [
                    f"www.{d}"
                    for d in base_unique
                    if not str(d).lower().startswith("www.")
                ]
                flat.extend(www_variants)

            unique_domains = sorted(set(flat))
            count = len(unique_domains)

            raw = overhead_seconds + per_domain_seconds * count
            return max(min_seconds, min(max_seconds, int(raw)))

        except AnsibleFilterError:
            raise
        except Exception as exc:
            raise AnsibleFilterError(
                f"timeout_start_sec_for_domains failed: {exc}"
            ) from exc
