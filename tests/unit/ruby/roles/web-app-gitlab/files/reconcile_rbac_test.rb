# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class GitlabReconcileRbacTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-gitlab/files/ruby/reconcile_rbac.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    require "json"

    class FakeErrors
      def full_messages
        ["Email is invalid"]
      end
    end

    class FakeUser
      attr_reader :id, :username, :emails, :user_type
      attr_accessor :admin, :external

      def initialize(row)
        @id = row.fetch("id")
        @username = row.fetch("username")
        @emails = row.fetch("emails")
        @user_type = row.fetch("user_type")
        @admin = row.fetch("admin")
        @external = row.fetch("external")
        @saves = row.fetch("saves")
      end

      def admin?
        @admin
      end

      def external?
        @external
      end

      def save
        @saves
      end

      def errors
        FakeErrors.new
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

      def self.find_by_username(username)
        ALL.find { |user| user.username.casecmp?(username) }
      end

      def self.find_by_any_email(email)
        ALL.find { |user| user.emails.any? { |known| known.casecmp?(email) } }
      end

      def self.where(conditions)
        raise ArgumentError, conditions.inspect unless conditions == { user_type: :human }

        FakeRelation.new(ALL.select { |user| user.user_type == "human" })
      end
    end
  RUBY

  # @param id [Integer] primary key of the account
  # @param username [String] GitLab username
  # @param emails [Array<String>] every e-mail GitLab knows for the account
  # @param admin [Boolean] admin flag before the reconcile
  # @param external [Boolean] external flag before the reconcile
  # @param user_type [String] "human" or a bot type the reconcile must skip
  # @param saves [Boolean] whether User#save succeeds
  # @return [Hash] one account row for the stubbed User model
  def account(id, username, emails: ["#{username}@example.org"], admin: false, external: false,
              user_type: "human", saves: true)
    {
      "id" => id, "username" => username, "emails" => emails, "admin" => admin,
      "external" => external, "user_type" => user_type, "saves" => saves,
    }
  end

  # @param username [String] username of the role group member
  # @param email [String] e-mail of the role group member
  # @return [Hash] one entry of an rbac_members list
  def member(username, email: "#{username}@example.org")
    { "username" => username, "email" => email, "name" => username }
  end

  # @param users [Array<Hash>] accounts the stubbed User model holds
  # @param administrators [Array<Hash>] members of the administrator role
  # @param externals [Array<Hash>] members of the external role
  # @param keep [Array<String>] usernames that stay administrators outside the role
  # @return [Array(String, String, Process::Status)] stdout, stderr and status
  def reconcile(users:, administrators: [], externals: [], keep: [])
    Open3.capture3(
      {
        "USERS" => users.to_json,
        "GITLAB_RBAC_ADMINISTRATORS" => administrators.to_json,
        "GITLAB_RBAC_EXTERNALS" => externals.to_json,
        "GITLAB_RBAC_KEEP_ADMINS" => keep.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
  end

  def test_a_member_matched_by_username_is_promoted
    stdout, stderr, status = reconcile(
      users: [account(1, "biber", emails: ["unrelated@example.org"])],
      administrators: [member("biber", email: "other@example.org")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=true external=false\n", stdout
  end

  def test_a_member_matched_by_email_is_promoted
    stdout, stderr, status = reconcile(
      users: [account(1, "biber", emails: ["biber@example.org"])],
      administrators: [member("keycloak-name", email: "Biber@Example.org")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=true external=false\n", stdout
  end

  def test_a_member_without_email_and_unknown_username_matches_nobody
    stdout, stderr, status = reconcile(
      users: [account(1, "biber", emails: [""])],
      administrators: [member("ghost", email: "")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "UNCHANGED\n", stdout
  end

  def test_an_admin_outside_the_role_is_demoted
    stdout, stderr, status = reconcile(users: [account(1, "biber", admin: true)])

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=false external=false\n", stdout
  end

  def test_a_kept_administrator_outside_the_role_stays_admin
    stdout, stderr, status = reconcile(
      users: [account(1, "root", admin: true)],
      keep: ["ROOT"]
    )

    assert_predicate status, :success?, stderr
    assert_equal "UNCHANGED\n", stdout
  end

  def test_a_kept_administrator_without_the_flag_is_promoted
    stdout, stderr, status = reconcile(users: [account(1, "root")], keep: ["root"])

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED root admin=true external=false\n", stdout
  end

  def test_an_external_member_is_marked_external
    stdout, stderr, status = reconcile(
      users: [account(1, "biber")],
      externals: [member("biber")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=false external=true\n", stdout
  end

  def test_an_external_account_outside_the_role_loses_the_flag
    stdout, stderr, status = reconcile(users: [account(1, "biber", external: true)])

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=false external=false\n", stdout
  end

  def test_the_administrator_role_outranks_the_external_role
    stdout, stderr, status = reconcile(
      users: [account(1, "biber", external: true)],
      administrators: [member("biber")],
      externals: [member("biber")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=true external=false\n", stdout
  end

  def test_every_changed_account_reports_its_own_line
    stdout, stderr, status = reconcile(
      users: [account(1, "biber"), account(2, "mallory", admin: true)],
      administrators: [member("biber")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "CHANGED biber admin=true external=false\nCHANGED mallory admin=false external=false\n", stdout
  end

  def test_bot_accounts_are_left_alone
    stdout, stderr, status = reconcile(
      users: [account(1, "project_bot", admin: true, user_type: "project_bot")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "UNCHANGED\n", stdout
  end

  def test_converged_flags_report_unchanged
    stdout, stderr, status = reconcile(
      users: [account(1, "biber", admin: true), account(2, "mapache", external: true), account(3, "guest")],
      administrators: [member("biber")],
      externals: [member("mapache")]
    )

    assert_predicate status, :success?, stderr
    assert_equal "UNCHANGED\n", stdout
  end

  def test_a_rejected_save_fails_with_the_validation_errors
    _stdout, stderr, status = reconcile(
      users: [account(1, "biber", saves: false)],
      administrators: [member("biber")]
    )

    refute_predicate status, :success?
    assert_match(/could not update 'biber': Email is invalid/, stderr)
  end
end
