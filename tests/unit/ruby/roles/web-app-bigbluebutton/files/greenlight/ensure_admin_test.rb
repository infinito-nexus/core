# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class GreenlightEnsureAdminSubjectTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-bigbluebutton/files/ruby/greenlight/ensure_admin.rb",
    __dir__
  )

  SUBJECT = "f3b1c2d4-0000-4000-8000-000000000001"

  PRELUDE = <<~'RUBY'
    require "json"

    FakeRole = Struct.new(:id, :name)

    class Role
      ALL = [FakeRole.new(1, "Administrator"), FakeRole.new(2, "User")].freeze

      def self.where(_condition, name) = ALL.select { |role| role.name.downcase == name }

      def self.first = ALL.first
    end

    class FakeUser
      attr_accessor :name, :email, :provider, :language, :status, :verified, :external_id, :password_confirmation
      attr_reader :id, :role_id

      def initialize(row)
        row.each { |column, value| instance_variable_set(:"@#{column}", value) }
      end

      def role=(role)
        @role_id = role.id
      end

      def verified? = verified == true

      def active? = status.to_s == "active"

      def authenticate(password) = password == @password

      def password=(password)
        @password = password
      end

      def update!(external_id:)
        @external_id = external_id
        puts "cleared #{id}"
      end

      def save!
        puts "saved #{id} external_id=#{external_id.inspect}"
      end
    end

    class Relation
      def initialize(users)
        @users = users
      end

      def first = @users.first

      def where = self

      def not(id:)
        Relation.new(@users.reject { |user| user.id == id })
      end

      def find_each(&block)
        @users.each(&block)
      end
    end

    class User
      ALL = JSON.parse(ENV.fetch("USERS")).map { |row| FakeUser.new(row) }

      def self.find_by(email:) = ALL.find { |user| user.email == email }

      def self.where(condition = nil, value = nil, **columns)
        return Relation.new(ALL.select { |user| user.email.downcase == value }) if condition

        Relation.new(ALL.select { |user| columns.all? { |column, wanted| user.public_send(column) == wanted } })
      end
    end
  RUBY

  # @param id [Integer] Greenlight user id
  # @param email [String] e-mail of the account
  # @param external_id [String, nil] subject the account is linked to
  # @return [Hash] one account row for the stubbed User model
  def account(id:, email:, external_id:)
    {
      "id" => id, "name" => "Administrator", "email" => email, "provider" => "greenlight", "language" => "en",
      "role_id" => 1, "verified" => true, "status" => "active", "external_id" => external_id, "password" => "secret",
    }
  end

  # @param users [Array<Hash>] accounts the stubbed User model holds
  # @param subject [String] NEW_EXTERNAL_ID, empty while SSO is off
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def ensure_admin(users:, subject:)
    stdout, stderr, status = Open3.capture3(
      {
        "NEW_NAME" => "Administrator",
        "NEW_EMAIL" => "admin@example.org",
        "DEFAULT_ADMIN_EMAIL" => "admin@example.com",
        "NEW_PASSWORD" => "secret",
        "NEW_EXTERNAL_ID" => subject,
        "USERS" => users.to_json,
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_the_keycloak_subject_is_stored_as_external_id
    lines, stderr, status = ensure_admin(
      users: [account(id: 1, email: "admin@example.org", external_id: nil)], subject: SUBJECT
    )

    assert_predicate status, :success?, stderr
    assert_equal ["saved 1 external_id=#{SUBJECT.inspect}", "CHANGED id=1 email=admin@example.org"], lines
  end

  def test_a_stored_subject_is_left_alone
    lines, stderr, status = ensure_admin(
      users: [account(id: 1, email: "admin@example.org", external_id: SUBJECT)], subject: SUBJECT
    )

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP id=1 email=admin@example.org"], lines
  end

  def test_without_sso_the_external_id_is_not_touched
    lines, stderr, status = ensure_admin(
      users: [account(id: 1, email: "admin@example.org", external_id: SUBJECT)], subject: ""
    )

    assert_predicate status, :success?, stderr
    assert_equal ["NOOP id=1 email=admin@example.org"], lines
  end

  def test_another_account_holding_the_subject_is_released_first
    lines, stderr, status = ensure_admin(
      users: [
        account(id: 1, email: "admin@example.org", external_id: nil),
        account(id: 2, email: "old-admin@example.org", external_id: SUBJECT),
      ],
      subject: SUBJECT
    )

    assert_predicate status, :success?, stderr
    assert_equal ["cleared 2", "saved 1 external_id=#{SUBJECT.inspect}", "CHANGED id=1 email=admin@example.org"], lines
  end
end
