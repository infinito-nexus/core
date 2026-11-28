# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class MastodonSsoIdentitiesTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-mastodon/files/ruby/ensure/sso_identities.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    require "json"

    FakeUser = Struct.new(:id, :email)

    class Account
      USERS = JSON.parse(ENV.fetch("FAKE_ACCOUNTS"))

      def self.find_local(username)
        row = USERS[username.downcase]
        row && Struct.new(:user).new(FakeUser.new(row.fetch("id"), row.fetch("email")))
      end
    end

    class Identity
      STORE = JSON.parse(ENV.fetch("FAKE_IDENTITIES"))

      attr_accessor :provider, :uid, :user_id

      def initialize(provider:, uid:, user_id: nil)
        @provider = provider
        @uid = uid
        @user_id = user_id
      end

      def self.rows
        STORE.map { |row| new(provider: row["provider"], uid: row["uid"], user_id: row["user_id"]) }
      end

      def self.where(provider:, user_id:)
        Struct.new(:uids) { def pluck(_column) = uids }.new(
          rows.select { |row| row.provider == provider && row.user_id == user_id }.map(&:uid)
        )
      end

      def self.find_by(provider:, uid:)
        rows.find { |row| row.provider == provider && row.uid == uid }
      end

      def save!
        puts "saved \#{provider} \#{uid} -> \#{user_id}"
      end
    end
  RUBY

  ALICE = { "username" => "alice", "email" => "alice@example.org", "emailVerified" => true, "id" => "kc-alice" }.freeze

  # @param directory [Array<Hash>] keycloak_directory_users as the deploy passes it
  # @param accounts [Hash{String=>Hash}] local Mastodon users by lower-case username
  # @param identities [Array<Hash>] existing Identity rows
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def bind(directory:, accounts:, identities: [])
    stdout, stderr, status = Open3.capture3(
      {
        "MASTODON_SSO_DIRECTORY_USERS" => directory.to_json,
        "FAKE_ACCOUNTS" => accounts.to_json,
        "FAKE_IDENTITIES" => identities.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_an_account_with_the_same_username_and_verified_email_is_bound
    lines, stderr, status = bind(
      directory: [ALICE],
      accounts: { "alice" => { "id" => 7, "email" => "Alice@Example.org" } }
    )

    assert_predicate status, :success?, stderr
    assert_equal ["saved openid_connect alice -> 7", "changed"], lines
  end

  def test_an_unverified_keycloak_email_is_skipped_by_name
    lines, stderr, status = bind(
      directory: [ALICE.merge("emailVerified" => false)],
      accounts: { "alice" => { "id" => 7, "email" => "alice@example.org" } }
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the Keycloak email is not verified", "ok"], lines
  end

  def test_a_different_local_email_is_skipped_without_printing_an_address
    lines, stderr, status = bind(
      directory: [ALICE],
      accounts: { "alice" => { "id" => 7, "email" => "someone-else@example.org" } }
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the Mastodon email differs from the Keycloak email", "ok"], lines
    refute_match(/@/, lines.join("\n"))
  end

  def test_an_account_linked_to_another_identity_is_never_rebound
    lines, stderr, status = bind(
      directory: [ALICE],
      accounts: { "alice" => { "id" => 7, "email" => "alice@example.org" } },
      identities: [{ "provider" => "openid_connect", "uid" => "alice-old", "user_id" => 7 }]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the account is linked to another identity", "ok"], lines
  end

  def test_an_identity_held_by_another_account_is_never_moved
    lines, stderr, status = bind(
      directory: [ALICE],
      accounts: { "alice" => { "id" => 7, "email" => "alice@example.org" } },
      identities: [{ "provider" => "openid_connect", "uid" => "alice", "user_id" => 9 }]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["skipped alice: the identity is linked to another account", "ok"], lines
  end

  def test_an_account_already_bound_to_its_identity_is_left_alone
    lines, stderr, status = bind(
      directory: [ALICE],
      accounts: { "alice" => { "id" => 7, "email" => "alice@example.org" } },
      identities: [{ "provider" => "openid_connect", "uid" => "alice", "user_id" => 7 }]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["ok"], lines
  end

  def test_a_keycloak_user_without_a_local_account_creates_nothing
    lines, stderr, status = bind(directory: [ALICE], accounts: {})

    assert_predicate status, :success?, stderr
    assert_equal ["ok"], lines
  end
end
