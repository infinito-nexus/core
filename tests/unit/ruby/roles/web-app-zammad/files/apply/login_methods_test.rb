# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class ZammadLoginMethodsEnforcementTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../../roles/web-app-zammad/files/ruby/apply/login_methods.rb",
    __dir__
  )

  ENFORCED_ROLES = "two_factor_authentication_enforce_role_ids"

  PRELUDE = <<~'RUBY'
    require "json"

    module UserInfo
      def self.current_user_id=(_id); end
    end

    module Setting
      def self.set(name, value)
        puts JSON.generate([name, value])
      end
    end

    FakeRole = Struct.new(:id, :active)

    Relation = Struct.new(:rows) do
      def pluck(column) = rows.map { |row| row.public_send(column) }
    end

    class Role
      ALL = [FakeRole.new(3, true), FakeRole.new(1, true), FakeRole.new(2, false)].freeze

      def self.where(**conditions)
        Relation.new(ALL.select { |role| conditions.all? { |column, wanted| role.public_send(column) == wanted } })
      end
    end
  RUBY

  # @param second_factor [String] LOGIN_2FA as the container sees it
  # @param enforced [String] LOGIN_2FA_ENFORCED as the container sees it
  # @return [Array(Hash, String, Process::Status)] every Setting.set by name, stderr and status
  def apply(second_factor:, enforced:)
    stdout, stderr, status = Open3.capture3(
      { "ZAMMAD_SECURITY" => "{}", "LOGIN_2FA" => second_factor, "LOGIN_2FA_ENFORCED" => enforced },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.to_h { |line| JSON.parse(line) }, stderr, status]
  end

  def test_an_enforced_second_factor_covers_every_active_role
    settings, stderr, status = apply(second_factor: "true", enforced: "true")

    assert_predicate status, :success?, stderr
    assert_equal [1, 3], settings.fetch(ENFORCED_ROLES)
  end

  def test_an_offered_second_factor_enforces_no_role
    settings, stderr, status = apply(second_factor: "true", enforced: "false")

    assert_predicate status, :success?, stderr
    assert_equal [], settings.fetch(ENFORCED_ROLES)
  end
end
