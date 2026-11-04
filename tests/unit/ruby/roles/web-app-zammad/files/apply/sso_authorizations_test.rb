# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class ZammadSsoAuthorizationsTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-zammad/files/ruby/apply/sso_authorizations.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    require "json"

    module UserInfo
      def self.current_user_id=(_id); end
    end

    FakeUser = Struct.new(:id, :email)

    class User
      USERS = JSON.parse(ENV.fetch("FAKE_USERS"))

      def self.find_by(login:)
        row = USERS[login]
        row && FakeUser.new(row.fetch("id"), row.fetch("email"))
      end
    end

    class Authorization
      STORE = JSON.parse(ENV.fetch("FAKE_AUTHORIZATIONS"))

      def self.where(provider:, user_id:)
        Struct.new(:uids) { def pluck(_column) = uids }.new(
          STORE.select { |row| row["provider"] == provider && row["user_id"] == user_id }.map { |row| row["uid"] }
        )
      end

      def self.find_by(provider:, uid:)
        STORE.find { |row| row["provider"] == provider && row["uid"] == uid }
      end

      def self.create!(provider:, uid:, username:, user_id:)
        puts "created \#{provider} \#{uid} \#{username} -> \#{user_id}"
      end
    end
  RUBY

  ALICE = { "username" => "Alice", "email" => "alice@example.org", "emailVerified" => true, "id" => "kc-alice" }.freeze

  # @param directory [Array<Hash>] keycloak_directory_users as the deploy passes it
  # @param users [Hash{String=>Hash}] local Zammad users by login
  # @param authorizations [Array<Hash>] existing Authorization rows
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def bind(directory:, users:, authorizations: [])
    stdout, stderr, status = Open3.capture3(
      {
        "ZAMMAD_SSO_DIRECTORY_USERS" => directory.to_json,
        "FAKE_USERS" => users.to_json,
        "FAKE_AUTHORIZATIONS" => authorizations.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_an_account_with_the_same_login_and_verified_email_is_authorized
    lines, stderr, status = bind(
      directory: [ALICE],
      users: { "alice" => { "id" => 7, "email" => "ALICE@example.org" } }
    )

    assert_predicate status, :success?, stderr
    assert_equal ["created openid_connect alice alice -> 7", "changed"], lines
  end

  def test_an_unverified_keycloak_email_is_skipped_by_login
    lines, stderr, status = bind(
      directory: [ALICE.merge("emailVerified" => false)],
      users: { "alice" => { "id" => 7, "email" => "alice@example.org" } }
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the Keycloak email is not verified", "ok"], lines
  end

  def test_a_different_local_email_is_skipped_without_printing_an_address
    lines, stderr, status = bind(
      directory: [ALICE],
      users: { "alice" => { "id" => 7, "email" => "other@example.org" } }
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the Zammad email differs from the Keycloak email", "ok"], lines
    refute_match(/@/, lines.join("\n"))
  end

  def test_an_account_linked_to_another_identity_is_never_rebound
    lines, stderr, status = bind(
      directory: [ALICE],
      users: { "alice" => { "id" => 7, "email" => "alice@example.org" } },
      authorizations: [{ "provider" => "openid_connect", "uid" => "alice-old", "user_id" => 7 }]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the account is linked to another identity", "ok"], lines
  end

  def test_an_identity_held_by_another_account_is_never_moved
    lines, stderr, status = bind(
      directory: [ALICE],
      users: { "alice" => { "id" => 7, "email" => "alice@example.org" } },
      authorizations: [{ "provider" => "openid_connect", "uid" => "alice", "user_id" => 9 }]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the identity is linked to another account", "ok"], lines
  end

  def test_an_account_already_authorized_is_left_alone
    lines, stderr, status = bind(
      directory: [ALICE],
      users: { "alice" => { "id" => 7, "email" => "alice@example.org" } },
      authorizations: [{ "provider" => "openid_connect", "uid" => "alice", "user_id" => 7 }]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["ok"], lines
  end
end
