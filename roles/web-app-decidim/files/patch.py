"""Patches Decidim gem files to add OpenID Connect support.

Decidim 0.31 (Rails 7.2) removed `config/secrets.yml`; provider configuration
is sourced from runtime ENV vars instead. The patches below:

- Locate decidim-core gem dynamically (`decidim-core-*`) so any 0.3x version works.
- Register `:openid_connect` in `Decidim.omniauth_providers` at the top of
  decidim-core's omniauth.rb initializer. Decidim::User's
  `devise :omniauthable, omniauth_providers: Decidim::OmniauthProvider.available.keys`
  reads that registry, so registration must happen before the User model loads
  for Rails to generate the `user_openid_connect_omniauth_authorize_path`
  URL helper the homepage's `_omniauth_buttons.html.erb` partial calls.
- Inject an `openid_connect` provider registration into decidim-core's
  omniauth.rb initializer, gated on `ENV["OIDC_ENABLED"] == "true"`.
- Short-circuit the oauth icon helper so the login-box-line icon is returned
  for `:openid_connect` without hitting the (organization-bound) registry.
- Fix the omniauth registration form action URL: Decidim 0.31.3 passes
  ``resource_name`` (``:user``) as a positional arg to
  ``omniauth_registrations_path``; Rails then treats it as a ``:format`` on
  the formatless route, yielding ``/omniauth_registrations.user`` which
  returns 406 and silently prevents user creation.
"""

import glob
import re
from pathlib import Path

OMNIAUTH_REGISTRATION = r"""if ENV["OIDC_ENABLED"].to_s == "true"
  Decidim.omniauth_providers[:openid_connect] = {
    enabled: true,
    icon: "login-box-line"
  }
end

"""


OMNIAUTH_INJECTION = (
    "\n" + (Path(__file__).parent / "ruby" / "omniauth_provider.rb").read_text()
)


def patch_omniauth_rb(content: str) -> str:
    """Register openid_connect in Decidim.omniauth_providers and add provider builder call."""
    if 'ENV["OIDC_ENABLED"]' in content:
        return content
    content = (
        re.sub(r"(  end\nend\s*)$", OMNIAUTH_INJECTION + r"\1", content.rstrip()) + "\n"
    )
    return OMNIAUTH_REGISTRATION + content


def patch_omniauth_helper_rb(content: str) -> str:
    """Return login-box-line icon for openid_connect to avoid registry lookup failure."""
    if "provider.to_sym == :openid_connect" in content:
        return content
    return content.replace(
        "    def oauth_icon(provider)",
        '    def oauth_icon(provider)\n      return icon("login-box-line") if provider.to_sym == :openid_connect',
    )


def patch_omniauth_registration_new_erb(content: str) -> str:
    """Drop the positional ``resource_name`` arg from the form URL helper.

    Decidim 0.31.3 renders ``decidim.omniauth_registrations_path(resource_name)``.
    The named route has no dynamic segments so Rails binds the symbol to
    ``:format``, producing ``/omniauth_registrations.user`` which 406s before
    the controller runs.
    """
    return content.replace(
        "decidim.omniauth_registrations_path(resource_name)",
        "decidim.omniauth_registrations_path",
    )


def find_decidim_core_file(relative_path: str) -> str:
    """Resolve a file inside the installed decidim-core gem, version-agnostic."""
    pattern = f"/usr/local/bundle/gems/decidim-core-*/{relative_path}"
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No decidim-core gem found matching {pattern}")
    return matches[-1]


if __name__ == "__main__":
    omniauth_path = find_decidim_core_file("config/initializers/omniauth.rb")
    with Path(omniauth_path).open() as f:
        content = f.read()
    with Path(omniauth_path).open("w") as f:
        f.write(patch_omniauth_rb(content))
    print(f"{omniauth_path} patched")

    helper_path = find_decidim_core_file("app/helpers/decidim/omniauth_helper.rb")
    with Path(helper_path).open() as f:
        content = f.read()
    with Path(helper_path).open("w") as f:
        f.write(patch_omniauth_helper_rb(content))
    print(f"{helper_path} patched")

    for view_relative in (
        "app/views/decidim/devise/omniauth_registrations/new.html.erb",
        "app/views/decidim/devise/omniauth_registrations/new_tos_fields.html.erb",
    ):
        registration_view = find_decidim_core_file(view_relative)
        with Path(registration_view).open() as f:
            content = f.read()
        with Path(registration_view).open("w") as f:
            f.write(patch_omniauth_registration_new_erb(content))
        print(f"{registration_view} patched")
