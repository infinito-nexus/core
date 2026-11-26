# frozen_string_literal: true

require "json"
require "minitest/autorun"
require "open3"
require "tmpdir"

class DiscourseApplySettingsLoginMethodsTest < Minitest::Test
  SCRIPT = File.expand_path(
    "../../../../../../roles/web-app-discourse/files/ruby/apply_settings.rb",
    __dir__
  )

  SWITCHES = {
    "enable_local_logins" => "DISCOURSE_LOCAL_LOGINS",
    "enable_local_logins_via_email" => "DISCOURSE_LOGIN_EMAIL",
    "enable_passkeys" => "DISCOURSE_LOGIN_PASSKEY",
    "allow_new_registrations" => "DISCOURSE_ALLOW_NEW_REGISTRATIONS",
  }.freeze

  ENFORCED = { "enforce_second_factor" => "all", "enable_local_logins" => true }.freeze
  UNENFORCED_SSO = { "enforce_second_factor" => "no", "enable_local_logins" => false }.freeze

  PRELUDE = <<~'RUBY'
    require "json"

    module SiteSetting
      VALUES = JSON.parse(ENV.fetch("STORED"))

      def self.method_missing(name, *args)
        setting = name.to_s
        return VALUES.fetch(setting) unless setting.end_with?("=")

        write(setting.delete_suffix("="), args.fetch(0))
      end

      def self.respond_to_missing?(_name, _include_private = false) = true

      def self.write(setting, value)
        if setting == "enable_local_logins" && value == false && VALUES.fetch("enforce_second_factor") != "no"
          raise "local_login_cannot_be_disabled_if_second_factor_enforced"
        end
        if setting == "enforce_second_factor" && value != "no" && VALUES.fetch("enable_local_logins") == false
          raise "second_factor_cannot_enforce_with_disabled_local_login"
        end

        VALUES[setting] = value
      end
    end
  RUBY

  DRIVER = <<~'RUBY'
    load ARGV.fetch(0)
    puts JSON.generate(SiteSetting::VALUES)
  RUBY

  # @param stored [Hash] site settings before the run
  # @param enforcement [String] DISCOURSE_ENFORCE_SECOND_FACTOR
  # @param switches [Hash{String=>Boolean}] login method switches by site setting
  # @param script [String] path of the console script to run
  # @return [Array(Hash, String, Process::Status)] site settings after the run, stderr and status
  def apply(stored:, enforcement:, switches:, script: SCRIPT)
    environment = {
      "STORED" => stored.to_json,
      "DISCOURSE_FORCE_HTTPS" => "true",
      "DISCOURSE_ENFORCE_SECOND_FACTOR" => enforcement,
      "DISCOURSE_SITE_SETTINGS" => "{}",
      "DISCOURSE_OIDC_ENABLED" => "false",
    }
    switches.each { |setting, enabled| environment[SWITCHES.fetch(setting)] = enabled.to_s }
    stdout, stderr, status = Open3.capture3(environment, RbConfig.ruby, "-e", "#{PRELUDE}\n#{DRIVER}", script)
    [status.success? ? JSON.parse(stdout) : {}, stderr, status]
  end

  # @param enabled [Boolean] the value of every login method switch
  # @return [Hash{String=>Boolean}] every switch set to enabled
  def all_switches(enabled)
    SWITCHES.keys.to_h { |setting| [setting, enabled] }
  end

  def test_the_console_stores_each_switch_as_its_site_setting
    [[true, false, true, false], [false, true, false, true]].each do |flags|
      switches = SWITCHES.keys.zip(flags).to_h
      settings, stderr, status = apply(stored: ENFORCED.merge("enforce_second_factor" => "no"), enforcement: "no", switches: switches)

      assert_predicate status, :success?, stderr
      assert_equal switches, settings.slice(*SWITCHES.keys)
    end
  end

  def test_moving_to_sso_lifts_the_enforcement_before_the_local_logins_go_off
    settings, stderr, status = apply(stored: ENFORCED, enforcement: "no", switches: all_switches(false))

    assert_predicate status, :success?, stderr
    assert_equal UNENFORCED_SSO, settings.slice(*UNENFORCED_SSO.keys)
  end

  def test_moving_to_native_enforces_only_after_the_local_logins_are_on
    settings, stderr, status = apply(stored: UNENFORCED_SSO, enforcement: "all", switches: all_switches(true))

    assert_predicate status, :success?, stderr
    assert_equal ENFORCED, settings.slice(*ENFORCED.keys)
  end

  def test_a_lift_written_after_the_local_logins_is_refused
    source = File.read(SCRIPT)
    lift = source.lines.find { |line| line.end_with?(" if second_factor_enforcement == \"no\"\n") }
    refute_nil lift
    reordered = source.sub(lift, "").sub(/^SiteSetting\.enable_local_logins = .*\n/) { |line| line + lift }

    Dir.mktmpdir do |directory|
      script = File.join(directory, "apply_settings.rb")
      File.write(script, reordered)
      _settings, stderr, status = apply(stored: ENFORCED, enforcement: "no", switches: all_switches(false), script: script)

      refute_predicate status, :success?
      assert_includes stderr, "local_login_cannot_be_disabled_if_second_factor_enforced"
    end
  end
end
