# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class DiscourseReconcileStaffTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-discourse/files/ruby/reconcile_staff.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    require "json"

    class FakeUser
      attr_reader :username, :username_lower, :email, :admin, :moderator

      def initialize(row)
        @username = row.fetch("username")
        @username_lower = @username.downcase
        @email = row.fetch("email")
        @admin = row.fetch("admin")
        @moderator = row.fetch("moderator")
      end

      def grant_admin!
        @admin = true
      end

      def revoke_admin!
        @admin = false
      end

      def grant_moderation!
        @moderator = true
      end

      def revoke_moderation!
        @moderator = false
      end
    end

    class FakeRelation
      def initialize(users)
        @users = users
      end

      def find_each(&block)
        @users.each(&block)
      end
    end

    class User
      def self.normalize_username(name)
        name.to_s.strip.empty? ? nil : name.to_s.unicode_normalize.downcase
      end

      def self.real
        FakeRelation.new(JSON.parse(ENV.fetch("USERS")).map { |row| FakeUser.new(row) })
      end
    end
  RUBY

  # @param username [String] Discourse username of the account
  # @param email [String] primary e-mail of the account
  # @param admin [Boolean] admin flag before the reconcile
  # @param moderator [Boolean] moderator flag before the reconcile
  # @return [Hash] one account row for the stubbed User.real
  def account(username, email: "#{username}@example.org", admin: false, moderator: false)
    { "username" => username, "email" => email, "admin" => admin, "moderator" => moderator }
  end

  # @param username [String] username of the role group member
  # @param email [String] e-mail of the role group member
  # @return [Hash] one entry of an rbac_members list
  def member(username, email: "#{username}@example.org")
    { "username" => username, "email" => email }
  end

  # @param users [Array<Hash>] accounts the stubbed User.real yields
  # @param administrators [Array<Hash>] members of the administrator role
  # @param moderators [Array<Hash>] members of the moderator role
  # @param kept [Array<String>] usernames the reconcile never touches
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def reconcile(users:, administrators: [], moderators: [], kept: [])
    stdout, stderr, status = Open3.capture3(
      {
        "USERS" => users.to_json,
        "DISCOURSE_RBAC_ADMINISTRATORS" => administrators.to_json,
        "DISCOURSE_RBAC_MODERATORS" => moderators.to_json,
        "DISCOURSE_RBAC_KEPT_ADMINISTRATORS" => kept.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_a_member_matched_by_username_is_granted_admin
    lines, stderr, status = reconcile(
      users: [account("biber", email: "unrelated@example.org")],
      administrators: [member("Biber", email: "other@example.org")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED granted_admin=biber"], lines
  end

  def test_a_member_matched_by_email_is_granted_admin
    lines, stderr, status = reconcile(
      users: [account("biber", email: "biber@example.org")],
      administrators: [member("keycloak-name", email: " Biber@Example.org ")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED granted_admin=biber"], lines
  end

  def test_an_admin_outside_the_role_is_revoked
    lines, stderr, status = reconcile(users: [account("biber", admin: true)])

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED revoked_admin=biber"], lines
  end

  def test_a_kept_administrator_outside_the_role_stays_admin
    lines, stderr, status = reconcile(
      users: [account("administrator", admin: true, moderator: true)],
      kept: ["Administrator"]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["UNCHANGED"], lines
  end

  def test_a_moderator_member_is_granted_moderation
    lines, stderr, status = reconcile(
      users: [account("biber")],
      moderators: [member("biber")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED granted_moderator=biber"], lines
  end

  def test_a_moderator_outside_the_role_is_revoked
    lines, stderr, status = reconcile(users: [account("biber", moderator: true)])

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED revoked_moderator=biber"], lines
  end

  def test_admin_and_moderator_flags_follow_their_own_role
    lines, stderr, status = reconcile(
      users: [account("biber", moderator: true)],
      administrators: [member("biber")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED granted_admin=biber", "CHANGED revoked_moderator=biber"], lines
  end

  def test_a_member_without_email_matches_no_account_without_email
    lines, stderr, status = reconcile(
      users: [account("other", email: "", admin: true)],
      administrators: [member("ghost", email: "")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED revoked_admin=other"], lines
  end

  def test_converged_flags_report_no_change
    lines, stderr, status = reconcile(
      users: [account("biber", admin: true), account("mapache", moderator: true), account("guest")],
      administrators: [member("biber")],
      moderators: [member("mapache")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["UNCHANGED"], lines
  end

  def test_a_missing_role_list_stops_the_reconcile
    _stdout, stderr, status = Open3.capture3(
      {
        "USERS" => [].to_json,
        "DISCOURSE_RBAC_ADMINISTRATORS" => [].to_json,
        "DISCOURSE_RBAC_MODERATORS" => nil,
        "DISCOURSE_RBAC_KEPT_ADMINISTRATORS" => [].to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )

    refute_predicate status, :success?
    assert_match(/DISCOURSE_RBAC_MODERATORS/, stderr)
  end
end
