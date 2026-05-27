import importlib.util
import unittest

from ansible.errors import AnsibleFilterError

from . import PROJECT_ROOT


def _load_social_module():
    """
    Load the social.py filter plugin module from the roles/web-app-dashboard path.

    This helper allows the test to be executed from the repository root
    without requiring the roles directory to be a Python package.
    """
    social_path = (
        PROJECT_ROOT / "roles" / "web-app-dashboard" / "filter_plugins" / "social.py"
    )

    if not social_path.is_file():
        raise RuntimeError(f"Could not find social.py at expected path: {social_path}")

    spec = importlib.util.spec_from_file_location("social", social_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_social = _load_social_module()
fediverse_url = _social.fediverse_url


class TestFediverseUrlFilter(unittest.TestCase):
    """Unit tests for the fediverse_url filter function."""

    def test_valid_handle_with_leading_at_default_protocol(self):
        """Handles '@user@instance.tld' correctly using default https protocol."""
        handle = "@alice@example.social"
        result = fediverse_url(handle)
        self.assertEqual(result, "https://example.social/@alice")

    def test_valid_handle_without_leading_at_custom_protocol(self):
        """Handles 'user@instance.tld' correctly when a custom protocol is provided."""
        handle = "bob@example.com"
        result = fediverse_url(handle, protocol="http")
        self.assertEqual(result, "http://example.com/@bob")

    def test_handles_whitespace_and_trims_input(self):
        """Strips surrounding whitespace from the handle before processing."""
        handle = "   @charlie@example.net   "
        result = fediverse_url(handle)
        self.assertEqual(result, "https://example.net/@charlie")

    def test_empty_string_returns_empty_string(self):
        """Returns an empty string if the handle is an empty string."""
        self.assertEqual(fediverse_url(""), "")

    def test_none_returns_empty_string(self):
        """Returns an empty string if the handle is None."""
        self.assertEqual(fediverse_url(None), "")

    def test_invalid_handle_without_at_raises_error(self):
        """Raises AnsibleFilterError when there is no separator '@'."""
        with self.assertRaises(AnsibleFilterError):
            fediverse_url("not-a-valid-handle")

    def test_invalid_handle_with_three_parts_raises_error(self):
        """Raises AnsibleFilterError when the handle contains more than one '@' separator."""
        with self.assertRaises(AnsibleFilterError):
            fediverse_url("too@many@parts.example")

    def test_invalid_handle_with_empty_username_raises_error(self):
        """Raises AnsibleFilterError when the username part is missing."""
        with self.assertRaises(AnsibleFilterError):
            fediverse_url("@@example.org")

    def test_invalid_handle_with_empty_host_raises_error(self):
        """Raises AnsibleFilterError when the host part is missing."""
        with self.assertRaises(AnsibleFilterError):
            fediverse_url("@user@")

    def test_custom_path_prefix_is_respected(self):
        """Respects a custom path prefix instead of the default '@'."""
        handle = "@dana@example.host"
        result = fediverse_url(handle, protocol="https", path_prefix="u/")
        self.assertEqual(result, "https://example.host/u/dana")


if __name__ == "__main__":
    unittest.main()
