# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class ReconcileAdminsTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-openproject/files/ruby/reconcile_admins.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    require "json"

    class FakeUser
      attr_reader :login

      def initialize(login, admin)
        @login = login
        @admin = admin
      end

      def admin?
        @admin
      end

      def update_column(column, value)
        raise ArgumentError, column.to_s unless column == :admin

        @admin = value
      end
    end

    class FakeRelation
      def initialize(users)
        @users = users
      end

      def exists?
        !@users.empty?
      end

      def find_each(&block)
        @users.each(&block)
      end
    end

    class User
      ACCOUNTS = JSON.parse(ENV.fetch("USERS")).map { |row| FakeUser.new(row.fetch("login"), row.fetch("admin")) }

      def self.by_login(login)
        FakeRelation.new(ACCOUNTS.select { |user| user.login.casecmp?(login) })
      end

      def self.where(type:)
        raise ArgumentError, type unless type == "User"

        FakeRelation.new(ACCOUNTS.dup)
      end
    end

    module LdapAuthSource
      def self.find_user(login)
        return nil unless JSON.parse(ENV.fetch("DIRECTORY")).include?(login)

        User::ACCOUNTS << FakeUser.new(login, false)
        User::ACCOUNTS.last
      end
    end
  RUBY

  # @param login [String] OpenProject login of the account
  # @param admin [Boolean] admin flag before the reconcile
  # @return [Hash] one account row for the stubbed User model
  def account(login, admin:)
    { "login" => login, "admin" => admin }
  end

  # @param users [Array<Hash>] accounts the stubbed User model holds
  # @param members [Array<String>] logins of the administrator role members
  # @param spared [Array<String>] logins the reconcile never touches
  # @param directory [Array<String>] logins LdapAuthSource.find_user can provision
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def reconcile(users:, members:, spared:, directory:)
    stdout, stderr, status = Open3.capture3(
      {
        "USERS" => users.to_json,
        "DIRECTORY" => directory.to_json,
        "OPENPROJECT_ADMIN_MEMBERS" => members.to_json,
        "OPENPROJECT_ADMIN_SPARED" => spared.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_a_member_without_an_account_is_provisioned_from_the_directory_and_promoted
    lines, stderr, status = reconcile(users: [], members: ["biber"], spared: [], directory: ["biber"])

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED biber provisioned", "CHANGED biber admin=true"], lines
  end

  def test_a_member_the_directory_does_not_know_is_not_provisioned
    lines, stderr, status = reconcile(users: [], members: ["ghost"], spared: [], directory: [])

    assert_predicate status, :success?, stderr
    assert_equal ["UNCHANGED"], lines
  end

  def test_a_member_is_matched_regardless_of_case
    lines, stderr, status = reconcile(
      users: [account("biber", admin: false)], members: ["Biber"], spared: [], directory: ["biber"]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED biber admin=true"], lines
  end

  def test_an_admin_outside_the_role_is_demoted
    lines, stderr, status = reconcile(
      users: [account("mapache", admin: true)], members: [], spared: [], directory: []
    )

    assert_predicate status, :success?, stderr
    assert_equal ["CHANGED mapache admin=false"], lines
  end

  def test_a_spared_admin_outside_the_role_stays_admin
    lines, stderr, status = reconcile(
      users: [account("administrator", admin: true)], members: [], spared: ["Administrator"], directory: []
    )

    assert_predicate status, :success?, stderr
    assert_equal ["UNCHANGED"], lines
  end

  def test_a_spared_member_is_never_provisioned
    lines, stderr, status = reconcile(
      users: [], members: ["gitlab-bot"], spared: ["gitlab-bot"], directory: ["gitlab-bot"]
    )

    assert_predicate status, :success?, stderr
    assert_equal ["UNCHANGED"], lines
  end

  def test_converged_flags_report_nothing
    lines, stderr, status = reconcile(
      users: [account("biber", admin: true), account("mapache", admin: false)],
      members: ["biber"],
      spared: [],
      directory: []
    )

    assert_predicate status, :success?, stderr
    assert_equal ["UNCHANGED"], lines
  end

  def test_a_missing_member_list_stops_the_reconcile
    _stdout, stderr, status = Open3.capture3(
      {
        "USERS" => [].to_json,
        "DIRECTORY" => [].to_json,
        "OPENPROJECT_ADMIN_MEMBERS" => nil,
        "OPENPROJECT_ADMIN_SPARED" => [].to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )

    refute_predicate status, :success?
    assert_match(/OPENPROJECT_ADMIN_MEMBERS/, stderr)
  end
end
