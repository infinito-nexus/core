import unittest
import yaml
from pathlib import Path
from urllib.parse import urlparse


class TestCspConfigurationConsistency(unittest.TestCase):
    """
    Iterate all roles; for each config/main.yml that defines 'server.csp',
    assert consistent structure and values:
      - csp is a dict
      - whitelist/flags/hashes are dicts if present
      - directives used are supported
      - flags are dicts of {flag_name: bool}, flag_name in SUPPORTED_FLAGS
      - whitelist entries are valid URLs/schemes/Jinja-or '*'
      - hashes entries are str or list[str], non-empty
    On error, include role name and file path for easier debugging.
    """

    SUPPORTED_DIRECTIVES = {
        "default-src",
        "connect-src",
        "frame-ancestors",
        "frame-src",
        "script-src",
        "script-src-elem",
        "style-src",
        "style-src-elem",
        "font-src",
        "worker-src",
        "manifest-src",
        "media-src",
        "style-src-attr",
        "script-src-attr",
    }

    SUPPORTED_FLAGS = {"unsafe-eval", "unsafe-inline"}

    def is_valid_whitelist_entry(self, entry: str) -> bool:
        """
        Accept entries that are:
          - Jinja expressions (contain '{{' and '}}')
          - '*' wildcard
          - Data or Blob URIs (start with 'data:' or 'blob:')
          - HTTP/HTTPS/WS/WSS URLs (with netloc)
        """
        if not isinstance(entry, str):
            return False
        e = entry.strip()
        if not e:
            return False
        if "{{" in e and "}}" in e:
            return True
        if e == "*":
            return True
        if e.startswith(("data:", "blob:")):
            return True
        parsed = urlparse(e)
        return parsed.scheme in ("http", "https", "ws", "wss") and bool(parsed.netloc)

    def test_csp_configuration_structure(self):
        roles_dir = Path(__file__).resolve().parents[3] / "roles"
        errors = []

        for role_path in sorted(roles_dir.iterdir()):
            if not role_path.is_dir():
                continue

            cfg_file = role_path / "meta" / "services.yml"
            if not cfg_file.exists():
                continue

            # Parse YAML (collect role + file path on error)
            try:
                cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as e:
                errors.append(f"{role_path.name}: YAML parse error in {cfg_file}: {e}")
                continue

            csp = cfg.get("server", {}).get("csp")
            if csp is None:
                continue  # No CSP section, nothing to check

            if not isinstance(csp, dict):
                errors.append(
                    f"{role_path.name}: 'server.csp' must be a dict (found {type(csp).__name__}) in {cfg_file}"
                )
                # Can't proceed safely with sub-sections
                continue

            # ---------- Validate whitelist ----------
            wl = csp.get("whitelist", {})
            if wl is not None and not isinstance(wl, dict):
                errors.append(
                    f"{role_path.name}: server.csp.whitelist must be a dict (found {type(wl).__name__}) in {cfg_file}"
                )
                wl = {}  # prevent crash; continue to scan other sections
            if isinstance(wl, dict):
                for directive, val in wl.items():
                    if directive not in self.SUPPORTED_DIRECTIVES:
                        errors.append(
                            f"{role_path.name}: whitelist contains unsupported directive '{directive}' ({cfg_file})"
                        )
                    # val may be str or list[str]
                    if isinstance(val, str):
                        values = [val]
                    elif isinstance(val, list):
                        values = val
                    else:
                        errors.append(
                            f"{role_path.name}: whitelist.{directive} must be a string or list of strings (found {type(val).__name__}) ({cfg_file})"
                        )
                        values = []

                    for entry in values:
                        if not isinstance(entry, str) or not entry.strip():
                            errors.append(
                                f"{role_path.name}: whitelist.{directive} contains empty or non-string entry ({cfg_file})"
                            )
                        elif not self.is_valid_whitelist_entry(entry):
                            errors.append(
                                f"{role_path.name}: whitelist.{directive} entry '{entry}' is not a valid value ({cfg_file})"
                            )

            # ---------- Validate flags ----------
            fl = csp.get("flags", {})
            if fl is not None and not isinstance(fl, dict):
                errors.append(
                    f"{role_path.name}: server.csp.flags must be a dict (found {type(fl).__name__}) in {cfg_file}"
                )
                fl = {}
            if isinstance(fl, dict):
                for directive, flag_dict in fl.items():
                    if directive not in self.SUPPORTED_DIRECTIVES:
                        errors.append(
                            f"{role_path.name}: flags contains unsupported directive '{directive}' ({cfg_file})"
                        )
                    if not isinstance(flag_dict, dict):
                        errors.append(
                            f"{role_path.name}: flags.{directive} must be a dict of flag_name->bool (found {type(flag_dict).__name__}) ({cfg_file})"
                        )
                        continue
                    for flag_name, flag_val in flag_dict.items():
                        if flag_name not in self.SUPPORTED_FLAGS:
                            errors.append(
                                f"{role_path.name}: flags.{directive} has unsupported flag '{flag_name}' ({cfg_file})"
                            )
                        if not isinstance(flag_val, bool):
                            errors.append(
                                f"{role_path.name}: flags.{directive}.{flag_name} must be a boolean (found {type(flag_val).__name__}) ({cfg_file})"
                            )

            # ---------- Validate hashes ----------
            hs = csp.get("hashes", {})
            if hs is not None and not isinstance(hs, dict):
                errors.append(
                    f"{role_path.name}: server.csp.hashes must be a dict (found {type(hs).__name__}) in {cfg_file}"
                )
                hs = {}
            if isinstance(hs, dict):
                for directive, snippet_val in hs.items():
                    if directive not in self.SUPPORTED_DIRECTIVES:
                        errors.append(
                            f"{role_path.name}: hashes contains unsupported directive '{directive}' ({cfg_file})"
                        )
                    if isinstance(snippet_val, str):
                        snippets = [snippet_val]
                    elif isinstance(snippet_val, list):
                        snippets = snippet_val
                    else:
                        errors.append(
                            f"{role_path.name}: hashes.{directive} must be a string or list of strings (found {type(snippet_val).__name__}) ({cfg_file})"
                        )
                        snippets = []

                    for snippet in snippets:
                        if not isinstance(snippet, str) or not snippet.strip():
                            errors.append(
                                f"{role_path.name}: hashes.{directive} contains empty or non-string snippet ({cfg_file})"
                            )

        if errors:
            self.fail(
                f"CSP configuration validation failures ({len(errors)}):\n"
                + "\n".join(errors)
            )


if __name__ == "__main__":
    unittest.main()
