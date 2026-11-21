# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class EnsureAdminUserTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-openproject/files/ruby/ensure_admin_user.rb",
    __dir__
  )

  PRELUDE = <<~RUBY
    require "json"

    class User
      attr_accessor :admin, :password_confirmation, :force_password_change
      attr_reader :login, :status

      def self.find_by(login:)
        row = JSON.parse(ENV.fetch("ACCOUNT"))
        return nil unless row && row.fetch("login") == login

        new(
          login: row.fetch("login"),
          mail: row.fetch("mail"),
          status: row.fetch("status"),
          stored_password: row.fetch("password"),
          persisted: true
        )
      end

      def initialize(login:, mail:, firstname: nil, lastname: nil, status: nil, stored_password: nil, persisted: false)
        @login = login
        @mail = mail
        @status = status
        @stored_password = stored_password
        @persisted = persisted
        @password = nil
      end

      def new_record?
        !@persisted
      end

      def check_password?(clear_password)
        !@stored_password.nil? && clear_password == @stored_password
      end

      def password=(value)
        @password = value
      end

      def activate
        @status = "active"
      end

      def save!
        changed = !@password.nil?
        @stored_password = @password if changed
        puts "STATE " + {
          "login" => login,
          "admin" => admin,
          "status" => status,
          "password" => @stored_password,
          "password_changed" => changed,
          "force_password_change" => force_password_change,
        }.to_json
      end
    end
  RUBY

  # @param login [String] OpenProject login of the account
  # @param status [String] account status before the run
  # @param password [String] password the account holds before the run
  # @return [Hash] the account row the stubbed User model finds
  def account(login, status:, password:)
    { "login" => login, "mail" => "#{login}@example.invalid", "status" => status, "password" => password }
  end

  # @param account [Hash, nil] the stored account, nil when OpenProject holds none
  # @param password [String] administrator password the deploy wants
  # @return [Array(Hash, String, Process::Status)] the saved account state, stderr and status
  def ensure_admin(account:, password:)
    stdout, stderr, status = Open3.capture3(
      {
        "ACCOUNT" => account.to_json,
        "OPENPROJECT_ADMIN_PASSWORD" => password,
        "OPENPROJECT_ADMIN_LOGIN" => "platformadmin",
        "OPENPROJECT_ADMIN_EMAIL" => "platformadmin@example.invalid",
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    state = stdout.lines.find { |line| line.start_with?("STATE ") }
    [state ? JSON.parse(state.delete_prefix("STATE ")) : {}, stderr, status]
  end

  def test_an_administrator_a_reseed_locked_is_active_again
    state, stderr, status = ensure_admin(
      account: account("platformadmin", status: "locked", password: "current"), password: "current"
    )

    assert_predicate status, :success?, stderr
    assert_equal "active", state["status"]
    assert_equal true, state["admin"]
    assert_equal false, state["password_changed"]
  end

  def test_a_rotated_password_replaces_the_stored_one_and_leaves_the_account_active
    state, stderr, status = ensure_admin(
      account: account("platformadmin", status: "locked", password: "before-rotation"), password: "after-rotation"
    )

    assert_predicate status, :success?, stderr
    assert_equal "after-rotation", state["password"]
    assert_equal "active", state["status"]
  end

  def test_a_missing_administrator_is_created_active_with_the_wanted_password
    state, stderr, status = ensure_admin(account: nil, password: "first")

    assert_predicate status, :success?, stderr
    assert_equal "platformadmin", state["login"]
    assert_equal true, state["admin"]
    assert_equal "active", state["status"]
    assert_equal "first", state["password"]
    assert_equal false, state["force_password_change"]
  end
end
