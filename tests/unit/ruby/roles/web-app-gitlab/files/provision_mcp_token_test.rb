# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class GitlabProvisionMcpTokenTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-gitlab/files/ruby/provision_mcp_token.rb",
    __dir__
  )

  RAILS_RUNNER_STDIN = 'eval($stdin.read, TOPLEVEL_BINDING, "stdin")'

  AUTHORIZED_CREATE = "Users::AuthorizedCreateService.new("
  SIGNUP_CREATE = "Users::CreateService.new("

  PRELUDE = <<~RUBY
    require "date"
    require "json"

    EVENTS = []
    at_exit { STDERR.puts(JSON.generate(EVENTS)) }

    class Date
      def self.current
        new(2026, 1, 1)
      end

      def advance(days:)
        self + days
      end
    end

    module Gitlab
      module Access
        class AccessDeniedError < StandardError; end
      end
    end

    class StubToken
      attr_reader :name

      def initialize(name)
        @name = name
        @revoked = false
      end

      def revoked?
        @revoked
      end

      def revoke!
        @revoked = true
        EVENTS << "revoked \#{name}"
      end

      def token
        "stub-token-\#{name}"
      end
    end

    class StubRelation
      def initialize(tokens)
        @tokens = tokens
      end

      def find_each(&block)
        @tokens.each(&block)
      end
    end

    class StubTokens
      def initialize(names)
        @tokens = names.map { |name| StubToken.new(name) }
      end

      def active
        self
      end

      def where(name:)
        StubRelation.new(@tokens.select { |token| token.name == name && !token.revoked? })
      end

      def create!(name:, scopes:, expires_at:)
        EVENTS << "created \#{name} \#{scopes.join(',')} \#{expires_at.iso8601}"
        StubToken.new(name).tap { |token| @tokens << token }
      end
    end

    class StubUser
      attr_reader :username, :personal_access_tokens

      def initialize(username, admin, tokens)
        @username = username
        @admin = admin
        @personal_access_tokens = StubTokens.new(tokens)
      end

      def admin?
        @admin
      end
    end

    class User
      ALL = JSON.parse(ENV.fetch("STUB_USERS")).map do |row|
        StubUser.new(row.fetch("username"), row.fetch("admin"), row.fetch("tokens"))
      end

      def self.find_by_username(username)
        ALL.find { |user| user.username == username }
      end
    end

    module Organizations
      class Organization
        DEFAULT_ORGANIZATION_ID = 1
        Default = Struct.new(:id)

        def self.default_organization
          Default.new(DEFAULT_ORGANIZATION_ID)
        end
      end
    end

    class StubResult
      def success?
        true
      end
    end

    module Users
      class CreateService
        def initialize(current_user, params)
          @current_user = current_user
          @params = params
        end

        def execute
          raise Gitlab::Access::AccessDeniedError
        end

        private

        def build
          User::ALL << StubUser.new(@params.fetch(:username), false, [])
          picked = @params.slice(:username, :skip_confirmation, :organization_id)
          EVENTS << "\#{self.class.name} current_user=\#{@current_user.inspect} \#{picked.to_json}"
          StubResult.new
        end
      end

      class AuthorizedCreateService < CreateService
        def execute
          build
        end
      end
    end
  RUBY

  # @param source [String] the Ruby program `rails runner -` evaluates
  # @param users [Array<Hash>] accounts the stubbed User model holds
  # @return [Array(String, String, Process::Status)] stdout, stderr and status
  def mint(source: File.read(SCRIPT), users: [])
    Open3.capture3(
      {
        "STUB_USERS" => users.to_json,
        "GITLAB_MCP_TOKEN_NAME" => "infinito-mcp",
        "GITLAB_MCP_TOKEN_OWNER" => "mcp-web-app-gitlab",
        "GITLAB_MCP_TOKEN_OWNER_NAME" => "Infinito MCP",
        "GITLAB_MCP_TOKEN_OWNER_EMAIL" => "mcp-web-app-gitlab@example.invalid",
        "GITLAB_MCP_TOKEN_OWNER_PASSWORD" => "stub owner secret",
        "GITLAB_MCP_TOKEN_LIFETIME_DAYS" => "364",
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\n#{RAILS_RUNNER_STDIN}",
      stdin_data: source
    )
  end

  # @param stderr [String] stderr of a successful run
  # @return [Array<String>] the events the stubs recorded
  def events(stderr)
    JSON.parse(stderr.lines.last)
  end

  def test_a_missing_owner_is_created_while_sign_up_is_off
    stdout, stderr, status = mint

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED\nstub-token-infinito-mcp\n", stdout
    assert_equal [
      'Users::AuthorizedCreateService current_user=nil ' \
      '{"username":"mcp-web-app-gitlab","skip_confirmation":true,"organization_id":1}',
      "created infinito-mcp mcp 2026-12-31",
    ], events(stderr)
  end

  def test_the_sign_up_path_is_refused_once_sign_up_is_off
    source = File.read(SCRIPT)
    assert_includes source, AUTHORIZED_CREATE

    stdout, stderr, status = mint(source: source.sub(AUTHORIZED_CREATE, SIGNUP_CREATE))

    refute_predicate status, :success?
    assert_match(/Gitlab::Access::AccessDeniedError/, stderr)
    assert_empty stdout
  end

  def test_an_existing_owner_gets_a_fresh_token_without_a_create
    stdout, stderr, status = mint(
      users: [{ "username" => "mcp-web-app-gitlab", "admin" => false, "tokens" => ["infinito-mcp", "other"] }]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED\nstub-token-infinito-mcp\n", stdout
    assert_equal ["revoked infinito-mcp", "created infinito-mcp mcp 2026-12-31"], events(stderr)
  end
end
