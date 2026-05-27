def merge_with_defaults(defaults, customs):
    """
    Recursively merge two dicts (customs into defaults).
    For each top-level key in customs, ensure all dict keys from defaults are present (at least empty dict).
    Customs always take precedence.
    """

    def merge_dict(d1, d2):
        # Recursively merge d2 into d1, d2 wins
        result = dict(d1) if d1 else {}
        for k, v in (d2 or {}).items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = merge_dict(result[k], v)
            else:
                result[k] = v
        return result

    merged = {}
    # Union of all app-keys
    all_keys = set(defaults or {}).union(set(customs or {}))
    for app_key in all_keys:
        base = (defaults or {}).get(app_key, {})
        override = (customs or {}).get(app_key, {})

        # Step 1: merge override into base
        result = merge_dict(base, override)

        # Step 2: ensure all dict keys from base exist in result (at least {})
        for k, v in (base or {}).items():
            if isinstance(v, dict) and k not in result:
                result[k] = {}
        merged[app_key] = result
    return merged


class FilterModule:
    """Custom merge filter for Infinito.Nexus: merge_with_defaults"""

    def filters(self):
        return {
            "merge_with_defaults": merge_with_defaults,
        }
