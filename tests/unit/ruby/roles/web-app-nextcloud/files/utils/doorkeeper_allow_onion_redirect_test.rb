# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class DoorkeeperAllowOnionRedirectTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-nextcloud/files/ruby/utils/doorkeeper_allow_onion_redirect.rb",
    __dir__
  )
  BASE_URLS = ["https://cloud.example.org", "http://cloud.#{"a" * 56}.onion"].freeze
  HARNESS = <<~RUBY
    require "json"
    require "uri"

    module Doorkeeper
      class Config
        attr_reader :force_ssl_in_redirect_uri

        def initialize(force_ssl)
          @force_ssl_in_redirect_uri = force_ssl
        end
      end

      def self.config
        @config ||= Config.new(JSON.parse(ENV.fetch("PREVIOUS_FORCE_SSL")))
      end
    end

    load ARGV.shift
    force_ssl = Doorkeeper.config.force_ssl_in_redirect_uri
    puts JSON.generate(ARGV.to_h { |url| [url, force_ssl.call(URI.parse(url))] })
  RUBY

  # @param previous [Boolean] force_ssl_in_redirect_uri before the override
  # @param base_urls [Array<String>, nil] NC_REDIRECT_BASE_URLS, unset when nil
  # @param uris [Array<String>] redirect URIs to check
  # @return [Array(Hash, Process::Status)] whether each URI must use TLS, and the exit
  def forced(previous, base_urls, *uris)
    env = {
      "PREVIOUS_FORCE_SSL" => JSON.generate(previous),
      "NC_REDIRECT_BASE_URLS" => base_urls && JSON.generate(base_urls)
    }
    stdout, _stderr, status = Open3.capture3(env, RbConfig.ruby, "-e", HARNESS, SCRIPT, *uris)
    [status.success? ? JSON.parse(stdout) : {}, status]
  end

  def test_a_plaintext_sibling_of_nextcloud_may_redirect_without_tls
    uri = "#{BASE_URLS[1]}/index.php/apps/integration_openproject/oauth-redirect"
    result, status = forced(true, BASE_URLS, uri)

    assert_predicate status, :success?
    assert_equal({ uri => false }, result)
  end

  def test_a_foreign_onion_host_keeps_the_tls_requirement
    uri = "http://intruder.#{"b" * 56}.onion/apps/integration_openproject/oauth-redirect"
    result, status = forced(true, BASE_URLS, uri)

    assert_predicate status, :success?
    assert_equal({ uri => true }, result)
  end

  def test_the_tls_sibling_keeps_the_previous_setting
    uri = "http://cloud.example.org/apps/integration_openproject/oauth-redirect"

    assert_equal({ uri => true }, forced(true, BASE_URLS, uri).first)
    assert_equal({ uri => false }, forced(false, BASE_URLS, uri).first)
  end

  def test_a_missing_base_url_list_fails_the_provisioning
    _result, status = forced(true, nil, "#{BASE_URLS[1]}/x")

    refute_predicate status, :success?
  end
end
