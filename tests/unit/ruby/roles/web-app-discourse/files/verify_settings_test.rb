# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"

class DiscourseVerifySettingsReadbackTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-discourse/files/ruby/verify_settings.rb",
    __dir__
  )

  PRELUDE = <<~'RUBY'
    require "json"

    module SiteSetting
      VALUES = JSON.parse(ENV.fetch("STORED"))

      def self.refresh!; end

      def self.method_missing(name, *_args) = VALUES.fetch(name.to_s)

      def self.respond_to_missing?(_name, _include_private = false) = true
    end

    FakeAdmin = Struct.new(:admin, :active, :password) do
      def confirm_password?(candidate) = candidate == password
    end

    class User
      def self.find_by_email(_email) = FakeAdmin.new(true, true, "secret")
    end
  RUBY

  # @param stored [String] enforce_second_factor the running Discourse holds
  # @param wanted [String] DISCOURSE_ENFORCE_SECOND_FACTOR the deploy asked for
  # @return [Array(Array<String>, String, Process::Status)] stdout lines, stderr and status
  def read_back(stored:, wanted:)
    stdout, stderr, status = Open3.capture3(
      {
        "STORED" => {
          "enable_local_logins" => true,
          "enable_local_logins_via_email" => false,
          "enable_passkeys" => false,
          "allow_new_registrations" => false,
          "enforce_second_factor" => stored,
        }.to_json,
        "DISCOURSE_ADMIN_EMAIL" => "admin@example.org",
        "DISCOURSE_ADMIN_PASSWORD" => "secret",
        "DISCOURSE_LOCAL_LOGINS" => "true",
        "DISCOURSE_LOGIN_EMAIL" => "false",
        "DISCOURSE_LOGIN_PASSKEY" => "false",
        "DISCOURSE_ALLOW_NEW_REGISTRATIONS" => "false",
        "DISCOURSE_ENFORCE_SECOND_FACTOR" => wanted,
        "DISCOURSE_OIDC_ENABLED" => "false",
      },
      RbConfig.ruby, "-e", "#{PRELUDE}\nload ARGV[0]", SCRIPT
    )
    [stdout.lines.map(&:strip), stderr, status]
  end

  def test_an_applied_enforcement_reads_back_as_applied
    lines, stderr, status = read_back(stored: "all", wanted: "all")

    assert_predicate status, :success?, stderr
    assert_includes lines, "second_factor_enforcement_applied=true"
  end

  def test_an_enforcement_the_site_did_not_take_reads_back_as_missed
    lines, stderr, status = read_back(stored: "no", wanted: "all")

    assert_predicate status, :success?, stderr
    assert_includes lines, "second_factor_enforcement_applied=false"
  end
end
