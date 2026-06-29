"""Patches Decidim gem and app files for OpenID Connect and S3 storage.

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
- Add ``force_path_style: true`` to the ``s3`` service in
  ``config/storage.yml``. The upstream storage.yml omits it, so the AWS SDK
  defaults to virtual-host addressing; SeaweedFS only serves path-style, so
  ActiveStorage must force it. ActiveStorage::Service::S3Service forwards any
  extra storage.yml key straight to ``Aws::S3::Resource.new`` (and thus the
  S3 client), so the flag takes effect without further wiring.
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


def patch_active_storage_env_rb(content: str) -> str:
    """Read STORAGE_PROVIDER for ActiveStorage like production.rb does.

    ``config/environments/development.rb`` hardcodes
    ``config.active_storage.service = :local``, so a deployment running with
    ``RAILS_ENV=development`` writes uploads to the local Disk service and never
    reaches the configured S3 (SeaweedFS) bucket. Mirror production.rb so the
    service follows ``STORAGE_PROVIDER`` in every environment.
    """
    target = "config.active_storage.service = :local"
    replacement = 'config.active_storage.service = Decidim::Env.new("STORAGE_PROVIDER", "local").to_s'
    if replacement in content or target not in content:
        return content
    return content.replace(target, replacement)


def patch_storage_yml(content: str) -> str:
    """Force path-style addressing for the s3 service so SeaweedFS is reachable."""
    if "force_path_style" in content:
        return content
    return re.sub(
        r"(^s3:\n[\s\S]*?^[ \t]+service: S3\n)",
        r"\1  force_path_style: true\n",
        content,
        count=1,
        flags=re.MULTILINE,
    )


def find_app_file(relative_path: str) -> str:
    """Resolve a file inside the generated Decidim app at /code."""
    return f"/code/{relative_path}"


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

    dev_env_path = find_app_file("config/environments/development.rb")
    with Path(dev_env_path).open() as f:
        content = f.read()
    with Path(dev_env_path).open("w") as f:
        f.write(patch_active_storage_env_rb(content))
    print(f"{dev_env_path} patched")

    storage_path = find_app_file("config/storage.yml")
    with Path(storage_path).open() as f:
        content = f.read()
    with Path(storage_path).open("w") as f:
        f.write(patch_storage_yml(content))
    print(f"{storage_path} patched")
