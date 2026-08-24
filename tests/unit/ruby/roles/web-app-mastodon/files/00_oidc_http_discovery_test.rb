# frozen_string_literal: true

require "minitest/autorun"
require "open3"

class OidcHttpDiscoveryTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-mastodon/files/ruby/00_oidc_http_discovery.rb",
    __dir__
  )

  # Loads the initializer in a child ruby and reports whether it pulled in SWD.
  #
  # @param env [Hash] environment for the child process
  # @return [Array(String, String, Process::Status)] stdout, stderr and status
  def load_with(env)
    Open3.capture3(env, RbConfig.ruby, "-e", "load ARGV[0]; puts defined?(SWD).inspect", SCRIPT)
  end

  def test_disabled_oidc_leaves_url_building_untouched
    stdout, _stderr, status = load_with("OIDC_ENABLED" => nil, "OIDC_ISSUER" => nil)

    assert_predicate status, :success?
    assert_equal "nil", stdout.strip
  end

  def test_https_issuer_leaves_url_building_untouched
    stdout, _stderr, status = load_with(
      "OIDC_ENABLED" => "true", "OIDC_ISSUER" => "https://auth.example.org"
    )

    assert_predicate status, :success?
    assert_equal "nil", stdout.strip
  end

  def test_enabled_without_http_issuer_leaves_url_building_untouched
    stdout, _stderr, status = load_with("OIDC_ENABLED" => "true", "OIDC_ISSUER" => nil)

    assert_predicate status, :success?
    assert_equal "nil", stdout.strip
  end

  def test_http_issuer_reaches_the_downgrade_branch
    _stdout, stderr, status = load_with(
      "OIDC_ENABLED" => "true", "OIDC_ISSUER" => "http://auth.example.org"
    )

    refute_predicate status, :success?
    assert_match(/swd/, stderr)
  end
end
