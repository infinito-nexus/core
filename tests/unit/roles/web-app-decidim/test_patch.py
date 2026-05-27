"""Unit tests for roles/web-app-decidim/files/patch.py."""

from __future__ import annotations

import sys
import unittest

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT / "roles" / "web-app-decidim" / "files"))

from patch import patch_omniauth_helper_rb, patch_omniauth_rb

OMNIAUTH_RB_FIXTURE = """\
Decidim::Auth.setup do |config|
  config.providers = []
  end
end
"""

OMNIAUTH_HELPER_FIXTURE = """\
module Decidim
  module OmniauthHelper
    def oauth_icon(provider)
      info = current_organization.enabled_omniauth_providers[provider.to_sym]
    end
  end
end
"""


class TestPatchOmniauthRb(unittest.TestCase):
    def test_inserts_env_gated_provider(self):
        result = patch_omniauth_rb(OMNIAUTH_RB_FIXTURE)
        self.assertIn('ENV["OIDC_ENABLED"].to_s == "true"', result)
        self.assertIn("omniauth_openid_connect", result)
        self.assertIn("redirect_uri", result)

    def test_registers_provider_in_decidim_registry(self):
        result = patch_omniauth_rb(OMNIAUTH_RB_FIXTURE)
        self.assertIn("Decidim.omniauth_providers[:openid_connect]", result)
        # Registration must precede the builder block so Devise picks it up
        # before Decidim::User loads.
        registry_idx = result.index("Decidim.omniauth_providers[:openid_connect]")
        builder_idx = result.index("Decidim::Auth.setup")
        self.assertLess(registry_idx, builder_idx)

    def test_closes_correctly(self):
        result = patch_omniauth_rb(OMNIAUTH_RB_FIXTURE)
        self.assertTrue(result.rstrip().endswith("end"))

    def test_is_idempotent(self):
        once = patch_omniauth_rb(OMNIAUTH_RB_FIXTURE)
        twice = patch_omniauth_rb(once)
        self.assertEqual(once, twice)


class TestPatchOmniauthHelperRb(unittest.TestCase):
    def test_adds_early_return(self):
        result = patch_omniauth_helper_rb(OMNIAUTH_HELPER_FIXTURE)
        self.assertIn(
            'return icon("login-box-line") if provider.to_sym == :openid_connect',
            result,
        )

    def test_preserves_original_method(self):
        result = patch_omniauth_helper_rb(OMNIAUTH_HELPER_FIXTURE)
        self.assertIn("current_organization.enabled_omniauth_providers", result)

    def test_is_idempotent(self):
        once = patch_omniauth_helper_rb(OMNIAUTH_HELPER_FIXTURE)
        twice = patch_omniauth_helper_rb(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
