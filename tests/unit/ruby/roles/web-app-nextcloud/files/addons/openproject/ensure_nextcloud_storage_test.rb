# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class NextcloudOpenProjectRedirectUrisTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../../roles/web-app-nextcloud/files/ruby/addons/openproject/ensure_nextcloud_storage.rb",
    __dir__
  )

  CLEARNET = "https://next.example.org"
  ONION = "http://next.#{'a' * 56}.onion"

  REDIRECT_URIS = [CLEARNET, ONION].flat_map do |base_url|
    [
      "#{base_url}/apps/integration_openproject/oauth-redirect",
      "#{base_url}/index.php/apps/integration_openproject/oauth-redirect",
    ]
  end.freeze

  PRELUDE = <<~'RUBY'
    require "json"

    PROVISION_INPUT = JSON.parse(ENV.fetch("PROVISION_INPUT"))

    class String
      def present? = !strip.empty?
    end

    Administrator = Struct.new(:id)

    class User
      def self.where(**_conditions) = [Administrator.new(1)]
    end

    class FakeApplication
      attr_reader :redirect_uri

      def initialize(redirect_uri)
        @redirect_uri = redirect_uri
      end

      def uid = "openproject-client"

      def plaintext_secret = "openproject-secret"

      def secret_matches?(_secret) = true

      def update!(redirect_uri:)
        @redirect_uri = redirect_uri
        puts JSON.generate(["updated", redirect_uri.split("\n")])
      end
    end

    module Storages
      class NextcloudStorage
        attr_accessor :id, :host, :oauth_application, :oauth_client, :authentication_method

        def self.find_by(**_conditions)
          registered = ENV.fetch("REGISTERED_REDIRECT_URI")
          return nil if registered.empty?

          storage = new(name: "Nextcloud", host: PROVISION_INPUT.fetch("nextcloud_host"), creator: nil)
          storage.id = 42
          storage.oauth_application = FakeApplication.new(registered)
          storage
        end

        def initialize(name:, host:, creator:)
          @name = name
          @host = host
          @creator = creator
        end

        def save!
          @id = 42
        end

        def update!(host:)
          @host = host
        end

        def reload = self
      end
    end

    class ServiceResult; end

    module OAuth
      module Applications
        class CreateService
          def initialize(user:); end

          def call(name:, redirect_uri:, scopes:, confidential:, owner:, integration:)
            puts JSON.generate(["created", redirect_uri.split("\n")])
            integration.oauth_application = FakeApplication.new(redirect_uri)
          end
        end
      end
    end
  RUBY

  # @param registered [String] redirect_uri of the OAuth application OpenProject already holds, empty for none
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def provision(registered:)
    stdout, stderr, status = Open3.capture3(
      {
        "PROVISION_INPUT" => {
          "nextcloud_host" => "#{CLEARNET}/",
          "nextcloud_base_urls" => ["#{CLEARNET}/", ONION],
          "storage_name" => "Nextcloud",
          "nc_op_client_secret" => "nextcloud-held-secret",
          "rotate_op_secret" => false,
          "nc_oauth_client_id" => "",
          "nc_oauth_client_secret" => "",
        }.to_json,
        "REGISTERED_REDIRECT_URI" => registered,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_a_new_oauth_application_accepts_every_network_base_url
    lines, stderr, status = provision(registered: "")

    assert_predicate status, :success?, stderr
    assert_equal ["created", REDIRECT_URIS], JSON.parse(lines.first)
  end

  def test_an_existing_oauth_application_is_widened_to_every_network_base_url
    lines, stderr, status = provision(registered: REDIRECT_URIS.first(2).join("\n"))

    assert_predicate status, :success?, stderr
    assert_equal ["updated", REDIRECT_URIS], JSON.parse(lines.first)
  end
end
