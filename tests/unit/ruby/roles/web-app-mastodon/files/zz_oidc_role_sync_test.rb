# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class MastodonOidcRoleSyncTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-mastodon/files/ruby/zz_oidc_role_sync.rb",
    __dir__
  )

  ADMINISTRATOR_GROUP = "/roles/web-app-mastodon/administrator"
  MODERATOR_GROUP = "/roles/web-app-mastodon/moderator"

  MODERATOR = 1
  ADMIN = 2
  OWNER = 3
  CUSTOM = 7

  ROLES = [
    { "id" => MODERATOR, "name" => "Moderator" },
    { "id" => ADMIN, "name" => "Admin" },
    { "id" => OWNER, "name" => "Owner" },
    { "id" => CUSTOM, "name" => "Helper" },
  ].freeze

  PRELUDE = <<~RUBY
    require "json"

    FakeRole = Struct.new(:id, :name)

    class UserRole
      ROLES = JSON.parse(ENV.fetch("ROLES")).map { |row| FakeRole.new(row.fetch("id"), row.fetch("name")) }

      def self.find_by(id:)
        ROLES.find { |role| role.id == id }
      end

      def self.find_by!(name:)
        ROLES.find { |role| role.name == name } || raise("no UserRole named \#{name}")
      end
    end

    class FakeAccount
      attr_reader :role_id

      def initialize(role_id, persisted)
        @role_id = role_id
        @persisted = persisted
      end

      def persisted?
        @persisted
      end

      def update!(role:)
        @role_id = role&.id
        puts "updated"
      end
    end

    class User
      def self.find_for_omniauth(_auth, _signed_in_resource = nil)
        role_id = ENV.fetch("ROLE_ID")
        FakeAccount.new(role_id.empty? ? nil : Integer(role_id), ENV.fetch("PERSISTED") == "true")
      end
    end

    class FakeAuth < Hash
      attr_reader :provider

      def initialize(provider, raw_info)
        super()
        @provider = provider
        self["extra"] = { "raw_info" => raw_info }
      end
    end

    module Rails
      def self.application
        self
      end

      def self.config
        self
      end

      def self.to_prepare
        yield
      end
    end
  RUBY

  DRIVER = <<~RUBY
    auth = FakeAuth.new(ENV.fetch("PROVIDER"), JSON.parse(ENV.fetch("RAW_INFO")))
    puts "role_id=\#{User.find_for_omniauth(auth).role_id.inspect}"
  RUBY

  # @param role_id [Integer, nil] UserRole id the account holds before the sign-in
  # @param groups [Array<String>, nil] groups claim of the ID token, nil for no claim
  # @param provider [String] omniauth provider of the sign-in
  # @param persisted [Boolean] whether the account is saved
  # @param enabled [String, nil] OIDC_ENABLED as the container sees it
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def sign_in(role_id:, groups:, provider: "openid_connect", persisted: true, enabled: "true")
    raw_info = groups.nil? ? {} : { "groups" => groups }
    stdout, stderr, status = Open3.capture3(
      {
        "OIDC_ENABLED" => enabled,
        "OIDC_RBAC_GROUPS_CLAIM" => "groups",
        "OIDC_RBAC_ADMINISTRATOR_GROUP" => ADMINISTRATOR_GROUP,
        "OIDC_RBAC_MODERATOR_GROUP" => MODERATOR_GROUP,
        "ROLES" => ROLES.to_json,
        "ROLE_ID" => role_id.to_s,
        "PERSISTED" => persisted.to_s,
        "PROVIDER" => provider,
        "RAW_INFO" => raw_info.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]\n#{DRIVER}", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_an_administrator_member_without_a_role_becomes_admin
    lines, stderr, status = sign_in(role_id: nil, groups: [ADMINISTRATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=#{ADMIN}"], lines
  end

  def test_a_moderator_member_without_a_role_becomes_moderator
    lines, stderr, status = sign_in(role_id: nil, groups: [MODERATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=#{MODERATOR}"], lines
  end

  def test_a_member_of_both_groups_becomes_admin
    lines, stderr, status = sign_in(role_id: nil, groups: [MODERATOR_GROUP, ADMINISTRATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=#{ADMIN}"], lines
  end

  def test_a_moderator_who_joins_the_administrator_group_is_promoted
    lines, stderr, status = sign_in(role_id: MODERATOR, groups: [ADMINISTRATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=#{ADMIN}"], lines
  end

  def test_an_admin_in_the_moderator_group_only_is_demoted_to_moderator
    lines, stderr, status = sign_in(role_id: ADMIN, groups: [MODERATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=#{MODERATOR}"], lines
  end

  def test_an_admin_outside_every_role_group_loses_the_role
    lines, stderr, status = sign_in(role_id: ADMIN, groups: ["/roles/web-app-other/administrator"])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=nil"], lines
  end

  def test_a_missing_groups_claim_removes_a_managed_role
    lines, stderr, status = sign_in(role_id: MODERATOR, groups: nil)

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=nil"], lines
  end

  def test_the_owner_role_is_left_untouched
    lines, stderr, status = sign_in(role_id: OWNER, groups: [])

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=#{OWNER}"], lines
  end

  def test_a_role_created_inside_mastodon_is_left_untouched
    lines, stderr, status = sign_in(role_id: CUSTOM, groups: [ADMINISTRATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=#{CUSTOM}"], lines
  end

  def test_a_role_id_without_a_role_is_replaced_from_the_groups
    lines, stderr, status = sign_in(role_id: 99, groups: [ADMINISTRATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["updated", "role_id=#{ADMIN}"], lines
  end

  def test_a_role_that_matches_the_groups_is_not_rewritten
    lines, stderr, status = sign_in(role_id: ADMIN, groups: [ADMINISTRATOR_GROUP])

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=#{ADMIN}"], lines
  end

  def test_an_account_without_role_or_group_is_not_rewritten
    lines, stderr, status = sign_in(role_id: nil, groups: [])

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=nil"], lines
  end

  def test_a_sign_in_through_another_provider_keeps_the_role
    lines, stderr, status = sign_in(role_id: ADMIN, groups: [], provider: "cas")

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=#{ADMIN}"], lines
  end

  def test_an_unsaved_account_is_not_synced
    lines, stderr, status = sign_in(role_id: nil, groups: [ADMINISTRATOR_GROUP], persisted: false)

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=nil"], lines
  end

  def test_disabled_oidc_leaves_the_sign_in_unpatched
    lines, stderr, status = sign_in(role_id: ADMIN, groups: [], enabled: nil)

    assert_predicate status, :success?, stderr
    assert_equal ["role_id=#{ADMIN}"], lines
  end
end
