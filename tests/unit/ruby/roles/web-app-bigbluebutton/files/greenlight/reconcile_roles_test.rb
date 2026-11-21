# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class GreenlightReconcileRolesTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-bigbluebutton/files/ruby/greenlight/reconcile_roles.rb",
    __dir__
  )

  ADMINISTRATOR = 1
  USER = 2
  GUEST = 3

  ROLES = [
    { "id" => ADMINISTRATOR, "name" => "Administrator", "provider" => "greenlight" },
    { "id" => USER, "name" => "User", "provider" => "greenlight" },
    { "id" => GUEST, "name" => "Guest", "provider" => "greenlight" },
  ].freeze

  PRELUDE = <<~RUBY
    require "json"

    FakeRole = Struct.new(:id, :name, :provider)

    class Role
      ALL = JSON.parse(ENV.fetch("ROLES")).map do |row|
        FakeRole.new(row.fetch("id"), row.fetch("name"), row.fetch("provider"))
      end

      def self.find_by!(name:, provider:)
        ALL.find { |role| role.name == name && role.provider == provider } ||
          raise("Couldn't find Role \#{name}")
      end
    end

    class FakeUser
      attr_reader :email, :provider, :role_id

      def initialize(row)
        @email = row.fetch("email")
        @provider = row.fetch("provider")
        @role_id = row.fetch("role_id")
      end

      def update_columns(role_id:, updated_at:)
        raise ArgumentError, "updated_at missing" if updated_at.nil?

        @role_id = role_id
        puts "set \#{email} role_id=\#{role_id}"
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
      ALL = JSON.parse(ENV.fetch("USERS")).map { |row| FakeUser.new(row) }

      def self.where(conditions)
        raise ArgumentError, conditions.inspect unless conditions.keys == [:provider]

        FakeRelation.new(ALL.select { |user| user.provider == conditions.fetch(:provider) })
      end
    end

    class Time
      def self.current
        now
      end
    end
  RUBY

  # @param email [String] e-mail of the Greenlight account
  # @param role_id [Integer] Greenlight role id before the reconcile
  # @param provider [String] Greenlight provider the account belongs to
  # @return [Hash] one account row for the stubbed User model
  def account(email, role_id, provider: "greenlight")
    { "email" => email, "role_id" => role_id, "provider" => provider }
  end

  # @param users [Array<Hash>] accounts the stubbed User model holds
  # @param admins [Array<String>] e-mails of the administrator role members
  # @param protected_emails [Array<String>] e-mails that stay administrators outside the role
  # @param roles [Array<Hash>] Greenlight roles the stubbed Role model holds
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def reconcile(users:, admins: [], protected_emails: [], roles: ROLES)
    stdout, stderr, status = Open3.capture3(
      {
        "USERS" => users.to_json,
        "ROLES" => roles.to_json,
        "RBAC_ADMIN_EMAILS" => admins.to_json,
        "RBAC_PROTECTED_EMAILS" => protected_emails.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_a_member_is_promoted_to_administrator
    lines, stderr, status = reconcile(
      users: [account("biber@example.org", USER)],
      admins: ["Biber@Example.org"]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["set biber@example.org role_id=#{ADMINISTRATOR}", "CHANGED promoted biber@example.org"], lines
  end

  def test_a_member_whose_stored_email_differs_in_case_is_promoted
    lines, stderr, status = reconcile(
      users: [account("Biber@Example.org", USER)],
      admins: ["biber@example.org"]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED promoted biber@example.org", lines.last
  end

  def test_an_administrator_outside_the_role_is_demoted_to_user
    lines, stderr, status = reconcile(users: [account("biber@example.org", ADMINISTRATOR)])

    assert_predicate status, :success?, stderr
    assert_equal ["set biber@example.org role_id=#{USER}", "CHANGED demoted biber@example.org"], lines
  end

  def test_the_protected_administrator_outside_the_role_stays_administrator
    lines, stderr, status = reconcile(
      users: [account("administrator@example.org", ADMINISTRATOR)],
      protected_emails: ["administrator@example.org"]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP"], lines
  end

  def test_the_protected_administrator_without_the_role_is_promoted
    lines, stderr, status = reconcile(
      users: [account("administrator@example.org", USER)],
      protected_emails: ["administrator@example.org"]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED promoted administrator@example.org", lines.last
  end

  def test_a_non_administrator_role_outside_the_role_group_is_kept
    lines, stderr, status = reconcile(users: [account("guest@example.org", GUEST)])

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP"], lines
  end

  def test_accounts_of_another_provider_are_left_alone
    lines, stderr, status = reconcile(
      users: [account("biber@example.org", ADMINISTRATOR, provider: "tenant")]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP"], lines
  end

  def test_several_changes_are_reported_in_one_line
    lines, stderr, status = reconcile(
      users: [account("biber@example.org", USER), account("mapache@example.org", ADMINISTRATOR)],
      admins: ["biber@example.org"]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED promoted biber@example.org, demoted mapache@example.org", lines.last
  end

  def test_converged_roles_report_noop
    lines, stderr, status = reconcile(
      users: [account("biber@example.org", ADMINISTRATOR), account("mapache@example.org", USER)],
      admins: ["biber@example.org"]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP"], lines
  end

  def test_a_member_without_an_email_promotes_no_account_without_one
    lines, stderr, status = reconcile(users: [account("", USER)], admins: [""])

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP"], lines
  end

  def test_a_missing_administrator_role_stops_the_reconcile
    _lines, stderr, status = reconcile(
      users: [account("biber@example.org", USER)],
      admins: ["biber@example.org"],
      roles: ROLES.reject { |role| role["name"] == "Administrator" }
    )

    refute_predicate status, :success?
    assert_match(/Couldn't find Role Administrator/, stderr)
  end
end
