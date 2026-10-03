# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class EnsureGitlabWebhookTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../../roles/web-app-openproject/files/ruby/addons/gitlab/ensure_gitlab_webhook.rb",
    __dir__
  )

  BASE_ENV = {
    "OPENPROJECT_GITLAB_BOT_LOGIN" => "infinito-gitlab",
    "OPENPROJECT_GITLAB_BOT_MAIL" => "gitlab@example.org",
    "OPENPROJECT_GITLAB_BOT_PASSWORD" => "s3cret-password",
    "OPENPROJECT_GITLAB_TOKEN_NAME" => "infinito-gitlab-webhook",
    "OPENPROJECT_GITLAB_WEBHOOK_SECRET" => "a" * 64
  }.freeze

  # @param user_exists [Boolean] whether User.find_by resolves the bot
  # @param token_owner [Integer, nil] user id the held token resolves to, nil for unknown
  # @param settings [Hash] what Setting already holds
  # @return [String] ruby source
  def prelude(user_exists:, token_owner:, settings:)
    <<~RUBY
      $state = { destroyed: false, created_token: false, saved: false, settings: #{settings.inspect} }

      class FakeUser
        attr_accessor :login, :firstname, :lastname, :mail, :admin, :language,
                      :password, :password_confirmation
        attr_reader :id
        def initialize(**attrs)
          attrs.each { |k, v| public_send("\#{k}=", v) }
          @id = 7
        end
        def activate; end
        def save!; $state[:saved] = true; end
      end

      module User
        def self.find_by(login:)
          #{user_exists} ? FakeUser.new(login: login) : nil
        end
        def self.new(**attrs) = FakeUser.new(**attrs)
      end

      FakeToken = Struct.new(:user_id, :plain_value)

      module Token
        module API
          def self.find_by_plaintext_value(_value)
            #{token_owner.inspect}.nil? ? nil : FakeToken.new(#{token_owner.inspect}, nil)
          end
          def self.where(user_id:) = Relation.new
          def self.create!(user:, token_name:)
            $state[:created_token] = true
            $state[:token_name] = token_name
            FakeToken.new(user.id, "minted-token-value-0123456789")
          end
          class Relation
            def destroy_all; $state[:destroyed] = true; end
          end
        end
      end

      module Setting
        def self.plugin_openproject_gitlab_integration = $state[:settings]
        def self.plugin_openproject_gitlab_integration=(value)
          $state[:settings] = value
        end
      end

      at_exit { warn "STATE=" + $state.to_json }
      require "json"
    RUBY
  end

  def run_script(env: {}, **stub)
    source = "#{prelude(**stub)}\nload ARGV[0]"
    Open3.capture3(BASE_ENV.merge(env), RbConfig.ruby, "-e", source, SCRIPT)
  end

  def payload(stdout)
    JSON.parse(stdout[/\{.*\}/])
  end

  def test_a_first_run_creates_the_bot_mints_a_token_and_reports_changed
    stdout, stderr, status = run_script(
      user_exists: false, token_owner: nil, settings: {}
    )

    assert_predicate status, :success?, stderr
    assert_includes stdout, "CHANGED"
    assert_equal "minted-token-value-0123456789", payload(stdout)["api_token"]
    assert_includes stderr, '"saved":true'
    assert_includes stderr, '"created_token":true'
    assert_includes stderr, '"token_name":"infinito-gitlab-webhook"'
  end

  def test_a_converged_run_reuses_the_held_token_and_reports_no_change
    settled = { "gitlab_user_id" => 7, "webhook_secret" => "a" * 64 }
    stdout, stderr, status = run_script(
      env: { "OPENPROJECT_GITLAB_API_TOKEN" => "held-token-value-9876543210" },
      user_exists: true, token_owner: 7, settings: settled
    )

    assert_predicate status, :success?, stderr
    refute_includes stdout, "CHANGED"
    assert_equal "held-token-value-9876543210", payload(stdout)["api_token"]
    assert_includes stderr, '"created_token":false'
  end

  def test_a_token_belonging_to_another_user_is_replaced
    settled = { "gitlab_user_id" => 7, "webhook_secret" => "a" * 64 }
    stdout, stderr, status = run_script(
      env: { "OPENPROJECT_GITLAB_API_TOKEN" => "held-token-value-9876543210" },
      user_exists: true, token_owner: 99, settings: settled
    )

    assert_predicate status, :success?, stderr
    assert_includes stdout, "CHANGED"
    assert_equal "minted-token-value-0123456789", payload(stdout)["api_token"]
    assert_includes stderr, '"destroyed":true'
  end

  def test_a_changed_webhook_secret_rewrites_the_setting
    stale = { "gitlab_user_id" => 7, "webhook_secret" => "b" * 64 }
    stdout, stderr, status = run_script(
      env: { "OPENPROJECT_GITLAB_API_TOKEN" => "held-token-value-9876543210" },
      user_exists: true, token_owner: 7, settings: stale
    )

    assert_predicate status, :success?, stderr
    assert_includes stdout, "CHANGED"
    assert_includes stderr, "a" * 64
  end

  def test_a_missing_mandatory_variable_fails_loudly
    env = BASE_ENV.to_h { |key, _| [key, nil] }
    _stdout, stderr, status = run_script(
      env: env, user_exists: true, token_owner: 7, settings: {}
    )

    refute_predicate status, :success?
    assert_includes stderr, "KeyError"
  end
end
