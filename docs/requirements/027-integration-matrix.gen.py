#!/usr/bin/env python3
"""Generate the role×role integration matrix for requirement 027.

Source of truth for docs/requirements/027-integration-matrix.md.
Run: python3 docs/requirements/027-integration-matrix.gen.py

Axes are the entity names of every web-app-* and web-svc-* role.
A cell [row][col] marks whether the ROW role ships an addon/plugin that wires
in the COLUMN role:
  - check  -> a real upstream plugin exists (cell links to its page)
  - coin   -> integration exists but is gated behind a commercial/paid tier
  - cross  -> no known plugin
  - dash   -> diagonal (same role)
"""

import re
from pathlib import Path

ROLES_DIR = Path(__file__).resolve().parent.parent.parent / "roles"

# Top-level meta/services.yml integration keys -> the in-axis target entity they
# wire the role into. These are infinito-native service flags (already wired,
# group-gated), distinct from the curated upstream app<->app plugins in EDGES.
# Skipped on purpose: ldap/redis/mariadb/database -> svc-db-* (not on the axes).
FRAMEWORK = {
    "sso": "keycloak",
    "matomo": "matomo",
    "prometheus": "prometheus",
    "email": "mailu",
    "dashboard": "dashboard",
    "css": "css",
    "logout": "logout",
    "cdn": "cdn",
    "coturn": "coturn",
    "collabora": "collabora",
    "onlyoffice": "onlyoffice",
    "libretranslate": "libretranslate",
}

# Entity names = role suffix of every web-app-*/web-svc-* role.
WEB_APP = [
    "akaunting",
    "baserow",
    "bigbluebutton",
    "bluesky",
    "bookwyrm",
    "bridgy-fed",
    "chess",
    "confluence",
    "dashboard",
    "decidim",
    "discourse",
    "erpnext",
    "espocrm",
    "fediwall",
    "fider",
    "flowise",
    "friendica",
    "funkwhale",
    "fusiondirectory",
    "gitea",
    "gitlab",
    "hugo",
    "jenkins",
    "jira",
    "jitsi",
    "joomla",
    "keycloak",
    "kix",
    "lam",
    "listmonk",
    "littlejs",
    "magento",
    "mailu",
    "mastodon",
    "matomo",
    "matrix",
    "mattermost",
    "mediawiki",
    "mig",
    "minio",
    "mini-qr",
    "mobilizon",
    "moodle",
    "navigator",
    "nextcloud",
    "odoo",
    "opencloud",
    "openproject",
    "opentalk",
    "openwebui",
    "peertube",
    "pgadmin",
    "phpldapadmin",
    "phpmyadmin",
    "pixelfed",
    "postmarks",
    "pretix",
    "prometheus",
    "roulette-wheel",
    "shopware",
    "snipe-it",
    "socialhome",
    "sphinx",
    "suitecrm",
    "taiga",
    "wordpress",
    "xwiki",
    "yourls",
    "zammad",
]
WEB_SVC = [
    "asset",
    "cdn",
    "collabora",
    "coturn",
    "css",
    "file",
    "html",
    "legal",
    "libretranslate",
    "logout",
    "onlyoffice",
    "simpleicons",
    "xmpp",
]
ENTITIES = WEB_APP + WEB_SVC

# (source, target, url, kind). kind: "check" or "coin".
# Verified upstream plugin/integration pages (see requirement 027 research).
EDGES = [
    # --- Nextcloud integration_* family + office/auth/analytics ---
    (
        "nextcloud",
        "openproject",
        "https://github.com/nextcloud/integration_openproject",
        "check",
    ),
    ("nextcloud", "gitlab", "https://github.com/nextcloud/integration_gitlab", "check"),
    (
        "nextcloud",
        "discourse",
        "https://github.com/nextcloud/integration_discourse",
        "check",
    ),
    (
        "nextcloud",
        "mattermost",
        "https://github.com/nextcloud/integration_mattermost",
        "check",
    ),
    ("nextcloud", "matrix", "https://github.com/nextcloud/integration_matrix", "check"),
    ("nextcloud", "jira", "https://github.com/nextcloud/integration_jira", "check"),
    ("nextcloud", "zammad", "https://github.com/nextcloud/integration_zammad", "check"),
    (
        "nextcloud",
        "openwebui",
        "https://github.com/nextcloud/integration_openai",
        "check",
    ),
    (
        "nextcloud",
        "flowise",
        "https://github.com/nextcloud/integration_openai",
        "check",
    ),
    (
        "nextcloud",
        "mastodon",
        "https://github.com/nextcloud/integration_mastodon",
        "check",
    ),
    (
        "nextcloud",
        "peertube",
        "https://github.com/nextcloud/integration_peertube",
        "check",
    ),
    ("nextcloud", "moodle", "https://github.com/nextcloud/integration_moodle", "check"),
    (
        "nextcloud",
        "suitecrm",
        "https://github.com/eneiluj/integration_suitecrm",
        "check",
    ),
    ("nextcloud", "bigbluebutton", "https://apps.nextcloud.com/apps/bbb", "check"),
    ("nextcloud", "xwiki", "https://apps.nextcloud.com/apps/xwiki", "check"),
    ("nextcloud", "collabora", "https://github.com/nextcloud/richdocuments", "check"),
    (
        "nextcloud",
        "onlyoffice",
        "https://github.com/ONLYOFFICE/onlyoffice-nextcloud",
        "check",
    ),
    ("nextcloud", "keycloak", "https://github.com/nextcloud/user_oidc", "check"),
    ("nextcloud", "matomo", "https://apps.nextcloud.com/apps/matomo", "check"),
    # --- Mattermost plugins ---
    (
        "mattermost",
        "gitlab",
        "https://github.com/mattermost/mattermost-plugin-gitlab",
        "check",
    ),
    (
        "mattermost",
        "jira",
        "https://github.com/mattermost/mattermost-plugin-jira",
        "check",
    ),
    (
        "mattermost",
        "jenkins",
        "https://github.com/mattermost/mattermost-plugin-jenkins",
        "check",
    ),
    (
        "mattermost",
        "jitsi",
        "https://github.com/mattermost-community/mattermost-plugin-jitsi",
        "check",
    ),
    (
        "mattermost",
        "openwebui",
        "https://github.com/mattermost/mattermost-plugin-agents",
        "check",
    ),
    (
        "mattermost",
        "prometheus",
        "https://github.com/cpanato/mattermost-plugin-alertmanager",
        "check",
    ),
    (
        "mattermost",
        "keycloak",
        "https://docs.mattermost.com/onboard/sso-saml.html",
        "coin",
    ),
    # --- GitLab native integrations ---
    (
        "gitlab",
        "mattermost",
        "https://docs.gitlab.com/user/project/integrations/mattermost_notifications/",
        "check",
    ),
    ("gitlab", "jira", "https://docs.gitlab.com/integration/jira/", "check"),
    ("gitlab", "jenkins", "https://docs.gitlab.com/integration/jenkins/", "check"),
    (
        "gitlab",
        "matrix",
        "https://docs.gitlab.com/user/project/integrations/matrix/",
        "check",
    ),
    (
        "gitlab",
        "confluence",
        "https://docs.gitlab.com/user/project/integrations/confluence/",
        "check",
    ),
    ("gitlab", "keycloak", "https://docs.gitlab.com/integration/saml/", "check"),
    # --- Discourse plugins ---
    (
        "discourse",
        "mattermost",
        "https://github.com/discourse/discourse-chat-integration",
        "check",
    ),
    (
        "discourse",
        "matrix",
        "https://github.com/discourse/discourse-chat-integration",
        "check",
    ),
    (
        "discourse",
        "prometheus",
        "https://github.com/discourse/discourse-prometheus",
        "check",
    ),
    (
        "discourse",
        "bigbluebutton",
        "https://github.com/discourse/discourse-bbb",
        "check",
    ),
    ("discourse", "jitsi", "https://github.com/discourse/discourse-jitsi", "check"),
    ("discourse", "openwebui", "https://github.com/discourse/discourse-ai", "check"),
    (
        "discourse",
        "matomo",
        "https://github.com/discourse/discourse-matomo-analytics",
        "check",
    ),
    (
        "discourse",
        "keycloak",
        "https://github.com/discourse/discourse-openid-connect",
        "check",
    ),
    (
        "discourse",
        "mastodon",
        "https://github.com/discourse/discourse-activity-pub",
        "check",
    ),
    # --- Matrix (Synapse / hookshot / Element) ---
    ("matrix", "gitlab", "https://github.com/matrix-org/matrix-hookshot", "check"),
    ("matrix", "jira", "https://github.com/matrix-org/matrix-hookshot", "check"),
    (
        "matrix",
        "keycloak",
        "https://matrix-org.github.io/synapse/latest/openid.html",
        "check",
    ),
    (
        "matrix",
        "prometheus",
        "https://matrix-org.github.io/synapse/latest/metrics-howto.html",
        "check",
    ),
    (
        "matrix",
        "jitsi",
        "https://github.com/element-hq/element-web/blob/develop/docs/jitsi.md",
        "check",
    ),
    # --- Moodle plugins ---
    (
        "moodle",
        "bigbluebutton",
        "https://moodle.org/plugins/mod_bigbluebuttonbn",
        "check",
    ),
    ("moodle", "nextcloud", "https://moodle.org/plugins/repository_owncloud", "check"),
    ("moodle", "matrix", "https://docs.moodle.org/en/Matrix", "check"),
    ("moodle", "keycloak", "https://moodle.org/plugins/auth_oidc", "check"),
    ("moodle", "jitsi", "https://moodle.org/plugins/mod_jitsi", "check"),
    ("moodle", "matomo", "https://moodle.org/plugins/tool_webanalytics", "check"),
    ("moodle", "openwebui", "https://moodle.org/plugins/aiprovider_openwebui", "check"),
    # --- Jenkins plugins ---
    ("jenkins", "gitlab", "https://plugins.jenkins.io/gitlab-plugin", "check"),
    ("jenkins", "gitea", "https://plugins.jenkins.io/gitea/", "check"),
    ("jenkins", "mattermost", "https://plugins.jenkins.io/mattermost/", "check"),
    ("jenkins", "prometheus", "https://plugins.jenkins.io/prometheus", "check"),
    ("jenkins", "keycloak", "https://plugins.jenkins.io/oic-auth/", "check"),
    # --- OpenProject ---
    (
        "openproject",
        "nextcloud",
        "https://www.openproject.org/docs/system-admin-guide/integrations/nextcloud/",
        "check",
    ),
    (
        "openproject",
        "gitlab",
        "https://www.openproject.org/docs/system-admin-guide/integrations/gitlab-integration/",
        "check",
    ),
    (
        "openproject",
        "keycloak",
        "https://www.openproject.org/docs/system-admin-guide/authentication/openid-providers/",
        "coin",
    ),
    # --- WordPress plugins ---
    ("wordpress", "matomo", "https://wordpress.org/plugins/matomo/", "check"),
    ("wordpress", "mastodon", "https://wordpress.org/plugins/activitypub/", "check"),
    ("wordpress", "discourse", "https://wordpress.org/plugins/wp-discourse/", "check"),
    (
        "wordpress",
        "keycloak",
        "https://wordpress.org/plugins/daggerhart-openid-connect-generic/",
        "check",
    ),
    (
        "wordpress",
        "listmonk",
        "https://wordpress.org/plugins/integration-for-listmonk-mailing-list-and-newsletter-manager/",
        "check",
    ),
    (
        "wordpress",
        "bigbluebutton",
        "https://wordpress.org/plugins/video-conferencing-with-bbb/",
        "check",
    ),
    (
        "wordpress",
        "peertube",
        "https://wordpress.org/plugins/video-manager-for-peertube/",
        "check",
    ),
    # --- MediaWiki extensions ---
    (
        "mediawiki",
        "keycloak",
        "https://www.mediawiki.org/wiki/Extension:OpenID_Connect",
        "check",
    ),
    ("mediawiki", "matomo", "https://www.mediawiki.org/wiki/Extension:Matomo", "check"),
    (
        "mediawiki",
        "discourse",
        "https://www.mediawiki.org/wiki/Extension:DiscourseSsoConsumer",
        "check",
    ),
    (
        "mediawiki",
        "peertube",
        "https://www.mediawiki.org/wiki/Extension:PeerTubeEmbed",
        "check",
    ),
    (
        "mediawiki",
        "libretranslate",
        "https://www.mediawiki.org/wiki/Extension:MachineTranslation",
        "check",
    ),
    ("mediawiki", "minio", "https://www.mediawiki.org/wiki/Extension:AWS", "check"),
    (
        "mediawiki",
        "openwebui",
        "https://www.mediawiki.org/wiki/Extension:AIEditingAssistant",
        "check",
    ),
    # --- XWiki extensions ---
    (
        "xwiki",
        "keycloak",
        "https://extensions.xwiki.org/xwiki/bin/view/Extension/OpenID%20Connect/",
        "check",
    ),
    (
        "xwiki",
        "matomo",
        "https://extensions.xwiki.org/xwiki/bin/view/Extension/Piwiki%20Integration",
        "check",
    ),
    # --- Joomla ---
    (
        "joomla",
        "keycloak",
        "../../roles/web-app-joomla/files/joomla-oidc-plugin/",
        "check",
    ),
    (
        "joomla",
        "matomo",
        "https://extensions.joomla.org/extension/itcs-matomo/",
        "check",
    ),
    # --- Friendica ---
    ("friendica", "matomo", "https://github.com/friendica/friendica-addons", "check"),
    # --- Pretix ---
    (
        "pretix",
        "keycloak",
        "https://docs.pretix.eu/en/latest/admin/installation/index.html",
        "check",
    ),
    # --- PeerTube ---
    (
        "peertube",
        "keycloak",
        "https://www.npmjs.com/package/peertube-plugin-auth-openid-connect",
        "check",
    ),
    # --- BigBlueButton (Greenlight) ---
    (
        "bigbluebutton",
        "keycloak",
        "https://docs.bigbluebutton.org/greenlight/v3/external-authentication/",
        "check",
    ),
    # --- CRM / ERP: auth + email ---
    (
        "zammad",
        "keycloak",
        "https://admin-docs.zammad.org/en/latest/settings/security/third-party/saml.html",
        "check",
    ),
    (
        "zammad",
        "mailu",
        "https://admin-docs.zammad.org/en/latest/channels/email/index.html",
        "check",
    ),
    ("espocrm", "keycloak", "https://docs.espocrm.com/administration/oidc/", "check"),
    (
        "espocrm",
        "mailu",
        "https://docs.espocrm.com/user-guide/imap-smtp-configuration/",
        "check",
    ),
    (
        "suitecrm",
        "keycloak",
        "https://docs.suitecrm.com/8.x/admin/configuration/saml/8.7.0-saml-configuration/",
        "check",
    ),
    (
        "suitecrm",
        "mailu",
        "https://docs.suitecrm.com/user/advanced-modules/inbound-email/",
        "check",
    ),
    (
        "odoo",
        "keycloak",
        "https://apps.odoo-community.org/apps/modules/14.0/auth_oidc",
        "check",
    ),
    (
        "odoo",
        "mailu",
        "https://www.odoo.com/documentation/latest/applications/general/email_communication.html",
        "check",
    ),
    (
        "odoo",
        "nextcloud",
        "https://apps.odoo.com/apps/modules/19.0/nextcloud_odoo_integration",
        "coin",
    ),
    (
        "erpnext",
        "keycloak",
        "https://docs.frappe.io/framework/user/en/guides/integration/openid_connect_and_frappe_social_login",
        "check",
    ),
    (
        "erpnext",
        "mailu",
        "https://docs.frappe.io/erpnext/user/manual/en/setting-up-email-account",
        "check",
    ),
    # --- Other SSO-to-Keycloak (covered centrally today via the sso service) ---
    (
        "baserow",
        "keycloak",
        "https://baserow.io/user-docs/configure-openid-connect-for-oauth-2-sso",
        "coin",
    ),
    (
        "taiga",
        "keycloak",
        "https://github.com/taigaio/taiga-contrib-oidc-auth",
        "check",
    ),
]

CHECK = "✅"
WIRED = "☑️"
COIN = "🪙"
CROSS = "❌"
DASH = "—"


def scan_framework_edges():
    """Derive infinito-native integration edges from each role's meta/services.yml."""
    edges = []
    for prefix in ("web-app-", "web-svc-"):
        for path in sorted(ROLES_DIR.glob(prefix + "*/meta/services.yml")):
            role = path.parent.parent.name
            entity = role[len(prefix) :]
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            seen = set()
            for line in lines:
                m = re.match(r"^([a-z0-9_]+):", line)
                if not m:
                    continue
                key = m.group(1)
                target = FRAMEWORK.get(key)
                if target and target != entity and target not in seen:
                    seen.add(target)
                    rel = f"../../roles/{role}/meta/services.yml"
                    edges.append((entity, target, rel, "wired"))
    return edges


def build():
    # Framework (infinito-native) edges first; curated upstream EDGES override
    # them so an explicit plugin link wins over the generic services.yml link.
    by_pair = {(s, d): (url, kind) for (s, d, url, kind) in scan_framework_edges()}
    by_pair.update({(s, d): (url, kind) for (s, d, url, kind) in EDGES})
    corner = "↓ row wires → col"

    def render_row(label, cells):
        # Repeat the row-label column every 10 columns for readability.
        out = [label]
        for j, cell in enumerate(cells):
            out.append(cell)
            if (j + 1) % 10 == 0 and (j + 1) < len(cells):
                out.append(label)
        return "| " + " | ".join(out) + " |"

    header = render_row(corner, ENTITIES)
    ncols = header.count("|") - 1
    sep = "|" + "---|" * ncols
    rows = [header, sep]
    for i, src in enumerate(ENTITIES):
        cells = []
        for dst in ENTITIES:
            if src == dst:
                cells.append(DASH)
            elif (src, dst) in by_pair:
                url, kind = by_pair[(src, dst)]
                sym = {"coin": COIN, "wired": WIRED}.get(kind, CHECK)
                cells.append(f"[{sym}]({url})")
            else:
                cells.append(CROSS)
        rows.append(render_row(f"**{src}**", cells))
        # Repeat the column header every 10 data rows for readability.
        if (i + 1) % 10 == 0 and (i + 1) < len(ENTITIES):
            rows.append(header)
    return "\n".join(rows)


HEADER = """# 027 - Integration Matrix

> Generated by [027-integration-matrix.gen.py](027-integration-matrix.gen.py). Do not edit by hand — edit the generator's `EDGES` map and re-run.

Companion artifact for [028-unified-addon-syntax.md](028-unified-addon-syntax.md).
Axes are the **entity names** of every `web-app-*` and `web-svc-*` role.
A cell marks whether the **row** role ships an addon/plugin that wires in the **column** role.

## Legend

| Symbol | Meaning |
|---|---|
| {wired} | Already wired via an infinito-native service flag in the row role's `meta/services.yml` (group-gated). Links to that declaration. |
| {check} | A verified upstream app↔app plugin exists but is not yet declared as an addon. Links to the plugin page. This is the backlog. |
| {coin} | Integration exists but is gated behind a commercial / paid tier. |
| {cross} | No known integration to wire these two. |
| {dash} | Same role (diagonal). |

Notes:
- The matrix is **directional**: the row hosts the plugin/flag. Bidirectional pairs (e.g. `nextcloud`↔`openproject`) carry a symbol in both cells, each linking to that side.
- {wired} edges are derived automatically by scanning every role's `meta/services.yml` for integration service keys (`sso`→keycloak, `matomo`→matomo, `prometheus`→prometheus, `email`→mailu, `dashboard`, `css`, `logout`, `cdn`, `coturn`, `collabora`, `onlyoffice`, `libretranslate`). `ldap`/`redis`/`mariadb` map to `svc-db-*` roles that are off these axes and are not shown.
- `→ keycloak` {wired} cells are the central `sso` service (requirement 021); a {check}/{coin} on `→ keycloak` instead means a role-local OIDC/SAML addon path beyond the central service.
- Native ActivityPub federation between fediverse roles (`mastodon`, `peertube`, `pixelfed`, `funkwhale`, `mobilizon`, `bookwyrm`, `socialhome`) needs **no plugin** and is therefore not a {check} edge unless an installable connector exists.

## Matrix

{matrix}
"""


def main():
    fw = scan_framework_edges()
    out = HEADER.format(
        check=CHECK, wired=WIRED, coin=COIN, cross=CROSS, dash=DASH, matrix=build()
    )
    path = Path(__file__).resolve().parent / "027-integration-matrix.md"
    path.write_text(out, encoding="utf-8")
    print(
        f"wrote {path} ({len(ENTITIES)}x{len(ENTITIES)} matrix, "
        f"{len(fw)} wired + {len(EDGES)} upstream edges)"
    )


if __name__ == "__main__":
    main()
