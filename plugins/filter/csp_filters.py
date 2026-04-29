from ansible.errors import AnsibleFilterError
import hashlib
import base64
from utils.applications.config import get
from utils.get_url import get_url


def _dedup_preserve(seq):
    """Return a list with stable order and unique items."""
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _sort_tokens(tokens):
    """
    Return a deterministically ordered list of CSP tokens.
    - de-duplicates while preserving relative order
    - then sorts lexicographically
    - keeps 'self' as the first token if present
    """
    uniq = _dedup_preserve(tokens)
    if not uniq:
        return uniq

    # Lexicographically sort all tokens
    uniq = sorted(uniq)

    # Ensure "'self'" is always first if present
    if "'self'" in uniq:
        uniq.remove("'self'")
        uniq.insert(0, "'self'")

    return uniq


class FilterModule(object):
    """
    Jinja filters for building a robust, CSP3-aware Content-Security-Policy header.
    Safari/CSP2 compatibility is ensured by merging the -elem/-attr variants into the base
    directives (style-src, script-src). We intentionally do NOT mirror back into -elem/-attr
    to allow true CSP3 granularity on modern browsers.
    """

    def filters(self):
        return {
            "build_csp_header": self.build_csp_header,
            "add_csp_hash": self.add_csp_hash,
        }

    @staticmethod
    def add_csp_hash(current, application_id, directive, snippet):
        """
        Return a new ``webserver_csp_hashes_extra_by_app``-shaped dict with
        ``snippet`` appended (deduplicated) to ``<application_id>.<directive>``.

        Replaces the verbose inline ``combine(..., recursive=True)`` pattern
        previously duplicated across sys-front-inj-* roles.
        """
        try:
            result = dict(current or {})
            app_entry = dict(result.get(application_id, {}) or {})
            existing = list(app_entry.get(directive, []) or [])
            if snippet not in existing:
                existing.append(snippet)
            app_entry[directive] = existing
            result[application_id] = app_entry
            return result
        except Exception as exc:
            raise AnsibleFilterError(f"add_csp_hash failed: {exc}")

    # -------------------------------
    # Helpers
    # -------------------------------

    @staticmethod
    def is_feature_enabled(
        applications: dict, feature: str, application_id: str
    ) -> bool:
        """
        Returns True if the docker service flag is enabled for this application.

        New flag layout (examples):
          - services.matomo.enabled
          - services.dashboard.enabled
          - services.simpleicons.enabled
          - services.logout.enabled
          - services.hcaptcha.enabled
          - services.recaptcha.enabled
        """
        return get(
            applications,
            application_id,
            f"services.{feature}.enabled",
            False,
            False,
        )

    @staticmethod
    def get_csp_whitelist(applications, application_id, directive):
        """
        Returns a list of additional whitelist entries for a given directive.
        Accepts both scalar and list in config; always returns a list.
        """
        wl = get(
            applications, application_id, "server.csp.whitelist." + directive, False, []
        )
        if isinstance(wl, list):
            return wl
        if wl:
            return [wl]
        return []

    @staticmethod
    def get_csp_flags(applications, application_id, directive):
        """
        Returns CSP flag tokens (e.g., "'unsafe-eval'", "'unsafe-inline'") for a directive,
        merging sane defaults with app config.

        Defaults:
          - For styles we enable 'unsafe-inline' by default (style-src, style-src-elem, style-src-attr),
            because many apps rely on inline styles / style attributes.
          - For scripts we do NOT enable 'unsafe-inline' by default.
        """
        default_flags = {}
        if directive in ("style-src", "style-src-elem", "style-src-attr"):
            default_flags = {"unsafe-inline": True}

        configured = get(
            applications, application_id, "server.csp.flags." + directive, False, {}
        )

        merged = {**default_flags, **configured}

        tokens = []
        for flag_name, enabled in merged.items():
            if enabled:
                tokens.append(f"'{flag_name}'")
        return tokens

    @staticmethod
    def get_csp_inline_content(applications, application_id, directive):
        """
        Returns inline script/style snippets to hash for a given directive.
        Accepts both scalar and list in config; always returns a list.
        """
        snippets = get(
            applications, application_id, "server.csp.hashes." + directive, False, []
        )
        if isinstance(snippets, list):
            return snippets
        if snippets:
            return [snippets]
        return []

    @staticmethod
    def get_csp_hash(content):
        """
        Computes the SHA256 hash of the given inline content and returns
        a CSP token like "'sha256-<base64>'".
        """
        try:
            digest = hashlib.sha256(content.encode("utf-8")).digest()
            b64 = base64.b64encode(digest).decode("utf-8")
            return f"'sha256-{b64}'"
        except Exception as exc:
            raise AnsibleFilterError(f"get_csp_hash failed: {exc}")

    @staticmethod
    def get_extra_values(extra_mapping, directive):
        values = (extra_mapping or {}).get(directive, [])
        if isinstance(values, list):
            return values
        if values:
            return [values]
        return []

    # -------------------------------
    # Main builder
    # -------------------------------

    def build_csp_header(
        self,
        applications,
        application_id,
        domains,
        web_protocol,
        extra_whitelist=None,
        extra_hashes=None,
    ):
        """
        Builds the Content-Security-Policy header value dynamically based on application settings.

        Key points:
          - CSP3-aware: supports base/elem/attr for styles and scripts.
          - Safari/CSP2 fallback: base directives (style-src, script-src) always include
            the union of their -elem/-attr variants.
          - We do NOT mirror back into -elem/-attr; finer CSP3 rules remain effective
            on modern browsers if you choose to use them.
          - If the app explicitly disables a token on the *base* (e.g. style-src.unsafe-inline: false),
            that token is removed from the merged base even if present in elem/attr.
          - Inline hashes are added ONLY if that directive does NOT include 'unsafe-inline'.
          - Whitelists/flags/hashes read from:
              server.csp.whitelist.<directive>
              server.csp.flags.<directive>
              server.csp.hashes.<directive>
          - “Smart defaults”:
              * internal CDN for style/script elem and connect
              * Matomo endpoints (if services.matomo.enabled) for script-elem/connect
              * Simpleicons service (if services.simpleicons.enabled) for connect
              * reCAPTCHA (if services.recaptcha.enabled) for script-elem/frame-src
              * hCaptcha (if services.hcaptcha.enabled) for script-elem/frame-src
              * frame-ancestors extended for dashboard/logout/keycloak if enabled
        """
        try:
            extra_whitelist = extra_whitelist or {}
            extra_hashes = extra_hashes or {}
            directives = [
                "default-src",
                "connect-src",
                "frame-ancestors",
                "frame-src",
                "script-src",
                "script-src-elem",
                "script-src-attr",
                "style-src",
                "style-src-elem",
                "style-src-attr",
                "font-src",
                "worker-src",
                "manifest-src",
                "media-src",
            ]

            tokens_by_dir = {}
            explicit_flags_by_dir = {}

            for directive in directives:
                # Collect explicit flags (to later respect explicit "False" on base during merge)
                explicit_flags = get(
                    applications,
                    application_id,
                    "server.csp.flags." + directive,
                    False,
                    {},
                )
                explicit_flags_by_dir[directive] = explicit_flags

                tokens = ["'self'"]

                # Flags (with sane defaults)
                flags = self.get_csp_flags(applications, application_id, directive)
                tokens += flags

                # Internal CDN defaults for selected directives
                if directive in (
                    "script-src-elem",
                    "connect-src",
                    "style-src-elem",
                    "style-src",
                ):
                    tokens.append(get_url(domains, "web-svc-cdn", web_protocol))

                # Matomo (if enabled via services.matomo.enabled)
                if directive in ("script-src-elem", "connect-src"):
                    if self.is_feature_enabled(applications, "matomo", application_id):
                        tokens.append(get_url(domains, "web-app-matomo", web_protocol))

                # Simpleicons (if enabled via services.simpleicons.enabled) – typically used via connect-src (fetch)
                if directive == "connect-src":
                    if self.is_feature_enabled(
                        applications, "simpleicons", application_id
                    ):
                        tokens.append(
                            get_url(domains, "web-svc-simpleicons", web_protocol)
                        )

                # reCAPTCHA (if enabled via services.recaptcha.enabled) – scripts + frames
                if self.is_feature_enabled(applications, "recaptcha", application_id):
                    if directive in ("script-src-elem", "frame-src"):
                        tokens.append("https://www.gstatic.com")  # nocheck: url
                        tokens.append("https://www.google.com")

                # hCaptcha (if enabled via services.hcaptcha.enabled) – scripts + frames
                if self.is_feature_enabled(applications, "hcaptcha", application_id):
                    if directive == "script-src-elem":
                        tokens.append("https://www.hcaptcha.com")
                        tokens.append("https://js.hcaptcha.com")
                    if directive == "frame-src":
                        tokens.append("https://newassets.hcaptcha.com/")

                # Frame ancestors (dashboard + logout)
                if directive == "frame-ancestors":
                    if self.is_feature_enabled(
                        applications, "dashboard", application_id
                    ):
                        # Allow being embedded by the dashboard app domain's site
                        domain = domains.get("web-app-dashboard")[0]
                        tokens.append(f"{domain}")
                    if self.is_feature_enabled(applications, "logout", application_id):
                        tokens.append(get_url(domains, "web-svc-logout", web_protocol))
                        tokens.append(
                            get_url(domains, "web-app-keycloak", web_protocol)
                        )

                # Logout support requires inline handlers (script-src-attr + script-src-elem)
                if directive in ("script-src-attr", "script-src-elem"):
                    if self.is_feature_enabled(applications, "logout", application_id):
                        tokens.append("'unsafe-inline'")

                # Custom whitelist
                tokens += self.get_csp_whitelist(
                    applications, application_id, directive
                )
                tokens += self.get_extra_values(extra_whitelist, directive)

                # Inline hashes (only if this directive does NOT include 'unsafe-inline')
                if "'unsafe-inline'" not in tokens:
                    for snippet in self.get_csp_inline_content(
                        applications, application_id, directive
                    ):
                        tokens.append(self.get_csp_hash(snippet))
                    for snippet in self.get_extra_values(extra_hashes, directive):
                        tokens.append(self.get_csp_hash(snippet))

                tokens_by_dir[directive] = _dedup_preserve(tokens)

            # ----------------------------------------------------------
            # CSP3 families → ensure CSP2 fallback (Safari-safe)
            # Merge style/script families so base contains union of elem/attr.
            # Respect explicit disables on the base (e.g. unsafe-inline=False).
            # Do NOT mirror back into elem/attr (keep granularity).
            # ----------------------------------------------------------
            def _strip_if_disabled(unioned_tokens, explicit_flags, name):
                """
                Remove a token (e.g. 'unsafe-inline') from the unioned token list
                if it is explicitly disabled in the base directive flags.
                """
                if (
                    isinstance(explicit_flags, dict)
                    and explicit_flags.get(name) is False
                ):
                    tok = f"'{name}'"
                    return [t for t in unioned_tokens if t != tok]
                return unioned_tokens

            def merge_family(base_key, elem_key, attr_key):
                base = tokens_by_dir.get(base_key, [])
                elem = tokens_by_dir.get(elem_key, [])
                attr = tokens_by_dir.get(attr_key, [])
                union = _dedup_preserve(base + elem + attr)

                # Respect explicit disables on the base
                explicit_base = explicit_flags_by_dir.get(base_key, {})
                for flag_name in ("unsafe-inline", "unsafe-eval"):
                    union = _strip_if_disabled(union, explicit_base, flag_name)

                tokens_by_dir[base_key] = union  # write back only to base

            merge_family("style-src", "style-src-elem", "style-src-attr")
            merge_family("script-src", "script-src-elem", "script-src-attr")

            # ----------------------------------------------------------
            # Assemble header
            # ----------------------------------------------------------
            for directive, toks in list(tokens_by_dir.items()):
                tokens_by_dir[directive] = _sort_tokens(toks)

            parts = []
            for directive in directives:
                if directive in tokens_by_dir:
                    parts.append(f"{directive} {' '.join(tokens_by_dir[directive])};")

            # Keep permissive img-src for data/blob + any host (as before)
            parts.append("img-src * data: blob:;")

            return " ".join(parts)

        except Exception as exc:
            raise AnsibleFilterError(f"build_csp_header failed: {exc}")
